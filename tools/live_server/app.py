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


def sized(acc=None):
    P = plan(); acc = acc or broker.account()
    G = guard(acc)
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    for p in acc["positions"]:
        held[p["symbol"]] = held.get(p["symbol"], 0) + p["qty"]
    J = journal()
    sys_open = [s for s in J if held.get(s, 0) > 0]                 # system positions still held
    cap = CAPITAL or acc["net"]
    slots = max(0, MAX_POSITIONS - len(sys_open))
    cash = acc["cash"]
    rows = []
    for r in P.get("top") or []:
        E = r.get("trigger") or r["price"]; stop = r["stop"]
        q = 0; why = ""
        if r["symbol"] in held:
            why = "already held"
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
    return dict(guard=G, asof=P.get("asof"), generated=P.get("generated"), capital=cap, cash=cash, slots=slots, sys_open=sys_open,
                mode="LIVE" if is_live() else "DRY RUN", rows=rows, exits=ex, watch=P.get("watch") or [], held=held)


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
    if not is_live():
        log("dry", **rec)
        return dict(ok=True, mode="DRY RUN", sent=False, order=p, msg="Dry run: this is exactly what would be sent. Switch to Live orders in the app to send for real.")
    try:
        oid = broker.place(p)
    except Exception as e:  # noqa: BLE001
        log("order_error", error=str(e), **rec)
        raise HTTPException(502, f"Angel rejected: {e}")
    log("order", order_id=oid, **rec)
    if side == "BUY":
        J = journal(); J[sym] = dict(since=t.date().isoformat(), system=(row or {}).get("system"), stop=(row or {}).get("stop"),
                                     entry=float(p["price"]), qty=body.qty); save_journal(J)
    else:
        record_exit(sym, float(p["price"]))
        J = journal(); J.pop(sym, None); save_journal(J)
    return dict(ok=True, mode="LIVE", sent=True, order_id=oid, order=p)


if __name__ == "__main__":
    import getpass
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        print(make_hash(getpass.getpass("App password: ")))
    elif len(sys.argv) > 1 and sys.argv[1] == "secret":
        print(os.urandom(32).hex())
