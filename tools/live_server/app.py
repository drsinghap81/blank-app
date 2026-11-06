"""Live trading server (runs on your AWS box, holds the broker keys).

  GET  /api/health            -> status, mode (DRY RUN / LIVE), plan date
  POST /api/login {password}  -> {token}  (12-hour token for the phone app)
  GET  /api/account           -> Angel funds / holdings / positions (+ moomoo read-only if enabled)
  GET  /api/plan              -> today's trade plan sized with your capital, cash, holdings and free slots
  POST /api/order {id, qty, confirm}  -> places ONE order for a plan row after you tapped Send and confirmed
  GET  /api/orders            -> today's orders (Angel order book + this server's log)
  POST /api/mode {live, password, confirm} -> dry run (one tap) / live (password + type LIVE); stored in DATA_DIR/mode.json

Guards on every order: the server must be in LIVE mode (default: dry run - shows the exact order, sends nothing);
the row must be in today's plan (no free-form orders); quantity <= the plan size; order value <= MAX_ORDER_VALUE and 20% of
capital and the cash available; MAX_ORDERS_DAY a day; each plan row once a day; sells only up to the quantity you hold;
`confirm` must equal "<SIDE> <QTY> <SYMBOL>". Every request and order is logged to DATA_DIR/orders.jsonl.
Run: uvicorn app:app --host 127.0.0.1 --port 8000  (behind Caddy for HTTPS; see deploy/setup.sh)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
from datetime import datetime, timezone

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from brokers import AngelEquity, MockBroker, MoomooRO, amo_window, ist_now, market_open

# systemd's EnvironmentFile keeps inline "# comments" as part of the value, so strip them here
ENV = {k: re.sub(r"\s+#.*$", "", v).strip() for k, v in os.environ.items()}
DATA = ENV.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "var"))
os.makedirs(DATA, exist_ok=True)
LIVE_DEFAULT = ENV.get("LIVE_ORDERS", "0") == "1"   # used until the app's switch is first touched
ALLOW_APP_LIVE = ENV.get("ALLOW_APP_LIVE", "1") == "1"  # 0 = the app can only switch to dry run
PLAN_URL = ENV.get("PLAN_URL", "https://raw.githubusercontent.com/drsinghap81/blank-app/main/data/scan/trade_plan.json")
CAPITAL = float(ENV.get("CAPITAL", "0") or 0)            # 0 -> use Angel's net value
# Portfolio guard (ATH system 2017-26): lowering risk beat every drawdown rule (size cuts, hard portfolio stop-loss).
# So you set a DRAWDOWN BUDGET and the risk per trade follows from a Monte Carlo of the system (95% of paths stay
# within the budget; about budget / 30). The guard warns at 75% and 100% of the budget (it does not sell or block:
# hard stops lowered returns), and pauses new buys for PAUSE_DAYS after STREAK losing exits in a row.
DD_BUDGET = float(ENV.get("DD_BUDGET_PCT", "15")) / 100
# Monte Carlo (6 Nov 2026; ATH system 2017-26, 5 fill orders x 400 block-bootstrap 10-year paths, 13-week blocks):
# risk per trade % -> max drawdown % that 95% of paths stayed within. Risk = the level whose 95% drawdown = your budget.
MC95 = [(0.0, 0.0), (0.25, 8.6), (0.5, 16.4), (0.75, 23.3), (1.0, 28.9), (1.25, 33.4), (1.5, 38.5)]


def risk_for_budget(b_pct):
    for (r0, d0), (r1, d1) in zip(MC95, MC95[1:]):
        if b_pct <= d1:
            return (r0 + (r1 - r0) * (b_pct - d0) / (d1 - d0)) / 100
    return MC95[-1][0] / 100


RISK = float(ENV["RISK_PCT"]) / 100 if ENV.get("RISK_PCT") else risk_for_budget(DD_BUDGET * 100)
MAX_POS_PCT = float(ENV.get("MAX_POS_PCT", "10")) / 100     # 10%: caps a one-stock gap shock (cost ~0.3%/yr)
STREAK, PAUSE_DAYS = int(ENV.get("STREAK", "5")), int(ENV.get("PAUSE_DAYS", "14"))
MAX_POSITIONS = int(ENV.get("MAX_POSITIONS", "10"))
MAX_ORDER_VALUE = float(ENV.get("MAX_ORDER_VALUE", "300000"))
MAX_ORDERS_DAY = int(ENV.get("MAX_ORDERS_DAY", "10"))
# protective stop on Angel (GTT) after each filled buy. 9/21: at the plan stop (as backtested, intraday 5-day-low stop).
# ATH: a safety net ATH_NET_PCT below the plan stop - the system itself exits on a WEEKLY close below the 30-week SMA;
# a stop at the SMA would have hit 15% of trades (-5.5% each, most recovered); 15% below it hits ~1% (cost ~0.16%/trade).
PROTECT = ENV.get("PROTECT_STOPS", "1") == "1"
ATH_NET_PCT = float(ENV.get("ATH_NET_PCT", "15")) / 100
GTT_LIMIT_GAP = float(ENV.get("GTT_LIMIT_GAP_PCT", "5")) / 100     # limit this far below the trigger so a fast fall still fills
TOKEN_SECRET = ENV.get("TOKEN_SECRET", "")
PW_HASH = ENV.get("APP_PASSWORD_HASH", "")               # scrypt$<salt hex>$<hash hex>  (make with: python app.py hash)

broker = MockBroker() if ENV.get("MOCK_BROKER") == "1" else AngelEquity(ENV, DATA)
moomoo = MoomooRO(ENV)
app = FastAPI(title="Trend Desk live server")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in ENV.get("ALLOW_ORIGIN", "https://drsinghap81.github.io").split(",")],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


def is_live() -> bool:
    """Live/dry switch: var/mode.json (set from the app) overrides LIVE_ORDERS in .env."""
    try:
        return bool(json.load(open(os.path.join(DATA, "mode.json")))["live"])
    except Exception:  # noqa: BLE001
        return LIVE_DEFAULT


def set_live(on: bool):
    os.makedirs(DATA, exist_ok=True)
    json.dump(dict(live=bool(on), at=time.time()), open(os.path.join(DATA, "mode.json"), "w"))


def log(kind, **kw):
    with open(os.path.join(DATA, "orders.jsonl"), "a") as f:
        f.write(json.dumps(dict(t=datetime.now(timezone.utc).isoformat(timespec="seconds"), kind=kind, **kw), default=str) + "\n")


def today_log():
    p = os.path.join(DATA, "orders.jsonl"); d = ist_now().date().isoformat(); out = []
    if os.path.exists(p):
        for ln in open(p):
            try:
                r = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if r.get("kind") in ("order", "dry") and r.get("ist_date") == d:
                out.append(r)
    return out


# ------------------------------------------------------------------ auth
def make_hash(pw: str) -> str:
    salt = os.urandom(16)
    return "scrypt$" + salt.hex() + "$" + hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()


def check_pw(pw: str) -> bool:
    try:
        _, salt, h = PW_HASH.split("$")
        return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex(), h)
    except Exception:  # noqa: BLE001
        return False


def sign(exp: int) -> str:
    msg = str(exp).encode()
    return base64.urlsafe_b64encode(msg + b"." + hmac.new(TOKEN_SECRET.encode(), msg, hashlib.sha256).digest()).decode()


def auth(authorization: str = Header(default="")):
    try:
        raw = base64.urlsafe_b64decode(authorization.replace("Bearer ", "").encode())
        msg, mac = raw.split(b".", 1)
        ok = hmac.compare_digest(mac, hmac.new(TOKEN_SECRET.encode(), msg, hashlib.sha256).digest()) and int(msg) > time.time()
    except Exception:  # noqa: BLE001
        ok = False
    if not ok or not TOKEN_SECRET:
        raise HTTPException(401, "log in again")
    return True


FAILS = {}


class Login(BaseModel):
    password: str


@app.post("/api/login")
def login(body: Login, request: Request):
    ip = request.client.host if request.client else "?"
    n, t0 = FAILS.get(ip, (0, 0))
    if n >= 5 and time.time() - t0 < 900:
        raise HTTPException(429, "too many attempts, wait 15 minutes")
    if not PW_HASH or not TOKEN_SECRET or not check_pw(body.password):
        FAILS[ip] = (n + 1, time.time()); log("login_fail", ip=ip)
        raise HTTPException(401, "wrong password")
    FAILS.pop(ip, None); log("login", ip=ip)
    return dict(token=sign(int(time.time()) + 12 * 3600), live=is_live())


class Mode(BaseModel):
    live: bool
    password: str = ""
    confirm: str = ""


@app.post("/api/mode")
def mode(body: Mode, request: Request, _=Depends(auth)):
    """Dry run: one tap. Live: needs the app password again and the word LIVE typed."""
    if body.live:
        if not ALLOW_APP_LIVE:
            raise HTTPException(403, "switching to live from the app is turned off on the server (ALLOW_APP_LIVE=0)")
        ip = request.client.host if request.client else "?"
        n, t0 = FAILS.get(ip, (0, 0))
        if n >= 5 and time.time() - t0 < 900:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        if body.confirm.strip().upper() != "LIVE":
            raise HTTPException(400, 'type LIVE to confirm')
        if not check_pw(body.password):
            FAILS[ip] = (n + 1, time.time()); log("mode_fail", ip=ip)
            raise HTTPException(401, "wrong password")
        FAILS.pop(ip, None)
    set_live(body.live); log("mode", live=body.live)
    return dict(ok=True, mode="LIVE" if body.live else "DRY RUN")


@app.get("/api/health")
def health():
    return dict(ok=True, mode="LIVE" if is_live() else "DRY RUN", market_open=market_open(), amo=amo_window(), ist=ist_now().isoformat(timespec="minutes"))


# ------------------------------------------------------------------ plan + sizing
_plan = {"t": 0, "d": None}


def plan():
    if time.time() - _plan["t"] > 300 or _plan["d"] is None:
        if ENV.get("PLAN_FILE"):
            d = json.load(open(ENV["PLAN_FILE"]))
        else:
            r = requests.get(PLAN_URL, timeout=30); r.raise_for_status(); d = r.json()
        _plan.update(t=time.time(), d=d)
    return _plan["d"]


def journal():
    p = os.path.join(DATA, "journal.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def save_journal(j):
    json.dump(j, open(os.path.join(DATA, "journal.json"), "w"), indent=1)


def guard(acc):
    """High-water mark of account value, drawdown vs budget, losing-streak pause."""
    p = os.path.join(DATA, "guard.json")
    g = json.load(open(p)) if os.path.exists(p) else {}
    nav = float(acc.get("net") or 0) + float(acc.get("holdings_value") or 0) if ENV.get("NAV_INCLUDES_HOLDINGS") == "1" else float(acc.get("net") or 0)
    if nav > 0:
        g["peak"] = max(float(g.get("peak") or 0), nav); g["nav"] = nav; g["t"] = ist_now().isoformat(timespec="minutes")
        json.dump(g, open(p, "w"))
    dd = (g["nav"] / g["peak"] - 1) if g.get("peak") else 0.0
    used = -dd / DD_BUDGET if DD_BUDGET else 0
    pause = g.get("pause_until")
    paused = bool(pause and ist_now().date().isoformat() < pause)
    status = "paused" if paused else "over" if used >= 1 else "warn" if used >= 0.75 else "ok"
    msg = {"ok": "Within your drawdown budget.",
           "warn": "75% of your drawdown budget used. Normal for this system in a losing stretch: keep following the rules; no new rules mid-drawdown.",
           "over": "Drawdown is beyond your budget. The backtest's worst fall at this risk was about the budget; review: are all trades on plan? Consider lowering the budget's risk for new trades (not selling).",
           "paused": f"{STREAK} losing exits in a row: new buys paused until {pause}. Exits still apply."}[status]
    return dict(peak=g.get("peak"), nav=g.get("nav"), dd_pct=round(dd * 100, 1), budget_pct=DD_BUDGET * 100, used_pct=round(used * 100),
                risk_pct=round(RISK * 100, 2), max_pos_pct=MAX_POS_PCT * 100, streak=g.get("streak", 0), streak_max=STREAK,
                pause_until=pause, status=status, msg=msg)


def record_exit(sym, sell_px):
    """after a SELL: update the losing streak from the journal entry price; start a pause after STREAK losers."""
    J = journal(); e = J.get(sym) or {}
    p = os.path.join(DATA, "guard.json"); g = json.load(open(p)) if os.path.exists(p) else {}
    if e.get("entry"):
        g["streak"] = (g.get("streak", 0) + 1) if sell_px < e["entry"] else 0
        if g["streak"] >= STREAK:
            from datetime import timedelta
            g["pause_until"] = (ist_now().date() + timedelta(days=PAUSE_DAYS)).isoformat(); g["streak"] = 0
        json.dump(g, open(p, "w"))


def protect_level(kind, stop):
    if not stop:
        return None
    return stop if kind == "T921" else stop * (1 - ATH_NET_PCT)


def _protect(sym, e):
    """place the GTT stop for a filled journal entry (live only)."""
    trig = protect_level(e.get("kind"), e.get("stop"))
    if not (PROTECT and trig and e.get("qty")):
        return
    try:
        gid, gp = broker.gtt_stop(sym, e["qty"], trig, trig * (1 - GTT_LIMIT_GAP))
        e.update(gtt_id=gid, gtt_trigger=round(trig, 2)); log("gtt", symbol=sym, gtt_id=gid, trigger=round(trig, 2), qty=e["qty"])
    except Exception as ex:  # noqa: BLE001
        e["gtt_error"] = str(ex)[:200]; log("gtt_error", symbol=sym, error=str(ex)[:200])


def sync(acc=None):
    """Match journal entries to Angel's order book and holdings:
    pending buy -> filled (real price/qty, then the GTT stop) / rejected / cancelled;
    exiting -> sold (record the exit, streak); open but no longer held -> the stop fired or it was sold elsewhere."""
    J = journal()
    if not J:
        return J
    try:
        book = {str(o.get("id")): o for o in broker.orders()}
    except Exception as ex:  # noqa: BLE001
        log("sync_error", error=str(ex)[:200]); return J
    acc = acc or broker.account()
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    for p in acc["positions"]:
        held[p["symbol"]] = held.get(p["symbol"], 0) + p["qty"]
    today = ist_now().date().isoformat(); changed = False
    for sym, e in list(J.items()):
        st = e.get("state", "open")
        o = book.get(str(e.get("order_id"))) if st in ("pending", "exiting") else None
        stat = str((o or {}).get("status", "")).lower()
        if st == "pending" and o:
            if stat == "complete" or (stat in ("cancelled", "rejected") and (o.get("filled") or 0) > 0):
                e.update(state="open", entry=float(o.get("avg") or e["entry"]), qty=int(o.get("filled") or e["qty"]), filled=today)
                log("filled", symbol=sym, price=e["entry"], qty=e["qty"]); _protect(sym, e); changed = True
            elif stat in ("rejected", "cancelled"):
                log("not_filled", symbol=sym, status=stat, text=o.get("text")); J.pop(sym); changed = True
                e2 = dict(e, state=stat, text=o.get("text"), ended=today); J.setdefault("_done", {})[f"{sym}:{today}"] = e2
            else:
                e["order_status"] = o.get("status")
        elif st == "pending" and not o and e.get("since", today) < today and held.get(sym, 0) > 0:
            e.update(state="open", filled=today); _protect(sym, e); changed = True      # filled yesterday; book rolled over
        elif st == "exiting" and o and stat == "complete":
            px = float(o.get("avg") or e.get("exit_px") or 0); record_exit(sym, px); log("sold", symbol=sym, price=px)
            J.pop(sym); J.setdefault("_done", {})[f"{sym}:{today}"] = dict(e, state="sold", exit=px, ended=today); changed = True
        elif st == "open" and held.get(sym, 0) <= 0 and (e.get("gtt_id") or e.get("filled", today) < today):
            px = float(e.get("gtt_trigger") or 0) * (1 - GTT_LIMIT_GAP / 2) or e["entry"]
            record_exit(sym, px); log("gone", symbol=sym, assumed_px=px)
            J.pop(sym); J.setdefault("_done", {})[f"{sym}:{today}"] = dict(e, state="stopped or sold outside the app", exit=px, ended=today); changed = True
    if changed:
        d = J.get("_done") or {}
        if len(d) > 200:
            J["_done"] = dict(list(d.items())[-200:])
        save_journal(J)
    return J


def trades_view(J, acc):
    ltp = {h["symbol"]: h.get("ltp") for h in acc["holdings"]}
    out = []
    for sym, e in J.items():
        if sym.startswith("_"):
            continue
        px = ltp.get(sym); R = None
        if px and e.get("stop") and e.get("entry") and e["entry"] > e["stop"]:
            R = round((px - e["entry"]) / (e["entry"] - e["stop"]), 2)
        out.append(dict(symbol=sym, system=e.get("system"), state=e.get("state", "open"), qty=e.get("qty"), entry=e.get("entry"),
                        stop=e.get("stop"), ltp=px, R=R, since=e.get("since"), gtt_trigger=e.get("gtt_trigger"), gtt_id=e.get("gtt_id"),
                        gtt_error=e.get("gtt_error"), order_status=e.get("order_status")))
    done = sorted((J.get("_done") or {}).items(), key=lambda kv: kv[1].get("ended", ""), reverse=True)[:5]
    recent = [dict(symbol=k.split(":")[0], state=v.get("state"), ended=v.get("ended"), entry=v.get("entry"), exit=v.get("exit"), text=v.get("text")) for k, v in done]
    return out, recent


def sized(acc=None):
    P = plan(); acc = acc or broker.account()
    J = sync(acc)
    G = guard(acc)
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    for p in acc["positions"]:
        held[p["symbol"]] = held.get(p["symbol"], 0) + p["qty"]
    sys_open = [s for s in J if not s.startswith("_") and (held.get(s, 0) > 0 or J[s].get("state") == "pending")]
    cap = CAPITAL or acc["net"]
    slots = max(0, MAX_POSITIONS - len(sys_open))
    cash = acc["cash"]
    rows = []
    for r in P.get("top") or []:
        E = r.get("trigger") or r["price"]; stop = r["stop"]
        q = 0; why = ""
        if r["symbol"] in held:
            why = "already held"
        elif r["symbol"] in J and J[r["symbol"]].get("state") == "pending":
            why = "order sent - waiting for the fill"
        elif stop and E > stop:
            q = math.floor(min(RISK * cap / (E - stop), MAX_POS_PCT * cap / E, MAX_ORDER_VALUE / E))
        rows.append(dict(r, qty=max(0, q), value=round(max(0, q) * E, 0), risk_amt=round(max(0, q) * (E - stop), 0) if stop else None,
                         pct_cap=round(max(0, q) * E / cap * 100, 1) if cap else None, skip=why))
    # fill slots in rank order and within cash (buy-stops reserve cash too)
    left, used = cash, 0
    for r in rows:
        if r["skip"] or r["qty"] <= 0:
            continue
        if used >= slots:
            r["skip"] = "no free slot (max %d positions)" % MAX_POSITIONS; continue
        if r["value"] > left:
            q = math.floor(left / (r.get("trigger") or r["price"]))
            if q <= 0 or q < 0.25 * r["qty"]:            # don't open a token position
                r["skip"] = "not enough cash"; continue
            r["qty"], r["value"] = q, round(q * (r.get("trigger") or r["price"]), 0); r["note"] += " · cut to the cash left"
        left -= r["value"]; used += 1
    ex = [dict(e, qty=held.get(e["symbol"], 0)) for e in P.get("exits") or [] if held.get(e["symbol"], 0) > 0]
    if G["status"] == "paused":
        for r in rows:
            if not r["skip"]:
                r["skip"] = "paused: losing streak (guard)"
    trades, recent = trades_view(J, acc)
    return dict(guard=G, asof=P.get("asof"), generated=P.get("generated"), capital=cap, cash=cash, slots=slots, sys_open=sys_open,
                mode="LIVE" if is_live() else "DRY RUN", rows=rows, exits=ex, watch=P.get("watch") or [], held=held,
                trades=trades, recent=recent, protect=dict(on=PROTECT, ath_net_pct=ATH_NET_PCT * 100))


@app.get("/api/plan")
def get_plan(_=Depends(auth)):
    try:
        return sized()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"plan/broker error: {e}")


@app.get("/api/account")
def account(_=Depends(auth)):
    out = {}
    try:
        out["angel"] = broker.account()
    except Exception as e:  # noqa: BLE001
        out["angel"] = dict(error=str(e))
    try:
        out["moomoo"] = moomoo.account()
    except Exception as e:  # noqa: BLE001
        out["moomoo"] = dict(error=str(e))
    return out


@app.get("/api/orders")
def orders(_=Depends(auth)):
    try:
        book = broker.orders()
    except Exception as e:  # noqa: BLE001
        book = [dict(error=str(e))]
    return dict(book=book, log=today_log(), mode="LIVE" if is_live() else "DRY RUN")


class Order(BaseModel):
    id: str
    qty: int
    confirm: str


@app.post("/api/order")
def order(body: Order, _=Depends(auth)):
    S = sized()
    done = today_log()
    if any(r.get("id") == body.id and r.get("kind") == "order" for r in done):
        raise HTTPException(409, "already sent today")
    if len([r for r in done if r.get("kind") == "order"]) >= MAX_ORDERS_DAY:
        raise HTTPException(429, f"daily limit of {MAX_ORDERS_DAY} orders reached")
    row = next((r for r in S["rows"] if r["id"] == body.id), None)
    ex = next((r for r in S["exits"] if r["id"] == body.id), None)
    if not row and not ex:
        raise HTTPException(404, "not in today's plan")
    t = ist_now(); amo = amo_window(t) and not market_open(t)
    if row:
        if row["skip"]:
            raise HTTPException(400, row["skip"])
        if body.qty < 1 or body.qty > row["qty"]:
            raise HTTPException(400, f"quantity must be 1..{row['qty']}")
        E = row.get("trigger") or row["price"]
        if body.qty * E > min(MAX_ORDER_VALUE, MAX_POS_PCT * S["capital"], S["cash"]):
            raise HTTPException(400, "order value above the limits")
        side = "BUY"
        if row["kind"] == "ATH_STOP":
            if not market_open(t):
                raise HTTPException(400, "buy-stop orders are sent during market hours (09:15-15:30 IST); AMO does not take them")
            p = broker.params(row["symbol"], side, body.qty, row["price"], kind="SL", trigger=row["trigger"])
        else:
            if not (market_open(t) or amo):
                raise HTTPException(400, "send between 15:45 and 08:57 IST (AMO) or during market hours")
            price = row["price"]
            if market_open(t):          # during the session: limit 1% above the live price, never above the plan price + 3%
                ltp = broker.ltp(row["symbol"])
                price = min(ltp * 1.01, row["ref"] * 1.03) if ltp else price
            p = broker.params(row["symbol"], side, body.qty, price, amo=amo)
        sym = row["symbol"]
    else:
        if body.qty < 1 or body.qty > ex["qty"]:
            raise HTTPException(400, f"you hold {ex['qty']}")
        side, sym = "SELL", ex["symbol"]
        ltp = broker.ltp(sym) if market_open(t) else (ex.get("ref") or 0)
        if not ltp:
            raise HTTPException(400, "no price")
        p = broker.params(sym, side, body.qty, ltp * 0.99, amo=amo)
    if body.confirm.strip().upper() != f"{side} {body.qty} {sym}".upper():
        raise HTTPException(400, f'confirm must be "{side} {body.qty} {sym}"')
    rec = dict(id=body.id, symbol=sym, side=side, qty=body.qty, params=p, ist_date=t.date().isoformat())
    prot = None
    if side == "BUY" and PROTECT:
        lv = protect_level(row["kind"], row.get("stop"))
        if lv:
            prot = dict(trigger=round(lv, 2), limit=round(lv * (1 - GTT_LIMIT_GAP), 2),
                        note="at the plan stop (as backtested)" if row["kind"] == "T921" else f"safety net {ATH_NET_PCT * 100:.0f}% below the plan stop; the system exit is a weekly close below the 30-week SMA")
    if not is_live():
        log("dry", **rec)
        return dict(ok=True, mode="DRY RUN", sent=False, order=p, protect=prot,
                    msg="Dry run: this is exactly what would be sent. Switch to Live orders in the app to send for real.")
    if side == "SELL":
        J0 = journal(); e0 = J0.get(sym) or {}
        if e0.get("gtt_id"):
            try:
                broker.gtt_cancel(e0["gtt_id"], sym); log("gtt_cancel", symbol=sym, gtt_id=e0["gtt_id"])
            except Exception as ex:  # noqa: BLE001
                log("gtt_cancel_error", symbol=sym, error=str(ex)[:200])
    try:
        oid = broker.place(p)
    except Exception as e:  # noqa: BLE001
        log("order_error", error=str(e), **rec)
        raise HTTPException(502, f"Angel rejected: {e}")
    log("order", order_id=oid, **rec)
    J = journal()
    if side == "BUY":
        J[sym] = dict(since=t.date().isoformat(), system=row.get("system"), kind=row.get("kind"), stop=row.get("stop"),
                      entry=float(p["price"]), qty=body.qty, order_id=str(oid), state="pending")
    else:
        e = J.get(sym) or dict(since=t.date().isoformat(), system=ex.get("system"), qty=body.qty)
        e.update(state="exiting", order_id=str(oid), exit_px=float(p["price"]), gtt_id=None); J[sym] = e
    save_journal(J)
    try:
        sync()
    except Exception:  # noqa: BLE001
        pass
    return dict(ok=True, mode="LIVE", sent=True, order_id=oid, order=p, protect=prot)


@app.get("/api/quotes")
def quotes(_=Depends(auth)):
    """Live prices for today's plan rows, exits and app trades, plus the limit price a buy sent now would get."""
    P = plan(); t = ist_now()
    rows = (P.get("top") or []); syms = sorted({r["symbol"] for r in rows} | {e["symbol"] for e in P.get("exits") or []}
                                             | {k for k in journal() if not k.startswith("_")})
    try:
        Q = broker.quotes(syms)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"quotes: {ex}")
    out = {}
    for r in rows:
        q = Q.get(r["symbol"])
        if not q or not q["ltp"]:
            continue
        lim = min(q["ltp"] * 1.01, r["ref"] * 1.03) if r.get("ref") else None
        note = ""
        if r["kind"] == "ATH_STOP":
            note = "already above the trigger - the buy-stop would fill at once" if q["ltp"] >= r["trigger"] else f"{(r['trigger'] / q['ltp'] - 1) * 100:.1f}% below the trigger"
        elif lim and q["ltp"] * 1.01 > r["ref"] * 1.03:
            note = "more than 2% above the plan price - the limit (plan +3%) may not fill"
        out[r["id"]] = dict(symbol=r["symbol"], ltp=q["ltp"], chg_pct=round((q["ltp"] / q["prev"] - 1) * 100, 2) if q["prev"] else None,
                            vs_plan_pct=round((q["ltp"] / r["ref"] - 1) * 100, 2) if r.get("ref") else None,
                            limit_now=round(lim, 2) if lim and r["kind"] != "ATH_STOP" else None, note=note)
    return dict(market_open=market_open(t), ist=t.isoformat(timespec="seconds"), rows=out,
                symbols={s: Q[s] for s in syms if s in Q})


class BasketItem(BaseModel):
    id: str
    qty: int


class Basket(BaseModel):
    items: list[BasketItem]
    confirm: str


@app.post("/api/basket")
def basket(body: Basket, _=Depends(auth)):
    """Several plan buys with ONE typed confirmation ("BASKET <n>"). Each item still goes through every check in /api/order
    (in today's plan, qty <= plan, value/cash limits, once a day, daily order cap); one failing item doesn't stop the rest."""
    items = [i for i in body.items if i.qty > 0]
    if not items:
        raise HTTPException(400, "basket is empty")
    if len({i.id for i in items}) != len(items):
        raise HTTPException(400, "same trade twice in the basket")
    if body.confirm.strip().upper() != f"BASKET {len(items)}":
        raise HTTPException(400, f'confirm must be "BASKET {len(items)}"')
    S = sized(); rows = {r["id"]: r for r in S["rows"]}
    out = []
    for i in items:
        r = rows.get(i.id)
        if not r:
            out.append(dict(id=i.id, ok=False, error="not in today's plan")); continue
        try:
            res = order(Order(id=i.id, qty=i.qty, confirm=f"BUY {i.qty} {r['symbol']}"), True)
            out.append(dict(id=i.id, symbol=r["symbol"], qty=i.qty, ok=True, sent=res.get("sent"), order_id=res.get("order_id"),
                            order=res.get("order"), protect=res.get("protect")))
        except HTTPException as ex:
            out.append(dict(id=i.id, symbol=r["symbol"], qty=i.qty, ok=False, error=ex.detail))
    log("basket", n=len(items), ok=sum(o["ok"] for o in out))
    return dict(mode="LIVE" if is_live() else "DRY RUN", results=out)


# ------------------------------------------------------------------ background: fills + stops every 2 minutes in market hours
def _loop():
    while True:
        try:
            t = ist_now()
            if t.weekday() < 5 and (9, 0) <= (t.hour, t.minute) <= (16, 0) and any(not k.startswith("_") for k in journal()):
                sync()
        except Exception as ex:  # noqa: BLE001
            log("loop_error", error=str(ex)[:200])
        time.sleep(120)


@app.on_event("startup")
def _start():
    if ENV.get("MOCK_BROKER") != "1":
        import threading
        threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    import getpass
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        print(make_hash(getpass.getpass("App password: ")))
    elif len(sys.argv) > 1 and sys.argv[1] == "secret":
        print(os.urandom(32).hex())
