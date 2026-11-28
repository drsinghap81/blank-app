"""Top Bottom on Bitcoin and Ether with CoinDCX futures prices (29 Nov 2026, Amritpal: "connect BTC ETH bots to coin dcx and do a trial
paper run" + "Live also as an option to me in app").

Prices: CoinDCX's own futures (B-BTC_USDT, B-ETH_USDT; public API, no key): daily candles are UTC days (05:30 IST / 11:00 Melbourne
summer), 1-minute candles for the running day. Checked every 20 seconds, minute by minute, so the order of events inside the day is real.
Rules = tools/topbottom_backtest.run_live and the Bank Nifty bot (tools/angel/tb_live.py), crypto settings 1/2/2:
  levels  : last top / bottom of the daily CLOSE (1-day turns) from completed UTC days; buy above top + 0.05%, sell below bottom - 0.05%;
            each level trades once; a day that OPENS more than 1% beyond a level does not trade it.
  entry   : at max(day open, level) (a stop order at the level); entry-day stop 1% from entry, live all day (like the Bank Nifty bot);
  after   : stop = the opposite system point - 0.05%, never wider than 2% from entry; breakeven once a later day has been +2% in favour;
            stopped at the system point -> reverse (both-sides book), else flat until a new level trades.
Paper books, always on, per coin: "both" (futures, long and short) and "buy" (buy only). Notional Rs 1,00,000 per book, compounded.
Cost 0.15% a round trip (CoinDCX taker fee 0.059% a side + slippage).
LIVE (off by default, per coin): mirrors ONE book on CoinDCX futures (INR margin): market order when the book enters, an exchange
stop-market on the position at the book's stop (moved every UTC day), exit/reverse when the book does. Needs COINDCX_API_KEY /
COINDCX_API_SECRET in /opt/trenddesk/.env (deploy/coindcx_keys.sh) and the app password + typing LIVE. Live joins at the NEXT entry,
never in the middle of a paper trade."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))                        # tools/ (topbottom_backtest)
from topbottom_backtest import confirmed_swings  # noqa: E402

PAIRS = {"BTC": "B-BTC_USDT", "ETH": "B-ETH_USDT"}
BUF, DAY_SL, MAX_SL, BE, GAP = 0.0005, 1.0, 2.0, 2.0, 1.0
SWING = 0.0            # 29 Nov 2026 "proper V" tests: a top / bottom counts only after the close turned this % (0 = every 1-day turn, live)
VLEG, VBUF = None, 0.005   # course V rule: when the move INTO a turn is under VLEG %, add VBUF to the buffer (None = off, live)


def _swings(c):
    T, B, pv = confirmed_swings(np.asarray(c, float), SWING)
    leg = {}
    if VLEG is not None:
        for k in range(1, len(pv)):
            leg[pv[k][3]] = abs(pv[k][3] / pv[k - 1][3] - 1) * 100
    return T, B, leg


def bufx(v, leg):
    return BUF + (VBUF if VLEG is not None and leg.get(v, 99) < VLEG else 0.0)
COST = 0.0015
CAP = 100000.0
QSTEP = 0.001                                                     # CoinDCX quantity step and minimum, BTC and ETH
MAX_LEV, MAX_INR = 5, 500000
PUB = "https://public.coindcx.com"
API = "https://api.coindcx.com"
IST = timezone(timedelta(hours=5, minutes=30))
EPS = 1e-9


def utcnow():
    return datetime.now(timezone.utc)


def day_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ CoinDCX
class DCX:
    """public data + (when keys exist) signed futures calls."""

    def __init__(self, env_file="/opt/trenddesk/.env"):
        self.env_file = env_file
        self.s = requests.Session(); self.s.headers["User-Agent"] = "trenddesk/1"

    def candles(self, pair, res, t0, t1):
        r = self.s.get(PUB + "/market_data/candlesticks", params={"pair": pair, "from": int(t0), "to": int(t1), "resolution": res, "pcode": "f"},
                       timeout=20)
        r.raise_for_status()
        rows = r.json().get("data") or []
        out = []
        for x in rows:
            ts = x["time"] / 1000 if x["time"] > 1e11 else x["time"]
            out.append((int(ts), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])))
        return sorted(set(out))

    def usdtinr(self):
        try:
            return float(self.s.get(API + "/api/v1/derivatives/futures/data/conversions", timeout=15).json()[0]["conversion_price"])
        except Exception:  # noqa: BLE001
            return None

    # ---- keys and signed calls
    def keys(self):
        """the server's .env first (deploy/coindcx_keys.sh; no restart needed), then the process environment."""
        k = s = None
        if os.path.exists(self.env_file):
            try:
                for line in open(self.env_file, encoding="utf-8"):
                    if "=" in line and not line.lstrip().startswith("#"):
                        a, b = line.strip().split("=", 1)
                        v = b.strip().strip("'").strip('"')
                        if a == "COINDCX_API_KEY":
                            k = v
                        elif a == "COINDCX_API_SECRET":
                            s = v
            except Exception:  # noqa: BLE001
                pass
        k = k or os.environ.get("COINDCX_API_KEY"); s = s or os.environ.get("COINDCX_API_SECRET")
        return (k, s) if k and s else (None, None)

    def has_keys(self):
        return self.keys()[0] is not None

    def post(self, path, body):
        k, s = self.keys()
        if not k:
            raise RuntimeError("no CoinDCX API key on the server")
        body = dict(body, timestamp=int(time.time() * 1000))
        js = json.dumps(body, separators=(",", ":"))
        sig = hmac.new(s.encode(), js.encode(), hashlib.sha256).hexdigest()
        r = self.s.post(API + path, data=js, headers={"Content-Type": "application/json", "X-AUTH-APIKEY": k, "X-AUTH-SIGNATURE": sig}, timeout=20)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"raw": r.text[:300]}
        if r.status_code >= 400:
            raise RuntimeError(f"CoinDCX {path} {r.status_code}: {str(j)[:200]}")
        return j

    def positions(self):
        j = self.post("/exchange/v1/derivatives/futures/positions", {"page": "1", "size": "50", "margin_currency_short_name": ["INR", "USDT"]})
        return j if isinstance(j, list) else j.get("data", [])

    def position(self, pair):
        for p in self.positions():
            if p.get("pair") == pair:
                return p
        return None

    def market(self, pair, side, qty, lev):
        return self.post("/exchange/v1/derivatives/futures/orders/create", {"order": {
            "side": side, "pair": pair, "order_type": "market_order", "total_quantity": qty, "leverage": int(lev),
            "notification": "no_notification", "hidden": False, "post_only": False, "margin_currency_short_name": "INR"}})

    def set_stop(self, pos_id, stop):
        try:
            self.post("/exchange/v1/derivatives/futures/positions/cancel_all_open_orders_for_position", {"id": pos_id})
        except Exception:  # noqa: BLE001
            pass
        return self.post("/exchange/v1/derivatives/futures/positions/create_tpsl",
                         {"id": pos_id, "stop_loss": {"stop_price": str(stop), "order_type": "stop_market"}})

    def exit(self, pos_id):
        try:
            self.post("/exchange/v1/derivatives/futures/positions/cancel_all_open_orders_for_position", {"id": pos_id})
        except Exception:  # noqa: BLE001
            pass
        return self.post("/exchange/v1/derivatives/futures/positions/exit", {"id": pos_id})


# ------------------------------------------------------------------ one paper book (pure logic, no I/O)
def new_book():
    return dict(pos=0, entry=0.0, entry_day=None, be_on=False, used_T=None, used_B=None, since=None, done_day=None,
                equity=CAP, trades=[], open_trade=None)


def same(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-9


def plan_for(closes, highs, lows, bk):
    """levels from completed days (closes) + the book's stop for today."""
    T, B, leg = _swings(closes)
    top = None if np.isnan(T[-1]) else float(T[-1]); bot = None if np.isnan(B[-1]) else float(B[-1])
    bt = bufx(top, leg) if top is not None else 0; bb = bufx(bot, leg) if bot is not None else 0
    buy = top * (1 + bt) if top is not None and not same(top, bk["used_T"]) else None
    sell = bot * (1 - bb) if bot is not None and not same(bot, bk["used_B"]) else None
    P = dict(top=top, bot=bot, buy=buy, sell=sell, prot=None, sys=False)
    if bk["pos"]:
        e, s = bk["entry"], bk["pos"]
        prot = e * (1 - s * MAX_SL / 100)
        if s > 0 and bot is not None:
            prot = max(prot, bot * (1 - bb))
        if s < 0 and top is not None:
            prot = min(prot, top * (1 + bt))
        if bk["be_on"]:
            prot = max(prot, e) if s > 0 else min(prot, e)
        P["prot"] = prot
        P["sys"] = bool((s > 0 and sell is not None and abs(prot - sell) < 1e-6) or (s < 0 and buy is not None and abs(prot - buy) < 1e-6))
    return P


def init_used(closes, highs, lows, bk):
    """start flat: a top / bottom price has already broken since it formed is spent (run_live start_flat_on)."""
    c = np.asarray(closes, float); h = np.asarray(highs, float); l = np.asarray(lows, float)
    T, B, leg = _swings(c); n = len(c)
    for arr, is_top in ((T, True), (B, False)):
        v = arr[n - 1]
        if np.isnan(v):
            continue
        k = int(np.argmax(arr == v))
        if is_top and len(h[k + 1:]) and h[k + 1:].max() >= v * (1 + bufx(float(v), leg)):
            bk["used_T"] = float(v)
        if not is_top and len(l[k + 1:]) and l[k + 1:].min() <= v * (1 - bufx(float(v), leg)):
            bk["used_B"] = float(v)


class Book:
    """minute-by-minute driver of one book; events are returned for the live mirror and the log."""

    def __init__(self, bk, both):
        self.b, self.both = bk, both

    def _open(self, day, side, px, why, ts):
        b = self.b
        b.update(pos=side, entry=float(px), entry_day=day, be_on=False, since=[px, px])
        b["open_trade"] = dict(side="BUY" if side > 0 else "SELL", entry_day=day, entry=round(px, 4), why=why, ts=ts)
        return ("enter", side, px, why)

    def _close(self, day, px, why):
        b = self.b; t = b["open_trade"] or {}
        ret = b["pos"] * (px / b["entry"] - 1) - COST
        pnl = b["equity"] * ret; b["equity"] += pnl
        b["trades"].append(dict(t, exit_day=day, exit=round(px, 4), why_out=why, pct=round(ret * 100, 3), pnl=round(pnl, 2)))
        b["trades"] = b["trades"][-200:]
        b.update(pos=0, entry=0.0, entry_day=None, be_on=False, since=None, open_trade=None)
        return ("exit", px, why)

    def minute(self, day, P, o, hi, lo, bar, ts):
        """o = day open; hi/lo = day so far incl. this bar; bar = (ts,o,h,l,c) of this minute."""
        b, ev = self.b, []
        if b["pos"] and b["entry_day"] != day:                     # stops set from earlier days
            prot, s = P["prot"], b["pos"]
            if (s > 0 and bar[3] <= prot + EPS) or (s < 0 and bar[2] >= prot - EPS):
                gap_open = (s > 0 and o < prot) or (s < 0 and o > prot)
                px = min(o, prot) if s > 0 else max(o, prot)
                rev = False
                if P["sys"] and (self.both or s < 0):
                    if s > 0:
                        b["used_B"] = P["bot"]
                    else:
                        b["used_T"] = P["top"]
                    lvl = P["sell"] if s > 0 else P["buy"]
                    rev = not (gap_open and abs(o - lvl) / lvl * 100 > GAP)
                elif P["sys"] and s > 0:
                    b["used_B"] = P["bot"]
                why = ("System point" if P["sys"] else ("Breakeven" if b["be_on"] else "Max SL")) + (" (gap)" if gap_open else "")
                ev.append(self._close(day, px, why))
                if rev:
                    ev.append(self._open(day, -s, px, "Reverse at system point", ts))
                else:
                    b["done_day"] = day
                return ev
            return ev
        if b["pos"] and b["entry_day"] == day:                     # entry-day stop, live all day
            if bar[0] > (b["open_trade"] or {}).get("ts", 0):
                b["since"] = [max(b["since"][0], bar[2]), min(b["since"][1], bar[3])]
            stop = b["entry"] * (1 - b["pos"] * DAY_SL / 100)
            if (b["pos"] > 0 and b["since"][1] <= stop) or (b["pos"] < 0 and b["since"][0] >= stop):
                ev.append(self._close(day, stop, "Entry-day SL")); b["done_day"] = day
            return ev
        if b["pos"] == 0 and b["done_day"] != day:
            go_l = P["buy"] is not None and hi >= P["buy"] and not same(P["top"], b["used_T"])
            go_s = self.both and P["sell"] is not None and lo <= P["sell"] and not same(P["bot"], b["used_B"])
            if go_l and go_s:
                go_l = abs(o - P["buy"]) <= abs(o - P["sell"]); go_s = not go_l
            if go_l:
                b["used_T"] = P["top"]
                if o > P["buy"] and (o - P["buy"]) / P["buy"] * 100 > GAP:
                    ev.append(("skip", f"opened > {GAP}% above the buy level {P['buy']:,.2f}: no trade (level used)"))
                else:
                    ev.append(self._open(day, 1, max(o, P["buy"]), "Buy above prev top", ts))
            elif go_s:
                b["used_B"] = P["bot"]
                if o < P["sell"] and (P["sell"] - o) / P["sell"] * 100 > GAP:
                    ev.append(("skip", f"opened > {GAP}% below the sell level {P['sell']:,.2f}: no trade (level used)"))
                else:
                    ev.append(self._open(day, -1, min(o, P["sell"]), "Sell below prev bottom", ts))
        return ev

    def end_day(self, day, dh, dl):
        """after the UTC day closes: breakeven arms when a day after the entry day was +2% in favour."""
        b = self.b
        if b["pos"] and b["entry_day"] != day and not b["be_on"]:
            fav = (dh - b["entry"]) / b["entry"] * 100 if b["pos"] > 0 else (b["entry"] - dl) / b["entry"] * 100
            if fav >= BE:
                b["be_on"] = True
                return True
        return False


# ------------------------------------------------------------------ the server job
class CryptoTB:
    def __init__(self, data_dir, log=lambda ev, **kw: None, alert=None, dcx=None):
        self.log = log; self.alert = alert or (lambda text, key=None: None)
        self.sp = os.path.join(data_dir, "crypto_tb.json")
        self.dcx = dcx or DCX(os.environ.get("ENV_FILE", "/opt/trenddesk/.env"))
        self.lock = threading.Lock(); self.thread = None
        self.last_run = None; self.last_error = None; self.daily = {}
        self.st = self._load()

    def _load(self):
        try:
            return json.load(open(self.sp))
        except Exception:  # noqa: BLE001
            return dict(start=utcnow().strftime("%Y-%m-%d"), books={}, live={c: dict(on=False, book="both", inr=10000, lev=1) for c in PAIRS},
                        live_global=False, lpos={}, notes=[], day=None, last_ts={})

    def _save(self):
        json.dump(self.st, open(self.sp + ".tmp", "w")); os.replace(self.sp + ".tmp", self.sp)

    def note(self, txt, push=False):
        self.st.setdefault("notes", []).append(f"{datetime.now(IST):%d %b %H:%M} IST {txt}"); self.st["notes"] = self.st["notes"][-80:]
        self.log("crypto_tb", note=txt)
        if push:
            try:
                self.alert(txt)
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- data
    def _daily(self, coin, force=False):
        today = utcnow().strftime("%Y-%m-%d")
        d = self.daily.get(coin)
        if d and d["day"] == today and not force:
            return d
        now = int(time.time())
        rows = self.dcx.candles(PAIRS[coin], "1D", now - 500 * 86400, now)
        done = [r for r in rows if day_of(r[0]) < today]
        if len(done) < 30:
            raise RuntimeError(f"{coin}: only {len(done)} daily candles from CoinDCX")
        d = dict(day=today, days=[day_of(r[0]) for r in done], o=[r[1] for r in done], h=[r[2] for r in done], l=[r[3] for r in done],
                 c=[r[4] for r in done])
        self.daily[coin] = d
        return d

    def _minutes(self, coin, since_ts):
        now = int(time.time())
        return [r for r in self.dcx.candles(PAIRS[coin], "1", since_ts, now) if r[0] + 60 <= now]     # completed minutes only

    # ---------------------------------------------------------------- one pass
    def run_once(self):
        with self.lock:
            try:
                self._pass()
                self.last_error = None
            except Exception as ex:  # noqa: BLE001
                self.last_error = f"{type(ex).__name__}: {str(ex)[:200]}"
            self.last_run = datetime.now(IST).strftime("%d %b %H:%M:%S")
            self._save()

    def _plan(self, D, day, bk):
        k = sum(1 for d in D["days"] if d < day)                    # levels from completed days before `day`
        return plan_for(D["c"][:k], D["h"][:k], D["l"][:k], bk)

    def _pass(self):
        now = int(time.time()); today = utcnow().strftime("%Y-%m-%d")
        t_day0 = int(datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        for coin in PAIRS:
            D = self._daily(coin)
            for nm in ("both", "buy"):
                key = f"{coin}:{nm}"
                if key not in self.st["books"]:
                    bk = new_book(); init_used(D["c"], D["h"], D["l"], bk); self.st["books"][key] = bk
                    self.note(f"{coin} {nm}: paper book started flat (spent levels: top {bk['used_T']}, bottom {bk['used_B']})")
            last = self.st.setdefault("last_ts", {}).get(coin) or (t_day0 - 60)
            db = self.st.setdefault("dbar", {}).get(coin)
            rows = [r for r in self._minutes(coin, max(last - 120, now - 2 * 86400)) if r[0] > last]
            Pl = {}
            for r in rows:
                d = day_of(r[0])
                if db is None or db["day"] != d:                    # a new UTC day starts
                    if db is not None:
                        for nm in ("both", "buy"):
                            if Book(self.st["books"][f"{coin}:{nm}"], nm == "both").end_day(db["day"], db["h"], db["l"]):
                                self.note(f"{coin} {nm}: breakeven armed - the stop moves to the entry")
                        if d == today:
                            D = self._daily(coin, force=True)
                    db = self.st["dbar"][coin] = dict(day=d, o=r[1], h=r[2], l=r[3], last=r[4])
                    Pl = {nm: self._plan(D, d, self.st["books"][f"{coin}:{nm}"]) for nm in ("both", "buy")}
                    self._live_daily(coin, D, d)
                if not Pl:
                    Pl = {nm: self._plan(D, d, self.st["books"][f"{coin}:{nm}"]) for nm in ("both", "buy")}
                db["h"] = max(db["h"], r[2]); db["l"] = min(db["l"], r[3]); db["last"] = r[4]
                for nm in ("both", "buy"):
                    bk = self.st["books"][f"{coin}:{nm}"]
                    evs = Book(bk, nm == "both").minute(d, Pl[nm], db["o"], db["h"], db["l"], r, r[0])
                    if evs:
                        Pl[nm] = self._plan(D, d, bk)
                        for e in evs:
                            self._event(coin, nm, e)
                last = r[0]
            self.st["last_ts"][coin] = last
            if db:
                self.st.setdefault("px", {})[coin] = db["last"]
                self.st.setdefault("plans", {})[coin] = {nm: self._plan(D, db["day"], self.st["books"][f"{coin}:{nm}"]) for nm in ("both", "buy")}
            self._live_check(coin)

    def _event(self, coin, nm, e):
        if e[0] == "skip":
            self.note(f"{coin} {nm}: {e[1]}"); return
        if e[0] == "enter":
            side, px, why = e[1], e[2], e[3]
            stop = px * (1 - side * DAY_SL / 100)
            self.note(f"{coin} {nm}: {'BUY' if side > 0 else 'SELL'} at {px:,.2f} - {why}. Entry-day stop {stop:,.2f}", push=True)
        else:
            self.note(f"{coin} {nm}: exit at {e[1]:,.2f} - {e[2]}", push=True)
        self._live_event(coin, nm, e)

    # ---------------------------------------------------------------- live mirror
    def _lcfg(self, coin):
        return self.st.setdefault("live", {}).setdefault(coin, dict(on=False, book="both", inr=10000, lev=1))

    def _qty(self, coin, px):
        fx = self.dcx.usdtinr() or 90.0
        c = self._lcfg(coin)
        q = math.floor(c["inr"] / (fx * px) / QSTEP + 1e-9) * QSTEP
        return round(q, 3)

    def _live_event(self, coin, nm, e):
        c = self._lcfg(coin)
        if not (c.get("on") and c.get("book") == nm):
            return
        lp = self.st.setdefault("lpos", {}).get(coin)
        try:
            if e[0] == "exit" and lp:
                p = self.dcx.position(PAIRS[coin])
                if p and abs(float(p.get("active_pos") or 0)) > 0:
                    self.dcx.exit(p["id"])
                self.note(f"{coin} LIVE: exit sent to CoinDCX ({e[2]})", push=True)
                self.st["lpos"].pop(coin, None)
            elif e[0] == "enter":
                if lp:
                    return
                side, px = e[1], e[2]
                q = self._qty(coin, px)
                if q < QSTEP:
                    self.note(f"{coin} LIVE: size Rs {c['inr']:,} is below the minimum 0.001 {coin} - no order", push=True); return
                self.dcx.market(PAIRS[coin], "buy" if side > 0 else "sell", q, c.get("lev", 1))
                stop = round(px * (1 - side * DAY_SL / 100), 1 if coin == "BTC" else 2)
                time.sleep(2)
                p = self.dcx.position(PAIRS[coin])
                if p and abs(float(p.get("active_pos") or 0)) > 0:
                    self.dcx.set_stop(p["id"], stop)
                    self.st["lpos"][coin] = dict(side=side, qty=q, id=p["id"], avg=p.get("avg_price"), stop=stop, book=nm, day=utcnow().strftime("%Y-%m-%d"))
                    self.note(f"{coin} LIVE: {'bought' if side > 0 else 'sold'} {q} on CoinDCX at ~{float(p.get('avg_price') or px):,.2f}, stop-market {stop:,.2f}", push=True)
                else:
                    self.note(f"{coin} LIVE: order sent but no position seen on CoinDCX - check the CoinDCX app", push=True)
        except Exception as ex:  # noqa: BLE001
            self.note(f"{coin} LIVE ERROR: {str(ex)[:180]} - check the CoinDCX app", push=True)

    def _live_daily(self, coin, D, day):
        """new UTC day: move the exchange stop to the book's stop for today."""
        lp = (self.st.get("lpos") or {}).get(coin)
        if not lp:
            return
        bk = self.st["books"].get(f"{coin}:{lp['book']}")
        if not bk or not bk["pos"]:
            return
        P = self._plan(D, day, bk)
        if P["prot"] is None:
            return
        stop = round(P["prot"], 1 if coin == "BTC" else 2)
        try:
            self.dcx.set_stop(lp["id"], stop); lp["stop"] = stop
            self.note(f"{coin} LIVE: stop on CoinDCX moved to {stop:,.2f}")
        except Exception as ex:  # noqa: BLE001
            self.note(f"{coin} LIVE ERROR moving the stop: {str(ex)[:160]}", push=True)

    def _live_check(self, coin):
        """an exchange stop that filled while the book still holds: the live side is flat now (the book decides the next entry)."""
        lp = (self.st.get("lpos") or {}).get(coin)
        if not lp or not self.dcx.has_keys():
            return
        try:
            p = self.dcx.position(PAIRS[coin])
        except Exception:  # noqa: BLE001
            return
        if not p or abs(float(p.get("active_pos") or 0)) == 0:
            self.note(f"{coin} LIVE: no position on CoinDCX any more (stop filled there) - live is flat", push=True)
            self.st["lpos"].pop(coin, None)

    # ---------------------------------------------------------------- app
    def set_live(self, coin, on, book=None, inr=None, lev=None):
        with self.lock:
            c = self._lcfg(coin)
            if book in ("both", "buy"):
                c["book"] = book
            if inr is not None:
                if not (1000 <= inr <= MAX_INR):
                    raise ValueError(f"size Rs 1,000 - {MAX_INR:,}")
                c["inr"] = int(inr)
            if lev is not None:
                if not (1 <= lev <= MAX_LEV):
                    raise ValueError(f"leverage 1 - {MAX_LEV}")
                c["lev"] = int(lev)
            if on and not self.dcx.has_keys():
                raise ValueError("add the CoinDCX API key on the server first (deploy/coindcx_keys.sh)")
            c["on"] = bool(on)
            self.note(f"{coin} LIVE {'ON' if on else 'OFF'}: follows the {c['book']} book, Rs {c['inr']:,} a trade, {c['lev']}x"
                      + ("; joins at the next entry" if on else "; an open CoinDCX position keeps its stop there"))
            self._save()
            return dict(c)

    def status(self):
        st = self.st; out = dict(start=st.get("start"), last_run=self.last_run, last_error=self.last_error, keys=self.dcx.has_keys(),
                                 cost_pct=COST * 100, capital=CAP, coins={}, notes=st.get("notes", [])[-30:], live=st.get("live"), lpos=st.get("lpos"))
        for coin in PAIRS:
            px = (st.get("px") or {}).get(coin); C = dict(price=px, day=(st.get("dbar") or {}).get(coin), books={})
            for nm in ("both", "buy"):
                bk = (st.get("books") or {}).get(f"{coin}:{nm}")
                if not bk:
                    continue
                P = ((st.get("plans") or {}).get(coin) or {}).get(nm) or {}
                tr = bk["trades"]; o = None
                if bk["pos"] and px:
                    o = dict(side="BUY" if bk["pos"] > 0 else "SELL", entry=bk["entry"], entry_day=bk["entry_day"], be=bk["be_on"],
                             stop=(bk["entry"] * (1 - bk["pos"] * DAY_SL / 100)) if bk["entry_day"] == (C["day"] or {}).get("day") else P.get("prot"),
                             open_pct=round(bk["pos"] * (px / bk["entry"] - 1) * 100, 2))
                C["books"][nm] = dict(equity=round(bk["equity"], 2), ret_pct=round((bk["equity"] / CAP - 1) * 100, 2), n=len(tr),
                                      wins=sum(1 for t in tr if t["pnl"] > 0), pos=o, trades=tr[::-1][:20],
                                      buy=None if bk["pos"] else P.get("buy"), sell=None if (bk["pos"] or nm == "buy") else P.get("sell"),
                                      top=P.get("top"), bot=P.get("bot"))
            out["coins"][coin] = C
        return out

    def loop(self):
        while True:
            self.run_once()
            time.sleep(20)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, daemon=True); self.thread.start()
