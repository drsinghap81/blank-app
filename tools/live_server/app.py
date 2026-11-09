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
# "Pick N" (8 Nov 2026): you choose how many positions the system book holds (3-10). Risk per trade then rises so the total
# initial risk stays at 10 x the guard risk, never above MAX_RISK_PCT (1%). Slots test, ATH 2017-26, 10% cap:
# 5 x 1% = 11.7% CAGR / -12.5% max DD vs 10 x 0.5% = 9.0% / -10.7% (fewer, larger positions did slightly better per unit DD).
MAX_RISK = float(ENV.get("MAX_RISK_PCT", "1")) / 100


def _picks_cfg() -> dict:
    try:
        return json.load(open(os.path.join(DATA, "picks.json")))
    except Exception:  # noqa: BLE001
        return {}


def picks() -> int:
    try:
        return max(3, min(MAX_POSITIONS, int(_picks_cfg()["n"])))
    except Exception:  # noqa: BLE001
        return MAX_POSITIONS


# Swing sleeve (8 Nov 2026): 9/21 trades run on the cash ATH isn't using, keeping SWING_RESERVE of capital free for new
# ATH breakouts (as in the backtest: ATH + 9/21 on idle cash 30.8%/yr, -24% at 1% each). Own risk (default = the guard
# risk, max MAX_RISK) and own slot count.
SWING_RESERVE = float(ENV.get("SWING_RESERVE_PCT", "15")) / 100
SWING_MAX = int(ENV.get("SWING_MAX", "10"))


def swing_risk() -> float:
    try:
        return max(0.0025, min(MAX_RISK, float(_picks_cfg()["swing_risk"]) / 100))
    except Exception:  # noqa: BLE001
        return RISK


# Systems as buckets (9 Nov 2026): each may hold at most alloc% of capital; all share one cash pool (Momentum first,
# swing buckets keep SWING_RESERVE in cash). NSE 2017-26 one-account test: Momentum <= 60% + Trend 9/21 <= 40% 23.1%/yr,
# worst fall -21.4%, vs Momentum alone 17.3%, -16.8%. Top Bottom runs on pledge margin (its own bot), not this cash.
BUCKETS = {"mom": 60, "tf": 40, "t9": 0, "rt": 0, "pt": 0, "s1": 0, "wc": 0, "tb": 100}   # optimised 9 Nov (trade_plan.buckets)
ALLOC_V = 2
SYS_BUCKET = {"Monthly ATH": "mom", "Trend 9/21": "tf", "9/21 trend": "t9", "Breakout retest": "rt", "Bottom pattern": "pt"}


def alloc() -> dict:
    a = dict(BUCKETS)
    try:
        cfg = _picks_cfg()
        if cfg.get("alloc_v") == ALLOC_V:          # settings saved before the 9 Nov optimisation are dropped
            a.update({k: float(v) for k, v in (cfg.get("alloc") or {}).items() if k in BUCKETS})
    except Exception:  # noqa: BLE001
        pass
    return a


def risk_now() -> float:
    return min(MAX_RISK, RISK * MAX_POSITIONS / picks())
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


class Picks(BaseModel):
    n: int | None = None
    swing_risk: float | None = None
    capital: float | None = None     # trading capital set in the app; 0 = use the account value; never above the account value
    alloc: dict | None = None        # bucket -> max % of capital it may hold (Live "Systems & allocation")


@app.post("/api/picks")
def set_picks(body: Picks, _=Depends(auth)):
    """How many positions the system book holds (3-10); risk per trade follows (see risk_now)."""
    cfg = _picks_cfg()
    n = picks() if body.n is None else max(3, min(MAX_POSITIONS, int(body.n)))
    sr = cfg.get("swing_risk") if body.swing_risk is None else max(0.25, min(MAX_RISK * 100, float(body.swing_risk)))
    capv = cfg.get("capital") if body.capital is None else max(0.0, float(body.capital))
    al = dict(cfg.get("alloc") or {}) if cfg.get("alloc_v") == ALLOC_V else {}
    for k, v in (body.alloc or {}).items():
        if k in BUCKETS:
            al[k] = max(0.0, min(100.0, float(v)))
    json.dump(dict(n=n, swing_risk=sr, capital=capv, alloc=al, alloc_v=ALLOC_V, at=time.time()), open(os.path.join(DATA, "picks.json"), "w"))
    log("picks", n=n, swing_risk=sr, capital=capv, alloc=al)
    return dict(picks=n, risk_pct=round(risk_now() * 100, 2), swing_risk_pct=round(swing_risk() * 100, 2), capital=capv, alloc=alloc())


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


@app.get("/dl/{key}")
def one_time_download(key: str):
    """one-time link created by fetch_candles.py (2 hours, single use) - market data only, no account data."""
    from fastapi.responses import FileResponse
    f = os.path.join(DATA, "dl.json")
    try:
        d = json.load(open(f))
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "no download")
    if not hmac.compare_digest(str(d.get("key")), key) or time.time() > d.get("until", 0):
        raise HTTPException(404, "no download")
    os.remove(f)
    return FileResponse(os.path.join(DATA, os.path.basename(d["file"])), filename=os.path.basename(d["file"]))


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
    # account value = cash + market value of holdings + today's delivery buys (buying a stock moves cash into shares; not a loss)
    nav = float(acc.get("net") or 0) + float(acc.get("holdings_value") or 0) + float(acc.get("positions_value") or 0)
    if g.get("basis") != "cash+holdings":                      # earlier versions measured cash only: restart the peak
        g = {k: v for k, v in g.items() if k in ("streak", "pause_until")}; g["basis"] = "cash+holdings"
    if nav > 0:
        g["peak"] = max(float(g.get("peak") or 0), nav); g["nav"] = nav; g["t"] = ist_now().isoformat(timespec="minutes")
        json.dump(g, open(p, "w"))
    dd = (g["nav"] / g["peak"] - 1) if g.get("peak") else 0.0
    used = -dd / DD_BUDGET if DD_BUDGET else 0
    pause = g.get("pause_until")
    paused = bool(pause and ist_now().date().isoformat() < pause)
    status = "paused" if paused else "over" if used >= 1 else "warn" if used >= 0.75 else "ok"
    msg = {"ok": "On track.",
           "warn": "3/4 of your limit used. Normal in a losing stretch - keep following the rules.",
           "over": "Past your limit. Check every trade is on plan; consider a smaller budget for new trades. Never sells for you.",
           "paused": f"{STREAK} losses in a row - new buys paused until {pause}."}[status]
    return dict(peak=g.get("peak"), nav=g.get("nav"), dd_pct=round(dd * 100, 1), budget_pct=DD_BUDGET * 100, used_pct=round(used * 100),
                risk_pct=round(risk_now() * 100, 2), base_risk_pct=round(RISK * 100, 2), picks=picks(), max_pos_pct=MAX_POS_PCT * 100, streak=g.get("streak", 0), streak_max=STREAK,
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
    return stop if kind in ("T921", "RETEST") else stop * (1 - ATH_NET_PCT)


def _protect(sym, e):
    """place the GTT stop for a filled journal entry (live only)."""
    trig = protect_level(e.get("kind"), e.get("stop"))
    if not (PROTECT and trig and e.get("qty")):
        return
    try:
        gid, gp = broker.gtt_stop(sym, e["qty"], trig, trig * (1 - GTT_LIMIT_GAP))
        e.update(gtt_id=gid, gtt_trigger=round(trig, 2)); e.pop("gtt_error", None)
        log("gtt", symbol=sym, gtt_id=gid, trigger=round(trig, 2), qty=e["qty"])
    except Exception as ex:  # noqa: BLE001
        e["gtt_error"] = str(ex)[:200]; e["gtt_tries"] = e.get("gtt_tries", 0) + 1; e["gtt_last"] = time.time()
        log("gtt_error", symbol=sym, error=str(ex)[:200])


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
        elif st == "open" and held.get(sym, 0) > 0 and not e.get("gtt_id") and e.get("gtt_tries", 0) < 4 \
                and time.time() - e.get("gtt_last", 0) > 600:
            _protect(sym, e); changed = True                                          # retry a failed protective stop
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


def retry_protect():
    """place any missing protective stop now (open trades still held, no GTT yet)."""
    J = journal(); acc = broker.account(); held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    for p in acc["positions"]:
        held[p["symbol"]] = held.get(p["symbol"], 0) + p["qty"]
    done = []
    for sym, e in J.items():
        if not sym.startswith("_") and e.get("state") == "open" and not e.get("gtt_id") and held.get(sym, 0) > 0:
            e["gtt_tries"] = 0; _protect(sym, e); done.append(dict(symbol=sym, gtt_id=e.get("gtt_id"), trigger=e.get("gtt_trigger"), error=e.get("gtt_error")))
    save_journal(J)
    return done


# Daily trail (9 Nov 2026): the protective GTT follows the system's own level, only ever up.
# Momentum (Monthly ATH): TRAIL_GAP below the 30-week SMA of completed weekly closes; Trend 9/21: TRAIL_GAP below the daily EMA 21.
# The systems still EXIT on closes (weekly close < SMA30, daily EMA9 < EMA21: "Sell next open" in Live); the GTT is the crash guard.
# Other systems keep their tested static stop (9/21 any stock: 5-day low; retests: 1 ATR). Runs 08:40-09:10 IST on weekdays,
# or from the app (/api/trail). Dry run: computes and shows the new level, changes nothing on Angel.
TRAIL_GAP = float(ENV.get("TRAIL_GAP_PCT", str(ATH_NET_PCT * 100))) / 100
TRAIL_SYS = ("Monthly ATH", "Trend 9/21")


def _weekly_sma30(c):
    """c: [(date, o, h, l, close)] completed daily candles -> 30-week SMA of completed weekly (Friday) closes, or None."""
    from datetime import date as _d, timedelta as _td
    wk = {}
    for d, *_x, cl in c:
        dd = _d.fromisoformat(d); end = dd + _td(days=(4 - dd.weekday()) % 7)
        wk[end] = cl                                     # last close of that week
    today = ist_now().date()
    ends = sorted(k for k in wk if k < today or (k == today and ist_now().hour >= 16))
    if len(ends) < 30:
        return None
    return sum(wk[k] for k in ends[-30:]) / 30


def _ema21(c):
    if len(c) < 60:
        return None
    a = 2 / 22; e = c[0][4]
    for x in c[1:]:
        e = a * x[4] + (1 - a) * e
    return e


def trail(force=False):
    today = ist_now().date().isoformat(); path = os.path.join(DATA, "trail.json")
    J = journal(); acc = account_cached(0)
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    live = is_live(); out = []
    for sym, e in J.items():
        if sym.startswith("_") or e.get("state") != "open" or held.get(sym, 0) <= 0 or e.get("system") not in TRAIL_SYS:
            continue
        cur = float(e.get("gtt_trigger") or 0)
        try:
            c = broker.daily_candles(sym)
            lvl = _weekly_sma30(c) if e["system"] == "Monthly ATH" else _ema21(c)
            if not lvl:
                out.append(dict(symbol=sym, result="not enough history")); continue
            guard = round(lvl * (1 - TRAIL_GAP), 2); last = c[-1][4]
            r = dict(symbol=sym, system=e["system"], level=round(lvl, 2), level_name="30-wk SMA" if e["system"] == "Monthly ATH" else "EMA 21",
                     close=round(last, 2), old=cur or None, new=guard)
            if not e.get("gtt_id"):
                r["result"] = "no stop on Angel yet (Retry stop first)"
            elif guard <= cur * 1.002:
                r["result"] = "unchanged (the stop only moves up)"; r["new"] = cur
            elif guard >= last * 0.97:
                r["result"] = "skipped: too close to the price"
            elif not live:
                r["result"] = "dry run: would raise"
            else:
                broker.gtt_modify(e["gtt_id"], sym, e.get("qty") or held[sym], guard, guard * (1 - GTT_LIMIT_GAP))
                e.update(gtt_trigger=guard, trail_prev=cur or None, trail_level=round(lvl, 2), trail_at=today)
                log("gtt_trail", symbol=sym, old=cur, new=guard, level=round(lvl, 2)); r["result"] = "raised"
            out.append(r)
        except Exception as ex:  # noqa: BLE001
            out.append(dict(symbol=sym, result=f"error, stop left where it was: {str(ex)[:120]}"))
            log("gtt_trail_error", symbol=sym, error=str(ex)[:200])
    save_journal(J)
    json.dump(dict(day=today, at=ist_now().strftime("%H:%M"), live=live, results=out), open(path, "w"))
    return out


def last_trail():
    try:
        return json.load(open(os.path.join(DATA, "trail.json")))
    except Exception:  # noqa: BLE001
        return None


@app.post("/api/trail")
def trail_now(_=Depends(auth)):
    return dict(results=trail(force=True), gap_pct=TRAIL_GAP * 100)


@app.post("/api/protect")
def protect_now(_=Depends(auth)):
    return dict(results=retry_protect())


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
                        gtt_error=e.get("gtt_error"), order_status=e.get("order_status"), trail_prev=e.get("trail_prev"),
                        trail_level=e.get("trail_level"), trail_at=e.get("trail_at")))
    done = sorted((J.get("_done") or {}).items(), key=lambda kv: kv[1].get("ended", ""), reverse=True)[:5]
    recent = [dict(symbol=k.split(":")[0], state=v.get("state"), ended=v.get("ended"), entry=v.get("entry"), exit=v.get("exit"), text=v.get("text")) for k, v in done]
    return out, recent


def perf_view(J, acc):
    """Return on everything sent from the app: open trades at today's price plus closed trades at their exit (before costs)."""
    ltp = {h["symbol"]: h.get("ltp") for h in acc["holdings"]}
    o = dict(n=0, cost=0.0, value=0.0); c = dict(n=0, cost=0.0, pnl=0.0, wins=0); sysd = {}; first = None
    def add(sy, cost, pnl):
        d = sysd.setdefault(sy or "Other", dict(cost=0.0, pnl=0.0, n=0)); d["cost"] += cost; d["pnl"] += pnl; d["n"] += 1
    for sym, e in J.items():
        if sym.startswith("_") or e.get("state", "open") != "open" or not (e.get("qty") and e.get("entry")):
            continue
        q, en = e["qty"], e["entry"]; px = ltp.get(sym) or en
        o["n"] += 1; o["cost"] += q * en; o["value"] += q * px; add(e.get("system"), q * en, q * (px - en))
        first = min(first or e.get("since") or "9", e.get("since") or "9")
    for k, e in (J.get("_done") or {}).items():
        if not (e.get("exit") and e.get("entry") and e.get("qty")):
            continue          # rejected or cancelled orders never filled
        q, en = e["qty"], e["entry"]; pnl = q * (e["exit"] - en)
        c["n"] += 1; c["cost"] += q * en; c["pnl"] += pnl; c["wins"] += pnl > 0; add(e.get("system"), q * en, pnl)
        first = min(first or e.get("since") or "9", e.get("since") or "9")
    o["pnl"] = o["value"] - o["cost"]; tot = o["pnl"] + c["pnl"]; cost = o["cost"] + c["cost"]
    r2 = lambda x: round(x, 2)
    return dict(open=dict(n=o["n"], cost=r2(o["cost"]), value=r2(o["value"]), pnl=r2(o["pnl"])),
                closed=dict(n=c["n"], cost=r2(c["cost"]), pnl=r2(c["pnl"]), wins=c["wins"]),
                total_pnl=r2(tot), total_pct=r2(tot / cost * 100) if cost else None, since=None if first == "9" else first,
                systems=[dict(system=k, n=v["n"], pnl=r2(v["pnl"]), pct=r2(v["pnl"] / v["cost"] * 100) if v["cost"] else None) for k, v in sysd.items()])


_acc = {"t": 0, "d": None}


def account_cached(max_age=5):
    """one Angel account read per few seconds (Angel rate-limits holdings / funds calls)."""
    if _acc["d"] is None or time.time() - _acc["t"] > max_age:
        _acc.update(d=broker.account(), t=time.time())
    return _acc["d"]


ANGEL_WHY = {"AB4036": "Angel doesn't take API orders for this stock: the exchange has it on its cautionary (surveillance) list. "
                       "If you still want it, place it yourself in the Angel app.",
             "AB1007": "Angel login session problem - try again in a minute.",
             "AB4008": "price outside the allowed band for today."}


def angel_msg(e):
    m = str(e); code = re.search(r"\[(AB\d+)\]", m)
    return ANGEL_WHY.get(code.group(1), m) if code else m


def equity_log(value):
    """Account value (cash + holdings at today's price) once per day, for the app's equity curve; today's entry is overwritten."""
    p = os.path.join(DATA, "equity.json")
    try:
        E = json.load(open(p))
    except Exception:  # noqa: BLE001
        E = {}
    d = ist_now().date().isoformat()
    if value and E.get(d) != value:
        E[d] = value; E = dict(sorted(E.items())[-800:])
        try:
            json.dump(E, open(p, "w"))
        except Exception:  # noqa: BLE001
            pass
    return sorted(E.items())


def sized(acc=None):
    P = plan(); acc = acc or account_cached()
    J = sync(acc)
    G = guard(acc)
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    for p in acc["positions"]:
        held[p["symbol"]] = held.get(p["symbol"], 0) + p["qty"]
    sys_open = [s for s in J if not s.startswith("_") and (held.get(s, 0) > 0 or J[s].get("state") == "pending")]
    acct = CAPITAL or acc["net"]
    try:
        app_cap = float(_picks_cfg().get("capital") or 0)
    except Exception:  # noqa: BLE001
        app_cap = 0.0
    cap = min(app_cap, acct) if app_cap > 0 and acct else acct      # capital set in the app, never above the account value
    N = picks(); RK = risk_now(); SR = swing_risk()
    sw_open = [s for s in sys_open if J[s].get("system") in ("9/21 trend", "Trend 9/21", "Breakout retest", "Bottom pattern")]
    AL = alloc(); ltp = {h["symbol"]: h.get("ltp") for h in acc["holdings"]}
    expo = {k: 0.0 for k in AL}
    for s_ in sys_open:
        b = SYS_BUCKET.get(J[s_].get("system"), "mom"); e_ = J[s_]
        expo[b] = expo.get(b, 0.0) + (held.get(s_, 0) or e_.get("qty") or 0) * float(ltp.get(s_) or e_.get("entry") or 0)
    room = {k: AL[k] / 100 * cap - expo.get(k, 0.0) for k in AL}
    ath_open = [s for s in sys_open if s not in sw_open]
    slots = max(0, N - len(ath_open)); sw_slots = max(0, SWING_MAX - len(sw_open))
    cash = acc["cash"]
    rows = []
    for r in [dict(x, tier="top") for x in P.get("top") or []] + [dict(x, tier="more") for x in P.get("more") or []] + \
            [dict(x, tier="swing") for x in P.get("swing") or []]:
        E = r.get("trigger") or r["price"]; stop = r["stop"]
        q = 0; why = ""
        if r["symbol"] in held:
            why = "already held"
        elif r["symbol"] in J and J[r["symbol"]].get("state") == "pending":
            why = "order sent - waiting for the fill"
        elif stop and E > stop:
            q = math.floor(min((SR if r["tier"] == "swing" else RK) * cap / (E - stop), MAX_POS_PCT * cap / E, MAX_ORDER_VALUE / E))
        rows.append(dict(r, qty=max(0, q), value=round(max(0, q) * E, 0), risk_amt=round(max(0, q) * (E - stop), 0) if stop else None,
                         pct_cap=round(max(0, q) * E / cap * 100, 1) if cap else None, skip=why))
    # each row must fit your actual cash on its own (cut to cash, no token positions); rank order only adds a note
    # when the row would use cash / a slot that the higher-ranked rows would need if you bought them too
    left, used = cash, 0
    sw_cash = max(0.0, cash - SWING_RESERVE * cap); sw_left, sw_used = sw_cash, 0
    for r in rows:
        if r["skip"] or r["qty"] <= 0:
            continue
        sw = r["tier"] == "swing"
        bk = r.get("bucket") or ("tf" if sw else "mom"); r["bucket"] = bk
        E0 = r.get("trigger") or r["price"]
        if r["value"] > room.get(bk, 0):
            q = math.floor(max(0.0, room.get(bk, 0)) / E0)
            if q <= 0 or q < 0.25 * r["qty"]:
                r["skip"] = ("system switched off (0%% in Systems & allocation)" if AL.get(bk, 0) <= 0 else "bucket full (%s max %g%% of capital)" % (bk, AL.get(bk, 0))); continue
            r["qty"], r["value"] = q, round(q * E0, 0); r["note"] = r.get("note", "") + " · cut to the bucket's room"
            r["risk_amt"] = round(q * (E0 - r["stop"]), 0); r["pct_cap"] = round(q * E0 / cap * 100, 1) if cap else None
        if (sw_slots if sw else slots) <= 0:
            r["skip"] = ("no free swing slot (max %d)" % SWING_MAX) if sw else ("no free slot (you picked %d positions)" % N); continue
        E = r.get("trigger") or r["price"]
        avail = sw_cash if sw else cash
        if r["value"] > avail:
            q = math.floor(avail / E)
            if q <= 0 or q < 0.25 * r["qty"]:            # don't open a token position
                r["skip"] = ("no idle cash (%d%% of capital kept for ATH breakouts)" % round(SWING_RESERVE * 100)) if sw else "not enough cash"; continue
            r["qty"], r["value"] = q, round(q * E, 0); r["note"] += " · cut to your cash"
            r["risk_amt"] = round(q * (E - r["stop"]), 0); r["pct_cap"] = round(q * E / cap * 100, 1) if cap else None
        if sw:
            if r["value"] > sw_left or sw_used >= sw_slots:
                r["note"] += " · uses idle cash or a slot the swing trades above would need"; r["reserve"] = True
            sw_left -= r["value"]; sw_used += 1; room[bk] = room.get(bk, 0) - r["value"]
            continue
        if r["value"] > left or used >= slots:
            r["note"] += " · uses cash or a slot the trades ranked above would need"
            r["reserve"] = True
        left -= r["value"]; used += 1; room[bk] = room.get(bk, 0) - r["value"]
    # an exit applies to the system the app bought the stock under (holdings bought elsewhere get every exit listed)
    ex = [dict(e, qty=held.get(e["symbol"], 0)) for e in P.get("exits") or [] if held.get(e["symbol"], 0) > 0
          and (e["symbol"] not in J or not J[e["symbol"]].get("system") or J[e["symbol"]]["system"] == e.get("system"))]
    if G["status"] == "paused":
        for r in rows:
            if not r["skip"]:
                r["skip"] = "paused: losing streak (guard)"
    trades, recent = trades_view(J, acc)
    real = round(acc["cash"] + (acc.get("holdings_value") or 0) + (acc.get("positions_value") or 0), 2)
    return dict(real_value=real, equity=equity_log(real), holdings=[dict(symbol=h["symbol"], qty=h["qty"], ltp=h.get("ltp"), avg=h.get("avg"),
                value=round(h["qty"] * (h.get("ltp") or 0), 2)) for h in acc["holdings"] if h["qty"] > 0], guard=G, asof=P.get("asof"), generated=P.get("generated"), capital=cap, cash=cash, slots=slots, sys_open=sys_open, picks=N, risk_pct=round(RK * 100, 2), account_value=acct, capital_set=app_cap or None,
                buckets=[dict(key=k, pct=AL[k], used=round(expo.get(k, 0.0)), room=round(max(0.0, room.get(k, 0.0)))) for k in AL],
                swing=dict(risk_pct=round(SR * 100, 2), slots=sw_slots, max=SWING_MAX, open=len(sw_open), idle_cash=round(sw_cash), reserve_pct=SWING_RESERVE * 100),
                mode="LIVE" if is_live() else "DRY RUN", rows=rows, exits=ex, watch=P.get("watch") or [], held=held,
                trades=trades, recent=recent, perf=perf_view(J, acc), protect=dict(on=PROTECT, ath_net_pct=ATH_NET_PCT * 100, trail_gap_pct=TRAIL_GAP * 100),
                trail=last_trail())


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
    try:
        S = sized()
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"couldn't read your Angel account: {angel_msg(ex)}")
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
        if market_open(t):
            ltp = broker.ltp(row["symbol"])
            st, lim, why = live_check(row, ltp)
            if st in ("broken", "missed", "ran"):
                raise HTTPException(400, f"not sent: {why}")
            if row["kind"] in ("ATH_STOP", "TF_STOP") and st == "wait":
                p = broker.params(row["symbol"], side, body.qty, row["price"], kind="SL", trigger=row["trigger"])
            else:                       # 9/21, breakouts, or a buy-stop already triggered: LIMIT near the live price, capped
                p = broker.params(row["symbol"], side, body.qty, lim or row["price"])
        else:
            if row["kind"] in ("ATH_STOP", "TF_STOP"):
                raise HTTPException(400, "buy-stop orders are sent during market hours (09:15-15:30 IST); AMO does not take them")
            if not amo:
                raise HTTPException(400, "send between 15:45 and 08:57 IST (AMO) or during market hours")
            p = broker.params(row["symbol"], side, body.qty, row["price"], amo=True)
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
                        note="at the plan stop (as backtested)" if row["kind"] in ("T921", "RETEST") else f"safety net {ATH_NET_PCT * 100:.0f}% below the plan stop; the system exit is a weekly close below the 30-week SMA")
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
        _acc["d"] = None
        raise HTTPException(502, f"Angel rejected {sym}: {angel_msg(e)}")
    _acc["d"] = None
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


CHASE = float(ENV.get("CHASE_PCT", "3")) / 100     # how far past the trigger / plan close a buy may still be sent


def live_check(r, ltp):
    """In market hours, what a plan buy may do at this live price (matches the backtest: buy at the trigger / next open).
    -> (state, limit_price or None, text). states: wait (buy-stop below trigger), triggered, ok, missed, ran, broken."""
    if not ltp:
        return "ok", None, ""
    if r.get("stop") and ltp <= r["stop"]:
        return "broken", None, f"below the plan stop ({r['stop']:.2f}) - the setup is invalid; can't send"
    if r["kind"] in ("ATH_STOP", "TF_STOP"):
        T = r["trigger"]
        if ltp < T:
            return "wait", None, f"{(T / ltp - 1) * 100:.1f}% below the trigger - the buy-stop waits on Angel"
        if ltp <= T * (1 + CHASE):
            return "triggered", round(min(ltp * 1.01, T * (1 + CHASE)), 2), f"triggered (+{(ltp / T - 1) * 100:.1f}% over the trigger) - buy now as a limit"
        return "missed", None, f"{(ltp / T - 1) * 100:.1f}% above the trigger - ran too far past the tested entry; skip"
    ref = r.get("ref") or r["price"]
    if ltp > ref * (1 + CHASE):
        return "ran", None, f"{(ltp / ref - 1) * 100:.1f}% above the plan close - more than {CHASE * 100:.0f}%; wait or skip"
    return "ok", round(min(ltp * 1.01, ref * (1 + CHASE)), 2), ""


@app.get("/api/quotes")
def quotes(_=Depends(auth)):
    """Live prices for today's plan rows, exits and app trades, plus the limit price a buy sent now would get."""
    P = plan(); t = ist_now()
    rows = (P.get("top") or []) + (P.get("more") or []) + (P.get("swing") or []); syms = sorted({r["symbol"] for r in rows} | {e["symbol"] for e in P.get("exits") or []}
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
        st, lim, note = live_check(r, q["ltp"]) if market_open(t) else ("ok", None, "")
        out[r["id"]] = dict(symbol=r["symbol"], ltp=q["ltp"], chg_pct=round((q["ltp"] / q["prev"] - 1) * 100, 2) if q["prev"] else None,
                            vs_plan_pct=round((q["ltp"] / r["ref"] - 1) * 100, 2) if r.get("ref") else None,
                            state=st, limit_now=lim, note=note, sendable=st in ("ok", "triggered", "wait"))
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
    try:
        S = sized()
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"couldn't read your Angel account: {angel_msg(ex)}")
    rows = {r["id"]: r for r in S["rows"]}
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
        except Exception as ex:  # noqa: BLE001  (never let one item kill the basket)
            out.append(dict(id=i.id, symbol=r["symbol"], qty=i.qty, ok=False, error=angel_msg(ex)))
        time.sleep(0.4)
    log("basket", n=len(items), ok=sum(o["ok"] for o in out))
    return dict(mode="LIVE" if is_live() else "DRY RUN", results=out)


# ------------------------------------------------------------------ Top Bottom bot (tools/angel/run_bot.py, TB_CHANNEL=app)
TB_DIR = ENV.get("TB_STATE_DIR") or os.path.join(DATA, "tb")
TB_APP = os.path.join(TB_DIR, "app")


def _tbr(name, default):
    try:
        return json.load(open(os.path.join(TB_APP, name)))
    except Exception:  # noqa: BLE001
        return default


def _tbw(name, obj):
    os.makedirs(TB_APP, exist_ok=True)
    tmp = os.path.join(TB_APP, name + ".tmp"); json.dump(obj, open(tmp, "w")); os.replace(tmp, os.path.join(TB_APP, name))


def tb_live():
    try:
        return bool(json.load(open(os.path.join(TB_DIR, "mode.json"))).get("live"))
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/tb")
def tb_state(_=Depends(auth)):
    msgs = []
    try:
        with open(os.path.join(TB_APP, "messages.jsonl"), encoding="utf-8") as f:
            msgs = [json.loads(x) for x in f.readlines()[-25:]]
    except Exception:  # noqa: BLE001
        pass
    P = _tbr("pending.json", {}); A = _tbr("answers.json", {})
    return dict(mode="LIVE" if tb_live() else "DRY RUN", status=_tbr("status.json", {}),
                pending=[dict(key=k, **v) for k, v in P.items()], answers=A, messages=msgs[::-1])


class TBAnswer(BaseModel):
    key: str
    value: bool | str
    confirm: str = ""


@app.post("/api/tb/answer")
def tb_answer(body: TBAnswer, _=Depends(auth)):
    P = _tbr("pending.json", {})
    if body.key not in P:
        raise HTTPException(404, "that approval is no longer pending")
    if body.value is True and tb_live() and body.confirm.strip().upper() != "YES":
        raise HTTPException(400, 'type YES to approve a live trade')
    A = _tbr("answers.json", {}); A[body.key] = body.value; _tbw("answers.json", A)
    if not P[body.key].get("options"):
        P.pop(body.key); _tbw("pending.json", P)
    log("tb_answer", key=body.key, value=body.value)
    return dict(ok=True)


class TBCmd(BaseModel):
    cmd: str


@app.post("/api/tb/cmd")
def tb_cmd(body: TBCmd, _=Depends(auth)):
    if body.cmd not in ("/status", "/stop", "/flat"):
        raise HTTPException(400, "unknown command")
    C = _tbr("commands.json", []); C.append(body.cmd); _tbw("commands.json", C)
    log("tb_cmd", cmd=body.cmd)
    return dict(ok=True, note="the bot picks this up within a few seconds while it runs (09:00-15:30 IST)")


@app.post("/api/tb/mode")
def tb_mode(body: Mode, request: Request, _=Depends(auth)):
    """same safety as the equity switch: live needs the app password + LIVE; dry run is one tap. Applies from the bot's next start."""
    if body.live:
        ip = request.client.host if request.client else "?"
        n, t0 = FAILS.get(ip, (0, 0))
        if n >= 5 and time.time() - t0 < 900:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        if body.confirm.strip().upper() != "LIVE":
            raise HTTPException(400, "type LIVE to confirm")
        if not check_pw(body.password):
            FAILS[ip] = (n + 1, time.time()); raise HTTPException(401, "wrong password")
    os.makedirs(TB_DIR, exist_ok=True)
    json.dump(dict(live=bool(body.live), at=time.time()), open(os.path.join(TB_DIR, "mode.json"), "w"))
    log("tb_mode", live=body.live)
    return dict(ok=True, mode="LIVE" if body.live else "DRY RUN")


# ------------------------------------------------------------------ background: fills + stops every 2 minutes in market hours
def _loop():
    while True:
        try:
            t = ist_now()
            if t.weekday() < 5 and (9, 0) <= (t.hour, t.minute) <= (16, 0) and any(not k.startswith("_") for k in journal()):
                sync()
            if t.weekday() < 5 and (8, 40) <= (t.hour, t.minute) <= (9, 10) and (last_trail() or {}).get("day") != t.date().isoformat() \
                    and any(not k.startswith("_") for k in journal()):
                trail()
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
