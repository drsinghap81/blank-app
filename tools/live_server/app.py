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
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from brokers import ET_TZ, AngelEquity, MockBroker, MockMoomoo, MoomooTrade, amo_window, ist_now, market_open

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
BUCKETS = {"mom": 60, "tf": 40, "t9": 0, "rt": 0, "pt": 0, "vcp": 0, "my": 0, "s1": 0, "wc": 0, "tb": 100}   # optimised 9 Nov (trade_plan.buckets)
ALLOC_V = 2
SYS_BUCKET = {"Monthly ATH": "mom", "Trend 9/21": "tf", "9/21 trend": "t9", "Breakout retest": "rt", "Bottom pattern": "pt", "VCP": "vcp", "My pick": "my"}
STOP_KINDS = ("ATH_STOP", "TF_STOP", "VCP_STOP")   # buy-stop rows (stop-limit day orders)


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
GTT_LIMIT_GAP = float(ENV.get("GTT_LIMIT_GAP_PCT", "5")) / 100
MY_TARGET_R = float(ENV.get("MY_TARGET_R", "2"))      # 11 Nov 2026: default target for your own picks = 2 x (entry - stop) above entry     # limit this far below the trigger so a fast fall still fills
TOKEN_SECRET = ENV.get("TOKEN_SECRET", "")
PW_HASH = ENV.get("APP_PASSWORD_HASH", "")               # scrypt$<salt hex>$<hash hex>  (make with: python app.py hash)

broker = MockBroker() if ENV.get("MOCK_BROKER") == "1" else AngelEquity(ENV, DATA)
moomoo = MockMoomoo() if ENV.get("MOCK_BROKER") == "1" else MoomooTrade(ENV)
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
            if r.get("kind") in ("order", "dry", "sip") and r.get("ist_date") == d:
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


_HB = {"start": time.time(), "loop": time.time(), "tb": time.time()}     # 11 Nov 2026: heartbeats for the watchdog


@app.get("/api/health")
def health():
    """Never touches Angel or the disk-heavy parts: the watchdog calls it every minute (10 s limit)."""
    now = time.time(); up = {}
    try:
        up = json.load(open(os.path.join(DATA, "update_status.json")))
    except Exception:  # noqa: BLE001
        pass
    try:
        la = os.getloadavg()[0]
        mem = {k: int(v.split()[0]) for k, v in (ln.split(":", 1) for ln in open("/proc/meminfo")) if k in ("MemTotal", "MemAvailable")}
    except Exception:  # noqa: BLE001
        la, mem = None, {}
    return dict(ok=True, mode="LIVE" if is_live() else "DRY RUN", market_open=market_open(), amo=amo_window(), ist=ist_now().isoformat(timespec="minutes"),
                uptime=int(now - _HB["start"]), loop_age=int(now - _HB["loop"]), tb_age=int(now - _HB["tb"]),
                version=up.get("version"), latest=up.get("latest"), update_waiting=bool(up.get("waiting")), load=la,
                mem_mb=round(mem.get("MemTotal", 0) / 1024), mem_free_mb=round(mem.get("MemAvailable", 0) / 1024))


class Admin(BaseModel):
    action: str
    password: str = ""
    confirm: str = ""


@app.post("/api/admin")
def admin(body: Admin, request: Request, _=Depends(auth)):
    """App buttons (Settings -> Server): 'update' = pull the latest code now (even in market hours) and restart;
    'restart' = restart the app server. Needs the app password + typing UPDATE / RESTART. The root watchdog acts within a minute."""
    act = body.action.lower()
    if act not in ("update", "restart"):
        raise HTTPException(400, "unknown action")
    ip = request.client.host if request.client else "?"
    n, t0 = FAILS.get(ip, (0, 0))
    if n >= 5 and time.time() - t0 < 900:
        raise HTTPException(429, "too many attempts, wait 15 minutes")
    if body.confirm.strip().upper() != act.upper():
        raise HTTPException(400, f"type {act.upper()} to confirm")
    if not check_pw(body.password):
        FAILS[ip] = (n + 1, time.time()); raise HTTPException(401, "wrong password")
    open(os.path.join(DATA, "cmd_" + act), "w").write(str(time.time())); log("admin", action=act)
    return dict(ok=True, msg=f"{'Update' if act == 'update' else 'Restart'} requested: within about a minute the server "
                f"{'pulls the latest code and ' if act == 'update' else ''}restarts (about 10 seconds offline). Your stops stay on Angel.")


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
    return stop if kind in ("T921", "RETEST", "PATTERN", "VCP", "VCP_STOP", "MY_GTT") else stop * (1 - ATH_NET_PCT)


def _protect(sym, e):
    """place the GTT stop for a filled journal entry (live only)."""
    trig = protect_level(e.get("kind"), e.get("stop"))
    if not (PROTECT and trig and e.get("qty")):
        return
    try:
        tgt = e.get("target")
        if tgt and tgt > trig:                      # 11 Nov 2026: your own picks get stop + target in one Angel GTT (OCO)
            try:
                gid, gp = broker.gtt_oco(sym, e["qty"], tgt, trig, trig * (1 - GTT_LIMIT_GAP))
                e.update(gtt_id=gid, gtt_trigger=round(trig, 2), oco=True); e.pop("gtt_error", None); e.pop("oco_error", None)
                log("gtt_oco", symbol=sym, gtt_id=gid, trigger=round(trig, 2), target=round(tgt, 2), qty=e["qty"])
                return
            except Exception as ex:  # noqa: BLE001   Angel refused the two-leg GTT: the stop goes on alone, you get told
                e["oco_error"] = str(ex)[:160]; e["oco"] = False; log("gtt_oco_error", symbol=sym, error=str(ex)[:200])
                alert("nostop", sym, f"Angel refused the stop + target GTT ({str(ex)[:60]}); the stop is placed alone. Set the target in Angel if you want it.",
                      key=f"oco:{sym}:{ist_now().date()}")
        gid, gp = broker.gtt_stop(sym, e["qty"], trig, trig * (1 - GTT_LIMIT_GAP))
        e.update(gtt_id=gid, gtt_trigger=round(trig, 2)); e.pop("gtt_error", None)
        log("gtt", symbol=sym, gtt_id=gid, trigger=round(trig, 2), qty=e["qty"])
    except Exception as ex:  # noqa: BLE001
        e["gtt_error"] = str(ex)[:200]; e["gtt_tries"] = e.get("gtt_tries", 0) + 1; e["gtt_last"] = time.time()
        log("gtt_error", symbol=sym, error=str(ex)[:200])
        if e["gtt_tries"] >= 2:
            alert("nostop", sym, f"Protective stop could NOT be placed on Angel ({str(ex)[:80]}). Place it in the Angel app.", key=f"nostop:{sym}:{ist_now().date()}")


def held_map(acc, held=None):
    """Shares held per symbol. 11 Nov 2026: Angel lists a same-day delivery buy in BOTH the holdings (T1) and the position
    book; adding the two doubled the quantity, and the protective GTT for PFC / RECLTD went on for twice the shares.
    A delivery position now adds only what the holdings don't already show; intraday positions (net qty) still add."""
    held = dict(held if held is not None else {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0})
    base = dict(held)
    for p in acc["positions"]:
        q = p["qty"]
        if str(p.get("product")).upper() in ("DELIVERY", "CNC") and q > 0:
            extra = max(0, q - base.get(p["symbol"], 0)); base[p["symbol"]] = max(0, base.get(p["symbol"], 0) - q)
            held[p["symbol"]] = held.get(p["symbol"], 0) + extra
        else:
            held[p["symbol"]] = held.get(p["symbol"], 0) + q
    return held


TESTED_R = {"RETEST": 3.0}        # 12 Nov 2026: systems tested WITH a fixed target get it on Angel automatically (OCO)


def auto_target(e, row=None):
    """Tested target for a trade, or None. Breakout retest 3R; Bottom pattern its measured move (from the plan row);
    your own picks MY_TARGET_R. Momentum / Trend 9/21 / 9/21 any / VCP: None (their tested exit is a trailing line)."""
    if e.get("system") in TRAIL_SYS:
        return None
    entry, stop = float(e.get("entry") or 0), float(e.get("stop") or 0)
    kind, sysn = e.get("kind"), e.get("system")
    if row and row.get("target") and kind in ("RETEST", "PATTERN"):
        return round(float(row["target"]), 2)
    if not (entry > stop > 0):
        return None
    if kind == "RETEST" or sysn == "Breakout retest":
        return round(entry + TESTED_R["RETEST"] * (entry - stop), 2)
    if kind == "PATTERN" or sysn == "Bottom pattern":
        return round(float(e["plan_target"]), 2) if e.get("plan_target") else None
    if kind == "MY_GTT" or sysn == "My pick":
        return round(entry + MY_TARGET_R * (entry - stop), 2)
    return None


def gtt_buy_upkeep(J, acc):
    """13 Nov 2026: system buy-stops placed as GTT buys stay valid only while the setup does. Cancel (and alert) when the month
    has changed (the trigger is that month's high), the stock left the plan, or the price is at/below the plan stop."""
    if not is_live():
        return False
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    try:
        P = plan(); plan_syms = {r["symbol"] for r in plan_rows(P) if r.get("kind") in STOP_KINDS}
    except Exception:  # noqa: BLE001
        return False
    month = ist_now().strftime("%Y-%m"); ch = False
    for sym, e in list(J.items()):
        if sym.startswith("_") or e.get("state") != "pending" or not e.get("gtt_buy_id") or e.get("kind") not in STOP_KINDS or held.get(sym, 0) > 0:
            continue
        why = None
        if e.get("gtt_month") and e["gtt_month"] != month:
            why = "the month ended without the breakout (the trigger was last month's high)"
        elif sym not in plan_syms:
            why = "the setup is no longer in the plan"
        else:
            try:
                lt = broker.ltp(sym)
            except Exception:  # noqa: BLE001
                lt = None
            if lt and e.get("stop") and lt <= float(e["stop"]):
                why = f"the price {lt:.2f} fell to the plan stop {float(e['stop']):.2f}"
        if not why:
            continue
        try:
            broker.gtt_cancel(e["gtt_buy_id"], sym); log("gtt_buy_cancel", symbol=sym, gtt_id=e["gtt_buy_id"], why=why)
        except Exception as ex:  # noqa: BLE001
            log("gtt_buy_cancel_error", symbol=sym, error=str(ex)[:200]); continue
        J.pop(sym); J.setdefault("_done", {})[f"{sym}:{ist_now().date()}"] = dict(e, state="cancelled", text=why, ended=ist_now().date().isoformat())
        alert("exit", sym, f"GTT buy cancelled: {why}.", key=f"gttbuy:{sym}:{ist_now().date()}"); ch = True
    return ch


def backfill_targets(J, acc):
    """Open trades from a target-tested system that only have a stop GTT: cancel it and place stop + target (OCO), once.
    Skipped if the price is already at/above the target (that is a decision for you, not an automatic sell)."""
    if not (PROTECT and is_live()):
        return False
    ltp = {h["symbol"]: h.get("ltp") for h in acc["holdings"]}; today = ist_now().date().isoformat(); ch = False
    for sym, e in J.items():
        if sym.startswith("_") or e.get("state") != "open" or e.get("target") or e.get("auto_tgt") or not e.get("gtt_id") or e.get("oco"):
            continue
        t = auto_target(e)
        if not t:
            continue
        e["auto_tgt"] = today; ch = True
        if (ltp.get(sym) or 0) >= t:
            log("auto_target_skip", symbol=sym, target=t, ltp=ltp.get(sym)); continue
        e["target"] = t
        try:
            broker.gtt_cancel(e["gtt_id"], sym); log("gtt_cancel", symbol=sym, gtt_id=e["gtt_id"]); e.pop("gtt_id", None)
        except Exception as ex:  # noqa: BLE001
            log("auto_target_error", symbol=sym, error=str(ex)[:200]); continue
        e["gtt_tries"] = 0; _protect(sym, e); log("auto_target", symbol=sym, target=t, oco=bool(e.get("oco")))
    return ch


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
    held = held_map(acc, held)
    today = ist_now().date().isoformat(); changed = False
    for sym, e in list(J.items()):
        st = e.get("state", "open")
        o = book.get(str(e.get("order_id"))) if st in ("pending", "exiting") else None
        stat = str((o or {}).get("status", "")).lower()
        if st == "open" and e.get("qty") and 0 < held.get(sym, 0) < e["qty"]:
            # 11 Nov 2026: a stop sized for more shares than you hold (same-day buys were counted twice) -> resize it
            old = e["qty"]; e["qty"] = int(held[sym]); changed = True; log("qty_fix", symbol=sym, old=old, new=e["qty"])
            if e.get("gtt_id") and e.get("oco"):
                try:
                    broker.gtt_cancel(e["gtt_id"], sym); e.pop("gtt_id", None); _protect(sym, e); log("gtt_resized", symbol=sym, qty=e["qty"], oco=True)
                except Exception as ex:  # noqa: BLE001
                    log("gtt_error", symbol=sym, error=str(ex)[:200])
            elif e.get("gtt_id") and e.get("gtt_trigger"):
                try:
                    gid, _p = broker.gtt_modify(e["gtt_id"], sym, e["qty"], e["gtt_trigger"], e["gtt_trigger"] * (1 - GTT_LIMIT_GAP))
                    e["gtt_id"] = gid; log("gtt_resized", symbol=sym, qty=e["qty"])
                except Exception as ex:  # noqa: BLE001
                    log("gtt_error", symbol=sym, error=str(ex)[:200])
                    alert("nostop", sym, f"Stop GTT is for {old} shares but you hold {e['qty']}; resize failed ({str(ex)[:60]}). Edit it in Angel.",
                          key=f"qtyfix:{sym}:{today}")
        if st == "pending" and o:
            if stat == "complete" or (stat in ("cancelled", "rejected") and (o.get("filled") or 0) > 0):
                e.update(state="open", entry=float(o.get("avg") or e["entry"]), qty=int(o.get("filled") or e["qty"]), filled=today)
                log("filled", symbol=sym, price=e["entry"], qty=e["qty"]); _protect(sym, e); changed = True
            elif stat in ("rejected", "cancelled"):
                log("not_filled", symbol=sym, status=stat, text=o.get("text")); J.pop(sym); changed = True
                e2 = dict(e, state=stat, text=o.get("text"), ended=today); J.setdefault("_done", {})[f"{sym}:{today}"] = e2
            else:
                e["order_status"] = o.get("status")
        elif st == "pending" and e.get("gtt_buy_id") and held.get(sym, 0) > 0:
            e.update(state="open", qty=int(held[sym]), filled=today); log("filled", symbol=sym, gtt=True, qty=e["qty"])
            alert("filled", sym, f"Your GTT buy filled: {e['qty']} shares. Protective stop going on Angel now.", key=f"filled:{sym}:{today}")
            _protect(sym, e); changed = True
            if e.get("kind") == "MY_GTT":
                mp = mypicks(); mp.pop(sym, None); _save_mypicks(mp)                      # done: the pick becomes an open trade
        elif st == "pending" and not o and e.get("since", today) < today and held.get(sym, 0) > 0:
            e.update(state="open", filled=today); _protect(sym, e); changed = True      # filled yesterday; book rolled over
        elif st == "open" and held.get(sym, 0) > 0 and not e.get("gtt_id") and e.get("gtt_tries", 0) < 4 \
                and time.time() - e.get("gtt_last", 0) > 600:
            _protect(sym, e); changed = True                                          # retry a failed protective stop
        elif st == "exiting" and o and stat == "complete":
            px = float(o.get("avg") or e.get("exit_px") or 0); record_exit(sym, px); log("sold", symbol=sym, price=px)
            alert("sold", sym, f"Sold {e.get('qty')} at ₹{px:,.2f}.", key=f"sold:{sym}:{today}")
            J.pop(sym); J.setdefault("_done", {})[f"{sym}:{today}"] = dict(e, state="sold", exit=px, ended=today); changed = True
        elif st == "open" and held.get(sym, 0) <= 0 and (e.get("gtt_id") or e.get("filled", today) < today):
            px = float(e.get("gtt_trigger") or 0) * (1 - GTT_LIMIT_GAP / 2) or e["entry"]
            hit_tgt = False
            if e.get("oco") and e.get("target") and e.get("gtt_trigger"):      # which leg of the stop + target GTT filled?
                try:
                    lt = broker.ltp(sym); hit_tgt = bool(lt) and lt >= (e["target"] + e["gtt_trigger"]) / 2
                except Exception:  # noqa: BLE001
                    pass
                if hit_tgt:
                    px = e["target"] * 0.9975
            record_exit(sym, px); log("gone", symbol=sym, assumed_px=px, target=hit_tgt)
            if hit_tgt:
                alert("sold", sym, f"Target hit: {e.get('qty')} shares sold near ₹{e['target']:,.2f} (your stop + target GTT).", key=f"stop:{sym}:{today}")
            else:
                alert("stop", sym, f"Stop hit or sold outside the app: {e.get('qty')} shares gone from Angel"
                      + (f" (stop ₹{e['gtt_trigger']:,.2f})" if e.get("gtt_trigger") else "") + ".", key=f"stop:{sym}:{today}")
            J.pop(sym); J.setdefault("_done", {})[f"{sym}:{today}"] = dict(e, state="stopped or sold outside the app", exit=px, ended=today); changed = True
    changed = backfill_targets(J, acc) or changed
    changed = gtt_buy_upkeep(J, acc) or changed
    if changed:
        d = J.get("_done") or {}
        if len(d) > 200:
            J["_done"] = dict(list(d.items())[-200:])
        save_journal(J)
    return J


def retry_protect():
    """place any missing protective stop now (open trades still held, no GTT yet)."""
    J = journal(); acc = broker.account(); held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    held = held_map(acc, held)
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


def _weekly_sma30(c, last=False):
    """c: [(date, o, h, l, close)] completed daily candles -> 30-week SMA of completed weekly (Friday) closes, or None.
    last=True: (sma, last completed weekly close)."""
    from datetime import date as _d, timedelta as _td
    wk = {}
    for d, *_x, cl in c:
        dd = _d.fromisoformat(d); end = dd + _td(days=(4 - dd.weekday()) % 7)
        wk[end] = cl                                     # last close of that week
    today = ist_now().date()
    ends = sorted(k for k in wk if k < today or (k == today and ist_now().hour >= 16))
    if len(ends) < 30:
        return (None, None) if last else None
    sma = sum(wk[k] for k in ends[-30:]) / 30
    return (sma, wk[ends[-1]]) if last else sma


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
                alert("raised", sym, f"Stop raised to ₹{guard:,.2f}" + (f" from ₹{cur:,.2f}" if cur else "") + ".", key=f"raised:{sym}:{today}")
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


# ------------------------------------------------------------------ adopt holdings (9 Nov 2026)
# Holdings bought outside the app can be handed to Momentum or Trend 9/21 - ONLY when you confirm each one ("ADOPT <SYM>").
# The app suggests a system from the stock's own chart; you decide. Adopted = journal entry (system, your avg price, qty)
# -> protective GTT (live), the daily stop raise, and the system's sell signal (weekly close < 30-wk SMA, or EMA 9 < EMA 21).
# "RELEASE <SYM>" hands it back: GTT cancelled, the shares stay in your account untouched.
PIE_ETFS = ("NIFTYBEES", "MID150BEES", "GOLDBEES", "MON100", "LIQUIDBEES", "LIQUIDCASE", "JUNIORBEES", "BANKBEES", "MAFANG")
_ADC = {}


def is_etf(sym):
    """ETFs (NIFTYBEES, ITBEES, MON100, ...ETF, ...IETF) are left out of the stock systems."""
    return sym in PIE_ETFS or sym.endswith("BEES") or sym.endswith("ETF") or sym in ("MON100", "MAFANG", "MAHKTECH", "HNGSNGBEES")


def _ema(c, n):
    if len(c) < n * 3:
        return None
    a = 2 / (n + 1); e = c[0][4]
    for x in c[1:]:
        e = a * x[4] + (1 - a) * e
    return e


def chart_read(sym):
    """30-week SMA, EMA 9/21 and the last completed close, from Angel daily candles (cached for the IST day)."""
    k = (sym, ist_now().date().isoformat())
    if k not in _ADC:
        c = broker.daily_candles(sym); sma, wkc = _weekly_sma30(c, last=True)
        _ADC[k] = dict(close=round(c[-1][4], 2) if c else None, sma30=sma, week_close=wkc, ema9=_ema(c, 9), ema21=_ema(c, 21), n=len(c))
    return _ADC[k]


_ATHS = {}


def ath_scan_row(sym):
    """The evening ATH scan's latest row for this stock (base length decides the system), cached for the IST day."""
    k = ist_now().date().isoformat()
    if _ATHS.get("day") != k:
        try:
            d = requests.get(PLAN_URL.rsplit("/", 1)[0] + "/ath.json", timeout=30).json(); rows = {}
            for x in d.get("tracked") or []:
                if x["symbol"] not in rows or str(x.get("date")) > str(rows[x["symbol"]].get("date")):
                    rows[x["symbol"]] = x
            _ATHS.update(day=k, rows=rows)
        except Exception as ex:  # noqa: BLE001
            log("ath_scan_error", error=str(ex)[:160]); return None
    return _ATHS.get("rows", {}).get(sym)


def adopt_suggest(sym):
    r = chart_read(sym); cl, sma, e9, e21 = r["close"], r["sma30"], r["ema9"], r["ema21"]
    if not cl or not sma:
        return dict(suggest=None, why="not enough price history", **r)
    a = ath_scan_row(sym)           # 11 Nov 2026: a scanned breakout's base length picks the system, as the backtests did
    if a and a.get("status") == "open" and (a.get("base_months") or 0) >= 24 and cl > sma:
        return dict(suggest="Monthly ATH", stop=round(sma, 2), protect=round(sma * (1 - ATH_NET_PCT), 2),
                    why=f"Momentum breakout ({a.get('base_months')}-month base): held until a weekly close below the 30-week SMA {sma:,.2f}", **r)
    if a and 12 <= (a.get("base_months") or 0) < 24 and a.get("tf_status") == "open" and e9 and e21 and e9 > e21:
        return dict(suggest="Trend 9/21", stop=round(e21, 2), protect=round(e21 * (1 - ATH_NET_PCT), 2),
                    why=f"Trend 9/21 breakout ({a.get('base_months')}-month base): held until EMA 9 closes below EMA 21 ({e21:,.2f})", **r)
    if cl > sma:
        return dict(suggest="Monthly ATH", stop=round(sma, 2), protect=round(sma * (1 - ATH_NET_PCT), 2),
                    why=f"above its 30-week SMA {sma:,.2f}: Momentum holds it until a weekly close below", **r)
    if e9 and e21 and e9 > e21:
        return dict(suggest="Trend 9/21", stop=round(e21, 2), protect=round(e21 * (1 - ATH_NET_PCT), 2),
                    why=f"below its 30-week SMA but EMA 9 is above EMA 21 ({e21:,.2f}): Trend 9/21 holds it until EMA 9 drops under",
                    **r)
    return dict(suggest=None, why="below its 30-week SMA and EMA 9 is under EMA 21: neither system would hold it now", **r)


@app.get("/api/adopt")
def adopt_list(_=Depends(auth)):
    J = journal(); acc = account_cached(0); out = []
    for h in acc["holdings"]:
        sym = h["symbol"]
        if h["qty"] <= 0 or is_etf(sym) or (sym in J and J[sym].get("state") in ("open", "pending", "exiting")):
            continue
        row = dict(symbol=sym, qty=h["qty"], avg=h.get("avg"), ltp=h.get("ltp"))
        try:
            row.update(adopt_suggest(sym))
        except Exception as ex:  # noqa: BLE001
            row.update(suggest=None, why=f"couldn't read the chart: {angel_msg(ex)}")
        out.append(row)
    adopted = [dict(symbol=k, system=e.get("system"), qty=e.get("qty"), since=e.get("since")) for k, e in J.items()
               if not k.startswith("_") and e.get("adopted") and e.get("state") == "open"]
    return dict(mode="LIVE" if is_live() else "DRY RUN", holdings=out, adopted=adopted, net_pct=ATH_NET_PCT * 100)


class Adopt(BaseModel):
    symbol: str
    system: str
    confirm: str


@app.post("/api/adopt")
def adopt(body: Adopt, _=Depends(auth)):
    sym = body.symbol.upper().strip()
    if body.system not in ("Monthly ATH", "Trend 9/21"):
        raise HTTPException(400, "system must be Momentum (Monthly ATH) or Trend 9/21")
    if body.confirm.strip().upper() != f"ADOPT {sym}":
        raise HTTPException(400, f'confirm must be "ADOPT {sym}"')
    if is_etf(sym):
        raise HTTPException(400, "ETFs are not managed by the stock systems")
    J = journal()
    if sym in J and J[sym].get("state") in ("open", "pending", "exiting"):
        raise HTTPException(409, "already managed by the app")
    acc = account_cached(0); h = next((x for x in acc["holdings"] if x["symbol"] == sym and x["qty"] > 0), None)
    if not h:
        raise HTTPException(404, "not in your Angel holdings")
    r = chart_read(sym)
    lvl = r["sma30"] if body.system == "Monthly ATH" else r["ema21"]
    if not lvl:
        raise HTTPException(400, "not enough price history to set the system level")
    e = dict(since=ist_now().date().isoformat(), system=body.system, kind="ADOPT", stop=round(lvl, 2), entry=float(h.get("avg") or h.get("ltp") or 0),
             qty=int(h["qty"]), state="open", adopted=True, adopt_px=float(h.get("ltp") or 0) or None)
    prot = round(protect_level("ADOPT", lvl), 2)
    if not is_live():
        log("adopt_dry", symbol=sym, system=body.system, stop=e["stop"], protect=prot)
        return dict(ok=True, mode="DRY RUN", adopted=False, entry=e, protect=prot,
                    msg="Dry run: nothing changed. In Live mode this hands it to the system and places the protective stop on Angel.")
    J[sym] = e; _protect(sym, e); save_journal(J); log("adopt", symbol=sym, system=body.system, stop=e["stop"], gtt=e.get("gtt_id"))
    return dict(ok=True, mode="LIVE", adopted=True, entry=e, protect=e.get("gtt_trigger"), gtt_error=e.get("gtt_error"))


class Release(BaseModel):
    symbol: str
    confirm: str


@app.post("/api/adopt/release")
def adopt_release(body: Release, _=Depends(auth)):
    sym = body.symbol.upper().strip()
    if body.confirm.strip().upper() != f"RELEASE {sym}":
        raise HTTPException(400, f'confirm must be "RELEASE {sym}"')
    J = journal(); e = J.get(sym)
    if not e or not e.get("adopted"):
        raise HTTPException(404, "not an adopted holding")
    if e.get("gtt_id"):
        try:
            broker.gtt_cancel(e["gtt_id"], sym); log("gtt_cancel", symbol=sym, gtt_id=e["gtt_id"])
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(502, f"couldn't cancel the stop on Angel, nothing changed: {angel_msg(ex)}")
    J.pop(sym); save_journal(J); log("adopt_release", symbol=sym)
    return dict(ok=True, released=sym)


def adopted_exits(J, held):
    """sell signals for adopted holdings (the nightly plan only knows the scan's own stocks)."""
    out = []
    for sym, e in J.items():
        if sym.startswith("_") or not e.get("adopted") or e.get("state") != "open" or held.get(sym, 0) <= 0:
            continue
        try:
            r = chart_read(sym)
        except Exception:  # noqa: BLE001
            continue
        cl = r["close"]
        if e["system"] == "Monthly ATH" and r["sma30"] and r.get("week_close") and r["week_close"] < r["sma30"]:
            out.append(dict(id=f"EXIT-ADOPT-{sym}", symbol=sym, system=e["system"], side="SELL", order="LIMIT", when="next open", ref=cl,
                            why=f"week closed at {r['week_close']:,.2f}, below the 30-week SMA {r['sma30']:,.2f}"))
        if e["system"] == "Trend 9/21" and r["ema9"] and r["ema21"] and r["ema9"] < r["ema21"]:
            out.append(dict(id=f"EXIT-ADOPT-{sym}", symbol=sym, system=e["system"], side="SELL", order="LIMIT", when="next open", ref=cl,
                            why="daily close with EMA 9 below EMA 21"))
    return out


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
                        stop=e.get("stop"), ltp=px, R=R, since=e.get("since"), gtt_trigger=e.get("gtt_trigger"), gtt_id=e.get("gtt_id"), target=e.get("target"), oco=bool(e.get("oco")), oco_error=e.get("oco_error"), kind=e.get("kind"),
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
        q, en = e["qty"], e.get("adopt_px") or e["entry"]; px = ltp.get(sym) or en
        o["n"] += 1; o["cost"] += q * en; o["value"] += q * px; add(e.get("system"), q * en, q * (px - en))
        first = min(first or e.get("since") or "9", e.get("since") or "9")
    for k, e in (J.get("_done") or {}).items():
        if not (e.get("exit") and e.get("entry") and e.get("qty")):
            continue          # rejected or cancelled orders never filled
        q, en = e["qty"], e.get("adopt_px") or e["entry"]; pnl = q * (e["exit"] - en)
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


ANGEL_WHY = {"AB4036": "this stock is on the exchange's surveillance (cautionary) list: every order needs your own consent tap in "
                       "Angel's app or web, which no API can give. Place it in the Angel app (the app shows the exact order); once it "
                       "fills, Sync adds it to your trades and puts the protective stop on.",
             "AB1007": "Angel login session problem - try again in a minute.",
             "AB4008": "price outside the allowed band for today."}


SURV_DAYS = 30


def surv_path():
    return os.path.join(DATA, "surveillance.json")


def surv_load():
    """12 Nov 2026: stocks Angel refused with AB4036 (exchange surveillance list: each order needs your consent in
    Angel's own app/web, which an API cannot give). Remembered for SURV_DAYS so the app marks them 'place in Angel'
    up front instead of failing on Send; a fresh successful API order clears the mark."""
    try:
        D = json.load(open(surv_path()))
    except Exception:  # noqa: BLE001
        return {}
    cut = (ist_now().date() - timedelta(days=SURV_DAYS)).isoformat()
    return {k: v for k, v in D.items() if v >= cut}


def surv_mark(sym, on=True):
    D = surv_load()
    if on:
        D[sym] = ist_now().date().isoformat()
    else:
        D.pop(sym, None)
    try:
        json.dump(D, open(surv_path(), "w"))
    except Exception:  # noqa: BLE001
        pass


def is_surv_err(e):
    return "AB4036" in str(e) or "cautionary" in str(e).lower()


def angel_msg(e):
    m = str(e); code = re.search(r"\[(AB\d+)\]", m)
    return ANGEL_WHY.get(code.group(1), m) if code else m


def equity_log(value, pledge=0.0):
    """Account value (cash + holdings at today's price) once per day, for the app's equity curve; today's entry is overwritten.
    11 Nov 2026: cash stopped counting the margin from pledged shares; days logged before that are lowered once by the
    pledge margin so the curve and 'today' don't show a drop that never happened."""
    p = os.path.join(DATA, "equity.json")
    try:
        E = json.load(open(p))
    except Exception:  # noqa: BLE001
        E = {}
    d = ist_now().date().isoformat()
    if E.get("_basis") != "no-pledge":
        E = {k: (round(v - pledge, 2) if k < d and pledge else v) for k, v in E.items() if not k.startswith("_")}
        E["_basis"] = "no-pledge"; value = value or 0
        try:
            json.dump(E, open(p, "w"))
        except Exception:  # noqa: BLE001
            pass
    if value and E.get(d) != value:
        E[d] = value; E = dict(sorted(E.items())[-800:]); E["_basis"] = "no-pledge"
        try:
            json.dump(E, open(p, "w"))
        except Exception:  # noqa: BLE001
            pass
    return sorted((k, v) for k, v in E.items() if not k.startswith("_"))


def sized(acc=None):
    P = plan(); acc = acc or account_cached()
    J = sync(acc)
    G = guard(acc)
    held = {h["symbol"]: h["qty"] for h in acc["holdings"] if h["qty"] > 0}
    held = held_map(acc, held)
    sys_open = [s for s in J if not s.startswith("_") and (held.get(s, 0) > 0 or J[s].get("state") == "pending")]
    acct = CAPITAL or acc["net"]
    try:
        app_cap = float(_picks_cfg().get("capital") or 0)
    except Exception:  # noqa: BLE001
        app_cap = 0.0
    cap = min(app_cap, acct) if app_cap > 0 and acct else acct      # capital set in the app, never above the account value
    N = picks(); RK = risk_now(); SR = swing_risk()
    sw_open = [s for s in sys_open if J[s].get("system") in ("9/21 trend", "Trend 9/21", "Breakout retest", "Bottom pattern", "VCP", "My pick")]
    AL = alloc(); ltp = {h["symbol"]: h.get("ltp") for h in acc["holdings"]}
    expo = {k: 0.0 for k in AL}
    for s_ in sys_open:
        b = SYS_BUCKET.get(J[s_].get("system"), "mom"); e_ = J[s_]
        expo[b] = expo.get(b, 0.0) + (held.get(s_, 0) or e_.get("qty") or 0) * float(ltp.get(s_) or e_.get("entry") or 0)
    room = {k: AL[k] / 100 * cap - expo.get(k, 0.0) for k in AL}
    ath_open = [s for s in sys_open if s not in sw_open]
    slots = max(0, N - len(ath_open)); sw_slots = max(0, SWING_MAX - len(sw_open))
    cash = acc["cash"]
    rows = []; SV = surv_load()
    for r in plan_rows(P):
        E = r.get("trigger") or r["price"]; stop = r["stop"]
        q = 0; why = ""
        if r["symbol"] in held:
            why = "already held"
        elif r["symbol"] in J and J[r["symbol"]].get("state") == "pending":
            why = "order sent - waiting for the fill"
        elif stop and E > stop:
            q = math.floor(min((SR if r["tier"] == "swing" else RK) * cap / (E - stop), MAX_POS_PCT * cap / E, MAX_ORDER_VALUE / E))
        rows.append(dict(r, qty=max(0, q), value=round(max(0, q) * E, 0), risk_amt=round(max(0, q) * (E - stop), 0) if stop else None,
                         pct_cap=round(max(0, q) * E / cap * 100, 1) if cap else None, skip=why, surv=r["symbol"] in SV))
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
        if AL.get(bk, 0) <= 0:
            r["outside"] = True; r["note"] = (r.get("note") or "") + " · outside your split (0% in Systems & allocation): your call"
            if r["value"] > cash:
                q = math.floor(cash / E0)
                if q <= 0 or q < 0.25 * r["qty"]:
                    r["skip"] = "not enough cash"; continue
                r["qty"], r["value"] = q, round(q * E0, 0); r["risk_amt"] = round(q * (E0 - r["stop"]), 0)
            continue
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
    have = {x["symbol"] for x in ex}
    ex += [dict(x, qty=held.get(x["symbol"], 0)) for x in adopted_exits(J, held) if x["symbol"] not in have]
    if G["status"] == "paused":
        for r in rows:
            if not r["skip"]:
                r["skip"] = "paused: losing streak (guard)"
    trades, recent = trades_view(J, acc)
    real = round(acc["cash"] + (acc.get("holdings_value") or 0) + (acc.get("positions_value") or 0), 2)
    brk = dict(cash=round(acc["cash"], 2), holdings=round(acc.get("holdings_value") or 0, 2), todays_buys=round(acc.get("positions_value") or 0, 2),
               rms=acc.get("rms"))                       # 11 Nov 2026: the parts of the account value, shown under the total in Live
    return dict(real_value=real, value_parts=brk, equity=equity_log(real, ((acc.get("rms") or {}).get("collateral") or 0)), holdings=[dict(symbol=h["symbol"], qty=h["qty"], ltp=h.get("ltp"), avg=h.get("avg"),
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
        if row["kind"] == "MY_GTT":
            if market_open(t):
                ltp = broker.ltp(row["symbol"])
                if ltp and ltp <= row["stop"]:
                    raise HTTPException(400, f"not sent: the price {ltp:.2f} is at or below your stop {row['stop']:.2f}")
            p = dict(gtt="BUY", symbol=row["symbol"], qty=body.qty, trigger=row["trigger"], limit=row["price"])
        elif row["kind"] in STOP_KINDS and (lambda l: not l or live_check(row, l)[0] == "wait")(broker.ltp(row["symbol"])):
            # 13 Nov 2026: a buy-stop still below its trigger goes on Angel as a GTT buy (sits there until the price reaches the
            # trigger, any day this month) instead of a day SL order that lapsed every evening. The server cancels it if the
            # setup ends first (gtt_buy_upkeep). Above the trigger -> the branches below (limit now / missed).
            ltp = broker.ltp(row["symbol"])
            if ltp and row.get("stop") and ltp <= row["stop"]:
                raise HTTPException(400, f"not sent: the price {ltp:.2f} is at or below the plan stop {row['stop']:.2f}")
            p = dict(gtt="BUY", symbol=row["symbol"], qty=body.qty, trigger=row["trigger"], limit=row["price"])
        elif market_open(t):
            ltp = broker.ltp(row["symbol"])
            st, lim, why = live_check(row, ltp)
            if st in ("broken", "missed", "ran"):
                raise HTTPException(400, f"not sent: {why}")
            p = broker.params(row["symbol"], side, body.qty, lim or row["price"])   # 9/21, breakouts, or a buy-stop already triggered: LIMIT, capped
        else:
            if row["kind"] in STOP_KINDS:
                raise HTTPException(400, "this buy-stop is already above its trigger - send it in market hours (it buys as a capped limit)")
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
    if p.get("gtt") == "BUY":
        try:
            gid, gp = broker.gtt_buy(sym, body.qty, row["trigger"], row["price"])
        except Exception as e:  # noqa: BLE001
            log("order_error", error=str(e), **rec); _acc["d"] = None
            if is_surv_err(e):
                surv_mark(sym)
            raise HTTPException(502, f"Angel rejected the GTT for {sym}: {angel_msg(e)}")
        log("gtt_buy", gtt_id=gid, **rec)
        J = journal()
        if row["kind"] == "MY_GTT":
            mp0 = mypicks().get(sym) or {}; R0 = float(row["trigger"]) - float(row.get("stop") or 0)
            J[sym] = dict(since=t.date().isoformat(), system="My pick", kind="MY_GTT", stop=row.get("stop"), entry=float(row["trigger"]),
                          qty=body.qty, order_id=None, gtt_buy_id=gid, state="pending",
                          target=round(float(mp0.get("target") or (float(row["trigger"]) + MY_TARGET_R * R0)), 2))
            msg = "GTT buy placed on Angel (good for a year). When it fills, the protective GTT stop goes in at your stop."
        else:
            J[sym] = dict(since=t.date().isoformat(), system=row.get("system"), kind=row.get("kind"), stop=row.get("stop"), entry=float(row["trigger"]),
                          qty=body.qty, order_id=None, gtt_buy_id=gid, state="pending", gtt_month=t.strftime("%Y-%m"), plan_id=row.get("id"))
            tg = auto_target(J[sym], row)
            if tg:
                J[sym]["target"] = tg
            msg = (f"GTT buy placed on Angel at the trigger {float(row['trigger']):.2f}: it waits there until the price reaches it. "
                   "The server cancels it if the setup ends first (month-end, off the plan, or below the stop). After the fill the protective stop goes on.")
        save_journal(J)
        return dict(ok=True, mode="LIVE", sent=True, gtt_id=gid, order=gp, protect=prot, msg=msg)
    try:
        oid = broker.place(p)
    except Exception as e:  # noqa: BLE001
        log("order_error", error=str(e), **rec)
        _acc["d"] = None
        if is_surv_err(e):
            surv_mark(sym)
        raise HTTPException(502, f"Angel rejected {sym}: {angel_msg(e)}")
    _acc["d"] = None
    if sym in surv_load():
        surv_mark(sym, False)
    log("order", order_id=oid, **rec)
    J = journal()
    if side == "BUY":
        J[sym] = dict(since=t.date().isoformat(), system=row.get("system"), kind=row.get("kind"), stop=row.get("stop"),
                      entry=float(p["price"]), qty=body.qty, order_id=str(oid), state="pending")
        if row.get("kind") == "PATTERN" and row.get("target"):
            J[sym]["plan_target"] = float(row["target"])
        tg = auto_target(J[sym], row)
        if tg:
            J[sym]["target"] = tg
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


def plan_rows(P):
    """every buy the app can size: Momentum top/more, swing systems, and bottom-pattern breakouts (watch-only system: sized
    so you can decide, protective stop at the pattern stop, no tested exit)."""
    pat = [dict(x, id=f"PAT-{x['symbol']}-{x.get('signal_date', '')}", system="Bottom pattern", bucket="pt", kind="PATTERN", side="BUY", order="LIMIT",
                when="next open", price=round(float(x["close"]), 2), ref=float(x["close"]), stop=float(x["stop"]),
                exit_rule="pattern stop only (no tested exit; watch-only system)",
                note=f"{x.get('typ', '')} broke its neckline {float(x.get('neck') or 0):,.2f} on {x.get('signal_date', '')}",
                risk_pct=round((1 - float(x["stop"]) / float(x["close"])) * 100, 1))
           for x in P.get("pattern_watch") or [] if x.get("close") and x.get("stop") and x["stop"] < x["close"]]
    mine = [dict(id=f"MY-{x['symbol']}", symbol=x["symbol"], name=x.get("name", ""), system="My pick", bucket="my", kind="MY_GTT", side="BUY",
                 order="GTT", when="GTT buy, good for 1 year", trigger=float(x["trigger"]), price=round(float(x["trigger"]) * (1 + MY_LIMIT_GAP), 2),
                 ref=float(x["trigger"]), stop=float(x["stop"]), exit_rule="protective GTT stop at your stop after the fill; the exit is your call",
                 note=(x.get("note") or "") + (f" · pushed from {x['src']}" if x.get("src") else ""),
                 risk_pct=round((1 - float(x["stop"]) / float(x["trigger"])) * 100, 1)) for x in mypicks().values()]
    return [dict(x, tier="top") for x in P.get("top") or []] + [dict(x, tier="more") for x in P.get("more") or []] + \
        [dict(x, tier="swing") for x in (P.get("swing") or []) + pat + mine]


# ------------------------------------------------------------------ your own picks -> Live -> Angel GTT buy (10 Nov 2026)
# Any stock panel in the app can push a stock here with a buy trigger and a stop. Live sizes it (outside the split, swing risk)
# and Send places an Angel GTT BUY (trigger -> limit MY_LIMIT_GAP above), good for a year. When it fills the server places the
# usual protective GTT stop at your stop. Removing the pick cancels a GTT that has not triggered yet.
MY_LIMIT_GAP = float(ENV.get("MY_LIMIT_GAP_PCT", "0.5")) / 100
MY_MAX = 30


def mypicks() -> dict:
    try:
        return json.load(open(os.path.join(DATA, "mypicks.json")))
    except Exception:  # noqa: BLE001
        return {}


def _save_mypicks(d):
    json.dump(d, open(os.path.join(DATA, "mypicks.json"), "w"))


class MyPick(BaseModel):
    symbol: str
    trigger: float
    stop: float
    target: float | None = None
    note: str = ""
    src: str = ""
    name: str = ""


@app.get("/api/mypicks")
def get_mypicks(_=Depends(auth)):
    return dict(rows=list(mypicks().values()))


class Target(BaseModel):
    symbol: str
    target: float = 0          # 0 = remove the target (stop only)
    confirm: str = ""


@app.post("/api/target")
def set_target(body: Target, _=Depends(auth)):
    """Stop + target (OCO) for an open trade outside the tested systems (11 Nov 2026). Momentum / Trend keep stop-only:
    their tests sell on the system's line, and a fixed target cut returns. The old GTT is cancelled and a new one placed."""
    sym = body.symbol.strip().upper(); J = journal(); e = J.get(sym)
    if not e or e.get("state") != "open":
        raise HTTPException(400, f"{sym} is not an open trade in the app")
    if e.get("system") in TRAIL_SYS:
        raise HTTPException(400, f"{sym} is in {e.get('system')}: its tested exit is the system line, so no fixed target")
    if body.confirm.strip().upper() != f"TARGET {sym}":
        raise HTTPException(400, f'confirm must be "TARGET {sym}"')
    trig = protect_level(e.get("kind"), e.get("stop")) or e.get("gtt_trigger")
    if body.target and not body.target > (e.get("entry") or 0) * 1.005:
        raise HTTPException(400, "target must be above your buy price")
    e["target"] = round(body.target, 2) if body.target else None
    if not is_live():
        save_journal(J); return dict(ok=True, mode="DRY RUN", msg=f"Dry run: {sym} would get stop {trig:.2f}" + (f" + target {body.target:.2f}" if body.target else " only"))
    if e.get("gtt_id"):
        try:
            broker.gtt_cancel(e["gtt_id"], sym); log("gtt_cancel", symbol=sym, gtt_id=e["gtt_id"])
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(502, f"couldn't cancel the old GTT on Angel: {angel_msg(ex)}")
        e.pop("gtt_id", None)
    e["gtt_tries"] = 0; _protect(sym, e); save_journal(J)
    return dict(ok=bool(e.get("gtt_id")), mode="LIVE", oco=bool(e.get("oco")), gtt_id=e.get("gtt_id"), error=e.get("oco_error") or e.get("gtt_error"),
                msg=(f"{sym}: stop {trig:.2f} + target {body.target:.2f} on Angel (one GTT, whichever hits first)" if e.get("oco")
                     else f"{sym}: stop {trig:.2f} on Angel" + (f" (target refused: {e.get('oco_error')})" if e.get("oco_error") else "")))


@app.post("/api/mypicks")
def add_mypick(body: MyPick, _=Depends(auth)):
    sym = body.symbol.strip().upper().replace(".NS", "")
    if not sym or not body.trigger > 0 or not 0 < body.stop < body.trigger:
        raise HTTPException(400, "stop must be below the buy trigger")
    if body.stop < body.trigger * 0.6:
        raise HTTPException(400, "stop more than 40% below the trigger - check the numbers")
    d = mypicks()
    if sym not in d and len(d) >= MY_MAX:
        raise HTTPException(400, f"at most {MY_MAX} picks - remove some first")
    if body.target is not None and not body.target > body.trigger:
        raise HTTPException(400, "target must be above the buy trigger")
    d[sym] = dict(symbol=sym, trigger=round(body.trigger, 2), stop=round(body.stop, 2), note=body.note[:120], src=body.src[:40],
                  name=body.name[:60], added=ist_now().date().isoformat(),
                  target=round(body.target if body.target else body.trigger + MY_TARGET_R * (body.trigger - body.stop), 2))
    _save_mypicks(d); log("mypick_add", **d[sym])
    return dict(ok=True, rows=list(d.values()))


@app.delete("/api/mypicks/{sym}")
def del_mypick(sym: str, _=Depends(auth)):
    sym = sym.upper(); d = mypicks(); J = journal(); e = J.get(sym) or {}
    msg = "removed"
    if e.get("kind") == "MY_GTT" and e.get("state") == "pending" and e.get("gtt_buy_id"):
        if is_live():
            try:
                broker.gtt_cancel(e["gtt_buy_id"], sym); msg = "removed and its GTT buy cancelled on Angel"
            except Exception as ex:  # noqa: BLE001
                raise HTTPException(502, f"couldn't cancel the GTT buy on Angel: {angel_msg(ex)}")
        J.pop(sym); save_journal(J)
    d.pop(sym, None); _save_mypicks(d); log("mypick_del", symbol=sym)
    return dict(ok=True, msg=msg, rows=list(d.values()))


def live_check(r, ltp):
    """In market hours, what a plan buy may do at this live price (matches the backtest: buy at the trigger / next open).
    -> (state, limit_price or None, text). states: wait (buy-stop below trigger), triggered, ok, missed, ran, broken."""
    if not ltp:
        return "ok", None, ""
    if r.get("stop") and ltp <= r["stop"]:
        return "broken", None, f"below the plan stop ({r['stop']:.2f}) - the setup is invalid; can't send"
    if r["kind"] in STOP_KINDS:
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


# ------------------------------------------------------------------ live prices for the US / ASX shortlists (10 Nov 2026)
# Yahoo's public chart endpoint (no key; Nasdaq-listed US prices real time, others ~15 min delayed), only for the stocks the
# plan shortlists (picks, near-trigger, sells), cached ~45 s. Uses requests (already installed), no new package.
MKT_PLAN = {"US": "us/trade_plan.json", "ASX": "asx/trade_plan.json"}
MKT_TZ = {"US": ("America/New_York", (9, 30), (16, 0)), "ASX": ("Australia/Sydney", (10, 0), (16, 0))}
_mplan, _mq = {}, {}


def mkt_plan(mk):
    c = _mplan.get(mk)
    if c and time.time() - c[0] < 300:
        return c[1]
    if ENV.get("PLAN_FILE"):
        d = json.load(open(os.path.join(os.path.dirname(ENV["PLAN_FILE"]), MKT_PLAN[mk])))
    else:
        r = requests.get(PLAN_URL.rsplit("/", 1)[0] + "/" + MKT_PLAN[mk], timeout=30); r.raise_for_status(); d = r.json()
    _mplan[mk] = (time.time(), d)
    return d


def mkt_open(mk, t=None):
    from zoneinfo import ZoneInfo
    tz, a, b = MKT_TZ[mk]; t = (t or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz))
    return t.weekday() < 5 and a <= (t.hour, t.minute) < b


def yq(sym, mk):
    y = sym if mk == "RAW" else sym.replace(".", "-") + (".AX" if mk == "ASX" else "")
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{y}", params=dict(interval="1d", range="1d"),
                     headers={"User-Agent": "Mozilla/5.0 (Trend Desk personal app)"}, timeout=10)
    r.raise_for_status(); res = r.json()["chart"]["result"][0]; m = res["meta"]
    op = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("open") or [None]
    return dict(ltp=m.get("regularMarketPrice"), prev=m.get("chartPreviousClose") or m.get("previousClose"), high=m.get("regularMarketDayHigh"),
                low=m.get("regularMarketDayLow"), open=op[-1] if op else None, t=m.get("regularMarketTime"))


INDICES = [("Nifty 50", "^NSEI", "IN"), ("Bank Nifty", "^NSEBANK", "IN"), ("Sensex", "^BSESN", "IN"), ("S&P 500", "^GSPC", "US"),
           ("Nasdaq 100", "^NDX", "US"), ("Dow", "^DJI", "US"), ("ASX 200", "^AXJO", "AU"), ("Nikkei", "^N225", "W"),
           ("Gold", "GC=F", "W"), ("Brent", "BZ=F", "W"), ("USD/INR", "INR=X", "W")]


@app.get("/api/indices")
def indices(_=Depends(auth)):
    """live index levels for the Markets tab (Yahoo chart endpoint, cached ~30 s)."""
    c = _mq.get("_idx")
    if c and time.time() - c[0] < 30:
        return c[1]
    from concurrent.futures import ThreadPoolExecutor
    out, errs = {}, []
    def one(it):
        name, y, grp = it
        try:
            q = yq(y, "RAW")
            if q.get("ltp"):
                out[name] = dict(q, grp=grp, src="yahoo")
        except Exception as ex:  # noqa: BLE001
            errs.append(f"{name}: {str(ex)[:80]}")
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, INDICES))
    try:                                   # India from Angel when Yahoo didn't answer (Yahoo can refuse cloud servers)
        for n, q in broker.index_quotes().items():
            if n not in out:
                out[n] = dict(q, grp="IN", src="angel")
    except Exception as ex:  # noqa: BLE001
        errs.append(f"Angel indices: {str(ex)[:80]}")
    if errs:
        log("indices_errors", n=len(errs), first=errs[0])
    res = dict(rows=[dict(name=n, **out[n]) for n, _, _ in INDICES if n in out], at=int(time.time()), errors=errs[:3])
    _mq["_idx"] = (time.time(), res)
    return res


@app.get("/api/quotes_mkt")
def quotes_mkt(mk: str = "US", _=Depends(auth)):
    if mk not in MKT_PLAN:
        raise HTTPException(404, "market must be US or ASX")
    c = _mq.get(mk)
    if c and time.time() - c[0] < 45:
        return c[1]
    P = mkt_plan(mk)
    syms = sorted({r["symbol"] for k in ("top", "more", "swing", "watch", "exits", "pattern_watch") for r in P.get(k) or [] if r.get("symbol")})[:60]
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    def one(sym):
        try:
            q = yq(sym, mk)
            if q.get("ltp"):
                out[sym] = q
        except Exception:  # noqa: BLE001
            pass
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, syms))
    res = dict(mk=mk, market_open=mkt_open(mk), symbols=out, source="Yahoo Finance (Nasdaq real time, others ~15 min delayed)")
    _mq[mk] = (time.time(), res)
    return res


@app.get("/api/quotes")
def quotes(_=Depends(auth)):
    """Live prices for today's plan rows, exits and app trades, plus the limit price a buy sent now would get."""
    P = plan(); t = ist_now()
    rows = plan_rows(P); syms = sorted({r["symbol"] for r in rows} | {e["symbol"] for e in P.get("exits") or []}
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


class SipItem(BaseModel):
    symbol: str
    qty: int


class Sip(BaseModel):
    items: list[SipItem]
    confirm: str


SIP_ETFS = ("NIFTYBEES", "MID150BEES", "GOLDBEES", "MON100", "LIQUIDBEES")
SIP_MAX = float(ENV.get("SIP_MAX", "200000"))        # most one SIP send may spend


@app.post("/api/sip")
def sip(body: Sip, _=Depends(auth)):
    """The Wealth Creation Pie's monthly ETF buys, with ONE typed confirmation ("SIP <n>"). Only the Pie's ETFs, whole units,
    total within SIP_MAX and your cash, each ETF once a day. Kept out of the systems' journal (no stops, no trailing)."""
    items = [i for i in body.items if i.qty > 0]
    if not items:
        raise HTTPException(400, "nothing to buy")
    bad = [i.symbol for i in items if i.symbol not in SIP_ETFS]
    if bad:
        raise HTTPException(400, f"not a Pie ETF: {', '.join(bad)}")
    if len({i.symbol for i in items}) != len(items):
        raise HTTPException(400, "each ETF once")
    if body.confirm.strip().upper() != f"SIP {len(items)}":
        raise HTTPException(400, f'confirm must be "SIP {len(items)}"')
    done = {r.get("symbol") for r in today_log() if r.get("kind") == "sip"}       # real buys only; dry runs can repeat
    again = [i.symbol for i in items if i.symbol in done]
    if again:
        raise HTTPException(409, f"already sent today: {', '.join(again)}")
    t = ist_now(); open_now = market_open(t); amo = amo_window(t) and not open_now
    if not open_now and not amo:
        raise HTTPException(400, "send during market hours or between 15:45 and 08:57 IST (AMO)")
    try:
        Q = broker.quotes([i.symbol for i in items]); acc = account_cached()
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"couldn't read prices or your account: {angel_msg(ex)}")
    out, total = [], 0.0
    for i in items:
        q = Q.get(i.symbol) or {}; px = q.get("ltp") or q.get("prev")
        if not px:
            raise HTTPException(400, f"no price for {i.symbol}")
        lim = px * 1.003                                  # marketable limit, a hair above the last price
        total += i.qty * lim
        out.append(dict(symbol=i.symbol, qty=i.qty, params=broker.params(i.symbol, "BUY", i.qty, lim, amo=amo)))
    if total > min(SIP_MAX, acc["cash"]):
        raise HTTPException(400, f"SIP total ₹{total:,.0f} is above your cash or the SIP limit (₹{SIP_MAX:,.0f})")
    if not is_live():
        for o in out:
            log("sip_dry", symbol=o["symbol"], qty=o["qty"], params=o["params"])
        return dict(ok=True, mode="DRY RUN", sent=False, total=round(total), orders=out,
                    msg="Dry run: these are exactly the orders that would go to Angel. Switch to Live orders to send for real.")
    res = []
    for o in out:
        try:
            oid = broker.place(o["params"]); log("sip", order_id=oid, symbol=o["symbol"], qty=o["qty"], params=o["params"], ist_date=t.date().isoformat())
            res.append(dict(symbol=o["symbol"], qty=o["qty"], ok=True, order_id=oid))
        except Exception as e:  # noqa: BLE001
            log("sip_error", symbol=o["symbol"], qty=o["qty"], error=str(e)[:200])
            res.append(dict(symbol=o["symbol"], qty=o["qty"], ok=False, error=angel_msg(e)))
    _acc["d"] = None
    return dict(ok=any(r["ok"] for r in res), mode="LIVE", sent=True, total=round(total), results=res)


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
TB_DIRS = {"bn": TB_DIR, "nifty": ENV.get("TB_NIFTY_DIR") or os.path.join(DATA, "tb_nifty")}   # Bank Nifty (buy+sell), Nifty (buy only)


def _tbdir(inst):
    if inst not in TB_DIRS:
        raise HTTPException(404, "unknown Top Bottom instrument")
    return TB_DIRS[inst]


def _tbr(name, default, inst="bn"):
    try:
        return json.load(open(os.path.join(_tbdir(inst), "app", name)))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return default


def _tbw(name, obj, inst="bn"):
    d = os.path.join(_tbdir(inst), "app"); os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, name + ".tmp"); json.dump(obj, open(tmp, "w")); os.replace(tmp, os.path.join(d, name))


def tb_live(inst="bn"):
    try:
        return bool(json.load(open(os.path.join(_tbdir(inst), "mode.json"))).get("live"))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/tb")
def tb_state(inst: str = "bn", _=Depends(auth)):
    d = _tbdir(inst); msgs = []
    try:
        with open(os.path.join(d, "app", "messages.jsonl"), encoding="utf-8") as f:
            msgs = [json.loads(x) for x in f.readlines()[-25:]]
    except Exception:  # noqa: BLE001
        pass
    P = _tbr("pending.json", {}, inst); A = _tbr("answers.json", {}, inst)
    return dict(inst=inst, installed=os.path.isdir(d), mode="LIVE" if tb_live(inst) else "DRY RUN", auto=tb_auto(inst), status=_tbr("status.json", {}, inst),
                pending=[dict(key=k, **v) for k, v in P.items()], answers=A, messages=msgs[::-1])


class TBAnswer(BaseModel):
    key: str
    value: bool | str
    confirm: str = ""


@app.post("/api/tb/answer")
def tb_answer(body: TBAnswer, inst: str = "bn", _=Depends(auth)):
    P = _tbr("pending.json", {}, inst)
    if body.key not in P:
        raise HTTPException(404, "that approval is no longer pending")
    if body.value is True and tb_live(inst) and body.confirm.strip().upper() != "YES":
        raise HTTPException(400, 'type YES to approve a live trade')
    A = _tbr("answers.json", {}, inst); A[body.key] = body.value; _tbw("answers.json", A, inst)
    if not P[body.key].get("options"):
        P.pop(body.key); _tbw("pending.json", P, inst)
    log("tb_answer", inst=inst, key=body.key, value=body.value)
    return dict(ok=True)


class TBCmd(BaseModel):
    cmd: str


@app.post("/api/tb/cmd")
def tb_cmd(body: TBCmd, inst: str = "bn", _=Depends(auth)):
    if body.cmd not in ("/status", "/stop", "/flat"):
        raise HTTPException(400, "unknown command")
    C = _tbr("commands.json", [], inst); C.append(body.cmd); _tbw("commands.json", C, inst)
    log("tb_cmd", inst=inst, cmd=body.cmd)
    return dict(ok=True, note="the bot picks this up within a few seconds while it runs (09:00-15:30 IST)")


@app.post("/api/tb/mode")
def tb_mode(body: Mode, request: Request, inst: str = "bn", _=Depends(auth)):
    """same safety as the equity switch: live needs the app password + LIVE; dry run is one tap. Applies from the bot's next start."""
    d = _tbdir(inst)
    if body.live:
        ip = request.client.host if request.client else "?"
        n, t0 = FAILS.get(ip, (0, 0))
        if n >= 5 and time.time() - t0 < 900:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        if body.confirm.strip().upper() != "LIVE":
            raise HTTPException(400, "type LIVE to confirm")
        if not check_pw(body.password):
            FAILS[ip] = (n + 1, time.time()); raise HTTPException(401, "wrong password")
    os.makedirs(d, exist_ok=True)
    json.dump(dict(live=bool(body.live), at=time.time()), open(os.path.join(d, "mode.json"), "w"))
    log("tb_mode", inst=inst, live=body.live)
    return dict(ok=True, mode="LIVE" if body.live else "DRY RUN")


class TBAuto(BaseModel):
    on: bool
    password: str = ""
    confirm: str = ""


def tb_auto(inst="bn"):
    try:
        return bool(json.load(open(os.path.join(_tbdir(inst), "auto.json"))).get("on"))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return False


@app.post("/api/tb/auto")
def tb_auto_set(body: TBAuto, request: Request, inst: str = "bn", _=Depends(auth)):
    """11 Nov 2026: auto-approve Top Bottom's entry / reversal levels (no tap needed). Turning it ON needs the app password +
    typing AUTO; OFF is one tap. The bot's own limits stay: lots, max lots, daily loss cap, entries a day, its stops.
    Orders reach Angel only when the bot is also in Live mode."""
    d = _tbdir(inst)
    if body.on:
        ip = request.client.host if request.client else "?"
        n, t0 = FAILS.get(ip, (0, 0))
        if n >= 5 and time.time() - t0 < 900:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        if body.confirm.strip().upper() != "AUTO":
            raise HTTPException(400, "type AUTO to confirm")
        if not check_pw(body.password):
            FAILS[ip] = (n + 1, time.time()); raise HTTPException(401, "wrong password")
    os.makedirs(d, exist_ok=True)
    json.dump(dict(on=bool(body.on), at=time.time()), open(os.path.join(d, "auto.json"), "w"))
    log("tb_auto", inst=inst, on=body.on)
    return dict(ok=True, auto=bool(body.on))


TB_NAME = {"bn": "Bank Nifty", "nifty": "Nifty"}


def tb_watch():
    """Every pass of the loop: each new Top Bottom approval request -> a phone alert (push) once; with auto-approve on,
    entry / reversal levels (keys BUY:… / SELL:…, yes-no questions) are answered YES at once and you are told."""
    for inst, d in TB_DIRS.items():
        if not os.path.isdir(d):
            continue
        P = _tbr("pending.json", {}, inst)
        if not P:
            continue
        auto = tb_auto(inst); live = tb_live(inst); A = None
        for k, v in P.items():
            txt = str(v.get("text") or k).replace("\n", " ")[:160]
            entry = (k.startswith("BUY:") or k.startswith("SELL:")) and not v.get("options")
            if auto and entry:
                A = A if A is not None else _tbr("answers.json", {}, inst)
                if A.get(k) is None:
                    A[k] = True; log("tb_auto_yes", inst=inst, key=k)
                    alert("tb", TB_NAME[inst], f"Auto-approved {k.replace(':', ' ')} ({'LIVE orders' if live else 'dry run'}). {txt}", key=f"tbauto:{inst}:{k}")
                continue
            alert("tb", TB_NAME[inst], f"Approve? {txt} — open Live → Futures{' (LIVE orders)' if live else ' (dry run)'}", key=f"tbask:{inst}:{k}")
        if A is not None:
            _tbw("answers.json", A, inst)
            P2 = {k: v for k, v in P.items() if not ((k.startswith("BUY:") or k.startswith("SELL:")) and not v.get("options") and A.get(k) is True)}
            _tbw("pending.json", P2, inst)


def _tb_loop():
    """Top Bottom approvals are checked every 5 s (a reversal prompt in market hours can't wait for the 2-minute loop)."""
    while True:
        _HB["tb"] = time.time()
        try:
            tb_watch()
        except Exception as ex:  # noqa: BLE001
            log("tb_watch_error", error=str(ex)[:200])
        time.sleep(5)


# ------------------------------------------------------------------ background: fills + stops every 2 minutes in market hours
# ------------------------------------------------------------------ US RSI(2) dip-buys on moomoo (14 Nov 2026)
# Same rules as tools/moomoo_rsi2 (project note moomoo-rsi2-bot.md): S&P 500, 50-day avg volume > 2M, price > SMA200 and
# RSI(2) < 10 -> buy near the US close; sell near the close when price > SMA5 or after 7 trading days; GTC stop at
# entry - 3 ATR(14) on moomoo. Levels from data/scan/us/rsi2.json (GitHub job after each US close), live prices from OpenD.
# Orders go out only from the app (typed confirmation), only when Live orders is on, and to moomoo's PAPER account unless
# MOOMOO_ENV=REAL in .env. The server only ever sells shares it bought for this system (us_journal.json).
RSI2_URL = ENV.get("RSI2_URL", "https://raw.githubusercontent.com/drsinghap81/blank-app/main/data/scan/us/rsi2.json")
US_CAPITAL = float(ENV.get("US_RSI2_CAPITAL", "10000")); US_SLOTS = int(ENV.get("US_RSI2_SLOTS", "10"))
US_MAX_ORDERS_DAY = int(ENV.get("US_MAX_ORDERS_DAY", "12")); US_LIMIT_BUF = float(ENV.get("US_LIMIT_BUFFER_PCT", "0.5")) / 100
_rsi2 = dict(t=0, d=None)


def et_now():
    return datetime.now(ET_TZ)


def us_open(t=None):
    t = t or et_now(); return t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) < (16, 0)


def rsi2_prep(max_age=600):
    if _rsi2["d"] is None or time.time() - _rsi2["t"] > max_age:
        r = requests.get(RSI2_URL, params=dict(t=int(time.time())), timeout=30); r.raise_for_status(); _rsi2.update(t=time.time(), d=r.json())
    return _rsi2["d"]


def _usj_path():
    return os.path.join(DATA, "us_journal.json")


def us_journal():
    try:
        return json.load(open(_usj_path()))
    except Exception:  # noqa: BLE001
        return dict(pos={}, closed=[], realized=0.0)


def save_us_journal(J):
    tmp = _usj_path() + ".tmp"; json.dump(J, open(tmp, "w"), indent=1); os.replace(tmp, _usj_path())


def _rsi_now(p, s):
    au = (s["au"] + max(p - s["close"], 0)) / 2; ad = (s["ad"] + max(s["close"] - p, 0)) / 2
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def _us_days(since, t):
    import numpy as np
    return int(np.busday_count(since, t.date().isoformat()))


def us_plan():
    """Live buy and sell rows for the RSI(2) system."""
    P = rsi2_prep(); ST = P["stocks"]; J = us_journal(); t = et_now()
    note = None; snap = {}; outside = {}
    if not (moomoo.enabled and moomoo.trade_on):
        note = "moomoo trading is off on the server (MOOMOO_ENABLED=1 and MOOMOO_TRADE=1 in .env, with OpenD running)."
    else:
        try:
            snap = moomoo.snapshot(sorted(set(P["signals"]) | set(P.get("watch", [])) | set(J["pos"])))
            held = moomoo.us_positions(); outside = {k: v for k, v in held.items() if k not in J["pos"]}
        except Exception as ex:  # noqa: BLE001
            note = f"couldn't reach moomoo OpenD: {str(ex)[:160]}"
    live = bool(snap) and us_open(t)
    slot = (US_CAPITAL + J.get("realized", 0.0)) / US_SLOTS; free = US_SLOTS - len(J["pos"])
    buys = []
    for sym in list(dict.fromkeys(P["signals"] + P.get("watch", []))):
        s = ST.get(sym); q = snap.get(sym)
        if not s:
            continue
        px = q["last"] if q and live else s["close"]
        r = _rsi_now(px, s) if live else s["rsi2"]
        ok = px > s["above"] and r < 10
        if not ok and not (sym in P["signals"] and not live):
            continue
        skip = ""
        if sym in J["pos"]:
            skip = "already held by this system"
        elif sym in outside:
            skip = "you hold it outside this system"
        elif free <= 0:
            skip = f"all {US_SLOTS} slots full"
        elif not live:
            skip = "send near the US close (15:45-15:58 New York) when prices are live"
        elif q and abs(q["prev"] / s["close"] - 1) > 0.01:
            skip = "moomoo's previous close doesn't match the data (split?) - skipped"
        qty = math.floor(slot / px) if px > 0 else 0
        buys.append(dict(id=f"US-{sym}", symbol=sym, name=s.get("name", ""), price=round(px, 2), rsi=round(r, 1), qty=qty,
                         limit=round(px * (1 + US_LIMIT_BUF), 2), stop=round(px - 3 * s["atr14"], 2), sell_above=round(s["exit_above"], 2),
                         live=live, skip=skip))
    buys.sort(key=lambda b: b["rsi"])
    sells = []
    for sym, p in J["pos"].items():
        s = ST.get(sym) or {}; q = snap.get(sym)
        px = q["last"] if q else None; days = _us_days(p["date"], t)
        why = ("price above the 5-day average" if px and s.get("exit_above") and px > s["exit_above"] else
               f"{days} trading days held (limit 7)" if days >= 7 else "")
        sells.append(dict(id=f"USX-{sym}", symbol=sym, qty=p["qty"], entry=p["entry"], stop=p["stop"], price=px, days=days,
                          state=p.get("state", "open"), sell=bool(why) and p.get("state") == "open", why=why or "hold",
                          pnl=round((px - p["entry"]) * p["qty"], 2) if px else None))
    return dict(asof=P["asof"], et=t.strftime("%Y-%m-%d %H:%M"), us_open=us_open(t), live_prices=live, note=note,
                env=getattr(moomoo, "env_name", "SIMULATE"), mode="LIVE" if is_live() else "DRY RUN", slot=round(slot, 2),
                capital=US_CAPITAL, realized=round(J.get("realized", 0.0), 2), buys=buys, sells=sells, closed=J.get("closed", [])[-20:])


class USOrder(BaseModel):
    id: str
    qty: int
    confirm: str = ""


@app.get("/api/us/plan")
def us_plan_api(_=Depends(auth)):
    try:
        return us_plan()
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"couldn't build the US plan: {str(ex)[:200]}")


def _wait(oid, secs=20):
    o = moomoo.order(oid); t0 = time.time()
    while o["status"] not in ("FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DELETED", "DISABLED") and time.time() - t0 < secs:
        time.sleep(2); o = moomoo.order(oid)
    return o


def _us_stop(sym, qty, stop):
    try:
        return moomoo.place(sym, "SELL", qty, "STOP", stop, aux=stop, tif="GTC")
    except Exception as ex:  # noqa: BLE001
        alert("stop_missing", sym, f"US {sym}: moomoo refused the protective stop at {stop:.2f} ({str(ex)[:120]}). "
              "The server will sell at the next check if the price is at or below it.", key=f"usstop:{sym}:{et_now().date()}")
        return None


@app.post("/api/us/order")
def us_order(body: USOrder, _=Depends(auth)):
    P = us_plan(); t = et_now()
    if P["note"]:
        raise HTTPException(400, P["note"])
    done = [r for r in today_log() if r.get("kind") in ("us_order", "us_dry")]
    if len(done) >= US_MAX_ORDERS_DAY:
        raise HTTPException(429, f"daily limit of {US_MAX_ORDERS_DAY} US orders reached")
    row = next((r for r in P["buys"] if r["id"] == body.id), None); ex = next((r for r in P["sells"] if r["id"] == body.id), None)
    if not row and not ex:
        raise HTTPException(404, "not in the current US plan (the signal may have gone)")
    if not us_open(t):
        raise HTTPException(400, "the US market is closed; send between 15:45 and 15:58 New York time")
    if row:
        if row["skip"]:
            raise HTTPException(400, row["skip"])
        if body.qty < 1 or body.qty > row["qty"]:
            raise HTTPException(400, f"quantity must be 1..{row['qty']}")
        if body.qty * row["limit"] > min(P["slot"] * 1.05, moomoo.us_cash()):
            raise HTTPException(400, "order value above the slot size or your USD cash")
        side, sym, qty = "BUY", row["symbol"], body.qty
    else:
        if body.qty < 1 or body.qty > ex["qty"]:
            raise HTTPException(400, f"this system holds {ex['qty']}")
        side, sym, qty = "SELL", ex["symbol"], body.qty
    if body.confirm.strip().upper() != f"{side} {qty} {sym}".upper():
        raise HTTPException(400, f'confirm must be "{side} {qty} {sym}"')
    rec = dict(id=body.id, symbol=sym, side=side, qty=qty, env=moomoo.env_name, et=t.isoformat(timespec="seconds"))
    if not is_live():
        log("us_dry", **rec, price=row["limit"] if row else ex["price"])
        return dict(ok=True, mode="DRY RUN", sent=False, env=moomoo.env_name, side=side, qty=qty, symbol=sym,
                    price=row["limit"] if row else ex["price"], stop=row["stop"] if row else None,
                    msg="Dry run: nothing sent. Switch Live orders on to send to moomoo" + (" (paper account)." if moomoo.env_name == "SIMULATE" else "."))
    J = us_journal()
    try:
        if side == "BUY":
            oid = moomoo.place(sym, "BUY", qty, "NORMAL", row["limit"])
            log("us_order", order_id=oid, price=row["limit"], **rec)
            o = _wait(oid)
            if o["dealt"] > 0:
                fill = o["avg"] or row["price"]; st = round(fill - 3 * (rsi2_prep()["stocks"][sym]["atr14"]), 2)
                sid = _us_stop(sym, o["dealt"], st)
                J["pos"][sym] = dict(qty=o["dealt"], entry=fill, stop=st, stop_id=sid, date=t.date().isoformat(), buy_id=oid, state="open")
                msg = f"Bought {o['dealt']:g} {sym} at {fill:.2f} on moomoo ({moomoo.env_name.lower()}). Stop {st:.2f} placed (GTC)." if sid else \
                      f"Bought {o['dealt']:g} {sym} at {fill:.2f}. moomoo refused the stop order; the server watches {st:.2f} instead."
            else:
                J["pos"][sym] = dict(qty=qty, entry=row["limit"], stop=row["stop"], stop_id=None, date=t.date().isoformat(), buy_id=oid, state="pending")
                msg = f"Buy order {oid} placed ({o['status']}); the server adds the stop when it fills."
        else:
            p = J["pos"][sym]
            if p.get("stop_id"):
                moomoo.cancel(p["stop_id"])
            oid = moomoo.place(sym, "SELL", qty, "MARKET", ex["price"] or p["entry"]); log("us_order", order_id=oid, **rec)
            o = _wait(oid)
            if o["dealt"] > 0:
                _us_close(J, sym, o["avg"] or ex["price"], o["dealt"], ex["why"])
                msg = f"Sold {o['dealt']:g} {sym} at {o['avg'] or ex['price']:.2f}."
            else:
                p["state"] = "exiting"; p["sell_id"] = oid; msg = f"Sell order {oid} placed ({o['status']}); the server records the fill."
            if sym in J["pos"] and p.get("state") != "exiting":      # partly sold: protect the rest
                p["stop_id"] = _us_stop(sym, p["qty"], p["stop"])
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log("us_order_error", error=str(e)[:300], **rec); save_us_journal(J)
        raise HTTPException(502, f"moomoo rejected {side} {sym}: {str(e)[:200]}")
    save_us_journal(J)
    return dict(ok=True, mode="LIVE", sent=True, env=moomoo.env_name, order_id=oid, msg=msg)


def _us_close(J, sym, px, qty, why):
    p = J["pos"][sym]; q = min(qty, p["qty"]); pnl = q * (px - p["entry"]); J["realized"] = J.get("realized", 0.0) + pnl; p["qty"] -= q
    J.setdefault("closed", []).append(dict(sym=sym, entry=p["entry"], exit=round(px, 2), qty=q, pnl=round(pnl, 2), why=why,
                                           opened=p["date"], closed=et_now().date().isoformat()))
    if p["qty"] <= 1e-9:
        del J["pos"][sym]
    log("us_exit", symbol=sym, qty=q, price=px, pnl=round(pnl, 2), why=why)


def us_sync():
    """Pending buys -> add the stop; stopped-out or sold positions -> close in the journal; missing broker stop -> sell if hit;
    near the close -> alert sell signals. Runs from the server loop during US hours."""
    if not (moomoo.enabled and moomoo.trade_on):
        return
    J = us_journal()
    if not J["pos"]:
        return
    t = et_now(); held = moomoo.us_positions(); changed = False
    for sym, p in list(J["pos"].items()):
        if p.get("state") == "pending":
            o = moomoo.order(p["buy_id"])
            if o["dealt"] > 0:
                fill = o["avg"] or p["entry"]; st = round(fill - (p["entry"] - p["stop"]), 2)
                p.update(qty=o["dealt"], entry=fill, stop=st, state="open", stop_id=_us_stop(sym, o["dealt"], st)); changed = True
                alert("filled", sym, f"US {sym}: bought {o['dealt']:g} at {fill:.2f}; stop {st:.2f}.", key=f"usfill:{sym}:{p['buy_id']}")
            elif o["status"] in ("CANCELLED_ALL", "FAILED", "DELETED", "DISABLED"):
                del J["pos"][sym]; changed = True
            continue
        if p.get("state") == "exiting" and p.get("sell_id"):
            o = moomoo.order(p["sell_id"])
            if o["dealt"] > 0:
                _us_close(J, sym, o["avg"], o["dealt"], "sold"); changed = True
            continue
        have = held.get(sym, 0)
        if have < p["qty"] - 1e-9:      # stop filled at moomoo (or sold outside the app)
            o = moomoo.order(p["stop_id"]) if p.get("stop_id") else dict(avg=0, status="")
            px = o["avg"] or p["stop"]; _us_close(J, sym, px, p["qty"] - have, "stop" if p.get("stop_id") else "sold outside the app"); changed = True
            alert("stop", sym, f"US {sym}: stop filled at {px:.2f}.", key=f"usstophit:{sym}:{p['date']}")
            continue
        if not p.get("stop_id") and us_open(t):
            q = moomoo.snapshot([sym]).get(sym)
            if q and q["last"] <= p["stop"]:
                oid = moomoo.place(sym, "SELL", p["qty"], "MARKET", q["last"]); o = _wait(oid)
                if o["dealt"] > 0:
                    _us_close(J, sym, o["avg"] or q["last"], o["dealt"], "stop (server check)"); changed = True
                    alert("stop", sym, f"US {sym}: sold {o['dealt']:g} at the stop check, {o['avg'] or q['last']:.2f}.", key=f"usstopsrv:{sym}:{t.date()}")
    if changed:
        save_us_journal(J)
    if t.weekday() < 5 and (15, 35) <= (t.hour, t.minute) <= (15, 55):
        try:
            for r in us_plan()["sells"]:
                if r["sell"]:
                    alert("exit", r["symbol"], f"US {r['symbol']}: sell signal ({r['why']}). Send the sell from the app before 15:58 New York.",
                          key=f"usexit:{r['symbol']}:{t.date()}")
        except Exception as ex:  # noqa: BLE001
            log("us_alert_error", error=str(ex)[:200])


def _loop():
    while True:
        _HB["loop"] = time.time()
        try:
            t = ist_now()
            if t.weekday() < 5 and (9, 0) <= (t.hour, t.minute) <= (16, 0) and any(not k.startswith("_") for k in journal()):
                sync()
            if t.weekday() < 5 and (8, 40) <= (t.hour, t.minute) <= (9, 10) and (last_trail() or {}).get("day") != t.date().isoformat() \
                    and any(not k.startswith("_") for k in journal()):
                trail()
            if ((21, 45) <= (t.hour, t.minute) <= (22, 30) or (8, 30) <= (t.hour, t.minute) <= (8, 50)) and t.weekday() < 6 \
                    and t.minute % 10 < 2:
                exit_alerts()
            if t.minute % 10 < 2:
                pie_alerts()
            if us_open(et_now()) or (et_now().weekday() < 5 and et_now().hour == 16 and et_now().minute < 15):
                us_sync()
        except Exception as ex:  # noqa: BLE001
            log("loop_error", error=str(ex)[:200])
        time.sleep(120)



# ------------------------------------------------------------------ alerts (11 Nov 2026)
# Every important event (stop hit, buy filled, sold, sell signal, stop raised, stop not placed) is written to
# DATA/alerts.json for the app's bell, pushed to the phones that turned on notifications (Web Push, VAPID keys made on
# this server and kept in DATA/vapid.json), and sent to WhatsApp / Telegram if those keys are in the server's env.
def _alerts_path():
    return os.path.join(DATA, "alerts.json")


def alerts_load():
    try:
        return json.load(open(_alerts_path()))
    except Exception:  # noqa: BLE001
        return dict(items=[], seen=[], subs=[])


def alert(kind, symbol, text, key=None):
    """Record and send once (key = de-duplication key, e.g. 'exit:TCS:2026-11-10')."""
    A = alerts_load(); key = key or f"{kind}:{symbol}:{datetime.now(timezone.utc).isoformat(timespec='minutes')}"
    if key in A.get("seen", []):
        return False
    item = dict(id=key, t=datetime.now(timezone.utc).isoformat(timespec="seconds"), kind=kind, symbol=symbol, text=text)
    A.setdefault("items", []).append(item); A["items"] = A["items"][-200:]
    A.setdefault("seen", []).append(key); A["seen"] = A["seen"][-1000:]
    json.dump(A, open(_alerts_path(), "w")); log("alert", akind=kind, symbol=symbol, text=text)
    threading.Thread(target=_send_alert, args=(item, list(A.get("subs", []))), daemon=True).start()
    return True


def _vapid():
    p = os.path.join(DATA, "vapid.json")
    if os.path.exists(p):
        return json.load(open(p))
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    import base64
    k = ec.generate_private_key(ec.SECP256R1())
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    v = dict(private_pem=priv, public=base64.urlsafe_b64encode(pub).decode().rstrip("="))
    json.dump(v, open(p, "w")); os.chmod(p, 0o600)
    return v


def _send_alert(item, subs):
    body = json.dumps(dict(title=f"Trend Desk · {item['symbol']}" if item.get("symbol") else "Trend Desk", body=item["text"], tag=item["id"]))
    dead = []
    if subs:
        try:
            from pywebpush import webpush, WebPushException
            from py_vapid import Vapid
            v = _vapid(); vv = Vapid.from_pem(v["private_pem"].encode())
            for sb in subs:
                try:
                    webpush(subscription_info=sb, data=body, vapid_private_key=vv, vapid_claims=dict(sub="mailto:alerts@trenddesk.app"), ttl=86400)
                except WebPushException as ex:  # noqa: PERF203
                    if getattr(ex, "response", None) is not None and ex.response.status_code in (404, 410):
                        dead.append(sb.get("endpoint"))
                    log("push_error", error=str(ex)[:160])
        except Exception as ex:  # noqa: BLE001
            log("push_error", error=str(ex)[:160])
    if dead:
        A = alerts_load(); A["subs"] = [x for x in A.get("subs", []) if x.get("endpoint") not in dead]; json.dump(A, open(_alerts_path(), "w"))
    try:
        import importlib.util as _iu         # tools/notify.py, loaded by path so it never shadows another "notify" module
        sp = _iu.spec_from_file_location("td_notify", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notify.py"))
        nm = _iu.module_from_spec(sp); sp.loader.exec_module(nm); whatsapp, telegram = nm.whatsapp, nm.telegram
        txt = f"Trend Desk · {item['symbol']}: {item['text']}" if item.get("symbol") else item["text"]
        whatsapp(txt) or telegram(txt)
    except Exception:  # noqa: BLE001
        pass


def exit_alerts():
    """Evening / morning: the plan's sell signals for stocks you hold, once per stock per scan date."""
    try:
        P = plan(); acc = account_cached(600); held = {h["symbol"]: h["qty"] for h in acc.get("holdings", []) if h["qty"] > 0}
    except Exception:  # noqa: BLE001
        return
    J = journal()
    for e in (P.get("exits") or []) + adopted_exits(J, held):
        sym = e.get("symbol")
        if sym in J and J[sym].get("system") and e.get("system") and J[sym]["system"] != e.get("system"):
            continue                                   # an exit for a different system than the one holding it
        if held.get(sym, 0) > 0:
            alert("exit", sym, f"Sell signal ({e.get('system') or 'system'}): {e.get('why') or 'exit rule met'}. Sell {held[sym]} at the next open.",
                  key=f"exit:{sym}:{P.get('asof')}")


_PIES = {"t": 0}


def pie_alerts():
    """Trading 212 pies (US): one alert when a month-end decision changes what a pie should hold."""
    if time.time() - _PIES["t"] < 3600:
        return
    _PIES["t"] = time.time()
    try:
        d = requests.get(PLAN_URL.rsplit("/", 1)[0] + "/us/pies.json", timeout=30).json()
    except Exception:  # noqa: BLE001
        return
    for p in d.get("pies") or []:
        if p.get("changed"):
            now = ", ".join(f"{x['ticker']} {x['pct']:g}%" for x in p.get("hold") or [])
            was = ", ".join(f"{x['ticker']} {x['pct']:g}%" for x in p.get("before") or [])
            alert("pie", "", f"Trading 212 · {p.get('title')}: now hold {now}" + (f" (was {was})" if was else "") + ". Rebalance at the next US session.",
                  key=f"pie:{p.get('key')}:{p.get('decided')}")


class PushSub(BaseModel):
    subscription: dict


@app.get("/api/alerts")
def alerts_list(_=Depends(auth)):
    A = alerts_load()
    return dict(items=list(reversed(A.get("items", [])))[:50], push=len(A.get("subs", [])))


@app.get("/api/push/key")
def push_key(_=Depends(auth)):
    return dict(key=_vapid()["public"])


@app.post("/api/push/subscribe")
def push_subscribe(body: PushSub, _=Depends(auth)):
    sb = body.subscription
    if not sb.get("endpoint"):
        raise HTTPException(400, "no endpoint")
    A = alerts_load(); A["subs"] = [x for x in A.get("subs", []) if x.get("endpoint") != sb["endpoint"]] + [sb]
    json.dump(A, open(_alerts_path(), "w"))
    return dict(ok=True, devices=len(A["subs"]))


@app.post("/api/push/test")
def push_test(_=Depends(auth)):
    alert("test", "", "Test alert: notifications are working.")
    return dict(ok=True)

# ------------------------------------------------------------------ research jobs (10 Nov 2026): ORB on Angel 1-minute history
_rj = {}


def research_job():
    if "j" not in _rj:
        import research
        _rj["j"] = research.Job(broker, DATA, log=lambda ev, **kw: log(ev, **kw))
    return _rj["j"]


@app.get("/api/research/orb")
def research_status(_=Depends(auth)):
    return research_job().status()


@app.post("/api/research/orb")
def research_start(_=Depends(auth)):
    return dict(started=research_job().start(), **research_job().status())


@app.on_event("startup")
def _start():
    if ENV.get("MOCK_BROKER") != "1":
        import threading
        threading.Thread(target=_loop, daemon=True).start()
        threading.Thread(target=_tb_loop, daemon=True).start()
        if ENV.get("RESEARCH_AUTO", "0") == "1":          # 11 Nov 2026: research test removed at Amritpal's request (off unless RESEARCH_AUTO=1)
            try:
                j = research_job()
                import research as _r
                old = (j.status().get("results") or {}).get("version") != getattr(_r, "VERSION", 1)
                if j.st.get("state") in ("idle", "running") or (j.st.get("state") == "done" and old):
                    j.start()          # a new test version re-runs: new days are fetched, then every test is analysed again
            except Exception as ex:  # noqa: BLE001
                log("research_error", error=str(ex)[:200])


if __name__ == "__main__":
    import getpass
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        print(make_hash(getpass.getpass("App password: ")))
    elif len(sys.argv) > 1 and sys.argv[1] == "secret":
        print(os.urandom(32).hex())
