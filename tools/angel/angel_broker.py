"""Angel One SmartAPI adapter for the Top Bottom bot.

Only LIMIT and STOPLOSS_LIMIT orders are used (SEBI 2026: no market / IOC orders for API algos).
Orders must come from the static IP registered in your SmartAPI app.
In dry-run mode nothing is sent to the exchange: fills are simulated at the live price.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime, timedelta

import requests

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
DONE = {"complete"}
DEAD = {"rejected", "cancelled"}


TOKEN_ERR = ("Invalid Token", "AG8001", "AG8002", "AG8003", "Token Expired", "token is invalid", "Invalid Session")


class _Guard:
    """18 Nov 2026: the Trend Desk server and this bot share one Angel API key, and a new login can end the other's session.
    Every Angel call goes through here: on a session error the bot logs in again (at most once a minute) and retries once,
    so a server restart never leaves the bot blind or unable to place / cancel orders."""

    def __init__(self, raw, owner):
        self._raw, self._own = raw, owner

    def __getattr__(self, name):
        v = getattr(self._raw, name)
        if not callable(v):
            return v

        def raw(*a, **k):   # 23 Nov 2026: Angel's "exceeding access rate" refusal means the request was NOT done -> wait and retry
            for wait in (1.5, 3, 5, 8, None):
                try:
                    return getattr(self._own.api._raw, name)(*a, **k)
                except Exception as e:  # noqa: BLE001
                    if wait is None or "access rate" not in str(e).lower():
                        raise
                    time.sleep(wait)

        def call(*a, **k):
            try:
                r = raw(*a, **k)
            except Exception as e:  # noqa: BLE001
                if any(w in str(e) for w in TOKEN_ERR) and self._own._relogin(f"{name}: {e}"):
                    return raw(*a, **k)
                raise
            if isinstance(r, dict) and r.get("status") is False and any(w in f"{r.get('message')} {r.get('errorcode')}" for w in TOKEN_ERR) \
                    and self._own._relogin(f"{name}: {r.get('message')}"):
                return raw(*a, **k)
            return r
        return call


class AngelBroker:
    def __init__(self, cfg: dict, env: dict, log=print, cache_dir: str = "."):
        self.cfg, self.env, self.log = cfg, env, log
        self.dry = bool(cfg.get("dry_run", True))
        self.cache_dir = cache_dir
        self.api = None
        self.contracts = {}          # tradingsymbol -> dict(token, expiry: date, lot, tick)
        self.ex = cfg.get("exchange") or "NFO"   # 26 Nov 2026: "MCX" for the commodity sleeves
        self._dry_n = 0

    # ------------------------------------------------------------ session
    def login(self, totp: str | None = None):
        """totp: a 6-digit code typed by you (code mode); otherwise generated from ANGEL_TOTP_SECRET."""
        from SmartApi import SmartConnect   # pip install smartapi-python
        e = self.env
        if not totp:
            import pyotp
            totp = pyotp.TOTP(e["ANGEL_TOTP_SECRET"]).now()
        raw = SmartConnect(api_key=e["ANGEL_API_KEY"])
        r = raw.generateSession(e["ANGEL_CLIENT_CODE"], e["ANGEL_PIN"], totp)
        if not r or not r.get("status"):
            raise RuntimeError(f"Angel login failed: {r}")
        self.api = _Guard(raw, self)
        self.log(f"Angel login OK ({e['ANGEL_CLIENT_CODE']}){' — DRY RUN, no orders will be sent' if self.dry else ''}")
        self.load_contracts()
        out = e.get("TB_SESSION_OUT")
        if out:                       # let a second bot (Nifty) use THIS session instead of logging in again
            import json
            from datetime import datetime
            from zoneinfo import ZoneInfo
            d = dict(day=str(datetime.now(ZoneInfo("Asia/Kolkata")).date()), access_token=getattr(self.api, "access_token", None),
                     refresh_token=getattr(self.api, "refresh_token", None), feed_token=getattr(self.api, "feed_token", None),
                     userId=getattr(self.api, "userId", None))
            tmp = out + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(d, f)
            os.replace(tmp, out)

    def attach(self, path: str) -> bool:
        """Use the session another bot already opened today (no second login, so neither session is invalidated)."""
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from SmartApi import SmartConnect
        try:
            d = json.load(open(path))
        except Exception:   # noqa: BLE001
            return False
        if d.get("day") != str(datetime.now(ZoneInfo("Asia/Kolkata")).date()) or not d.get("access_token"):
            return False
        self.api = _Guard(SmartConnect(api_key=self.env["ANGEL_API_KEY"], access_token=d["access_token"],
                                       refresh_token=d.get("refresh_token"), feed_token=d.get("feed_token"), userId=d.get("userId")), self)
        self.shared = True
        self.log(f"Angel session shared from the main bot{' — DRY RUN, no orders will be sent' if self.dry else ''}")
        self.load_contracts()
        return True

    def _relogin(self, why) -> bool:
        if time.time() - getattr(self, "_last_relogin", 0) < 60 or not self.env.get("ANGEL_TOTP_SECRET"):
            return False
        self._last_relogin = time.time()
        self.log(f"Angel session lost ({why[:120]}) - logging in again")
        try:
            self.shared = False
            self.login(); return True
        except Exception as e:  # noqa: BLE001
            self.log(f"re-login failed: {e}"); return False

    def logout(self):
        if getattr(self, "shared", False) or self.env.get("TB_SESSION_OUT"):
            return                    # the session is shared with the other bot: let it expire at midnight
        try:
            self.api.terminateSession(self.env["ANGEL_CLIENT_CODE"])
        except Exception:   # noqa: BLE001
            pass

    def load_contracts(self):
        path = os.path.join(self.cache_dir, f"scrip_master_{date.today()}.json")
        if not os.path.exists(path):
            for f in os.listdir(self.cache_dir):
                if f.startswith("scrip_master_"):
                    os.remove(os.path.join(self.cache_dir, f))
            r = requests.get(MASTER_URL, timeout=120)
            r.raise_for_status()
            open(path, "wb").write(r.content)
        rows = json.load(open(path))
        sym = self.cfg["symbol"]
        for x in rows:   # FUTSTK: stock-future sleeves (24 Nov 2026); FUTCOM: MCX commodity sleeves (26 Nov 2026)
            if x.get("exch_seg") == self.ex and x.get("name") == sym and x.get("instrumenttype") in ("FUTIDX", "FUTSTK", "FUTCOM"):
                self.contracts[x["symbol"]] = dict(
                    token=x["token"], expiry=datetime.strptime(x["expiry"], "%d%b%Y").date(),
                    lot=int(float(x["lotsize"])), tick=float(x.get("tick_size") or 5) / 100)
        if not self.contracts:
            raise RuntimeError(f"No {sym} futures found in Angel's instrument list")
        self.log("contracts: " + ", ".join(f"{k} (exp {v['expiry']}, lot {v['lot']})" for k, v in sorted(self.contracts.items(), key=lambda kv: kv[1]['expiry'])))

    # ------------------------------------------------------------ contracts
    def _by_expiry(self):
        return sorted(self.contracts, key=lambda k: self.contracts[k]["expiry"])

    def reference_contract(self, today: date) -> str:
        """near month = earliest expiry on/after today (same rule as the backtest series). MCX (26 Nov 2026): roll_days ahead -
        brokers close physically settled MCX contracts before the tender period, so the bot moves to the next one early."""
        today = today + timedelta(days=int(self.cfg.get("roll_days") or 0))
        for k in self._by_expiry():
            if self.contracts[k]["expiry"] >= today:
                return k
        raise RuntimeError("no live futures contract")

    def next_contract(self, con: str) -> str:
        ks = self._by_expiry()
        return ks[ks.index(con) + 1]

    def expiry(self, con: str) -> date:
        return self.contracts[con]["expiry"]

    def lot_size(self, con: str) -> int:
        return self.contracts[con]["lot"]

    def _round(self, con, px, up):
        t = self.contracts[con]["tick"]
        n = px / t
        return round((math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)) * t, 2)

    # ------------------------------------------------------------ market data
    def quote(self, con: str) -> dict:
        c = self.contracts[con]
        for attempt in range(3):
            try:
                r = self.api.ltpData(self.ex, con, c["token"])
                d = r["data"]
                return dict(ltp=float(d["ltp"]), open=float(d["open"]), high=float(d["high"]),
                            low=float(d["low"]), prev_close=float(d["close"]))
            except Exception as e:  # noqa: BLE001
                self.log(f"quote failed ({e}), retrying")
                time.sleep(1 + attempt)
        raise RuntimeError("quote failed 3 times")

    def daily_bars(self, con: str, start: date, end: date):
        """[(date, o, h, l, c), ...] daily candles of one contract."""
        c = self.contracts[con]
        r = self.api.getCandleData({"exchange": self.ex, "symboltoken": c["token"], "interval": "ONE_DAY",
                                    "fromdate": f"{start} 09:00", "todate": f"{end} {self.cfg.get('session_close') or '15:30'}"})
        out = []
        for row in (r or {}).get("data") or []:
            ts = datetime.fromisoformat(row[0][:19]).date()
            out.append((ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        return out

    def traded_today(self, con: str) -> bool:
        """holiday check: any 1-minute candle today?"""
        c = self.contracts[con]
        t = date.today()
        o = self.cfg.get("session_open") or "09:15"; o2 = (datetime.strptime(o, "%H:%M") + timedelta(minutes=15)).strftime("%H:%M")
        r = self.api.getCandleData({"exchange": self.ex, "symboltoken": c["token"], "interval": "ONE_MINUTE",
                                    "fromdate": f"{t} {o}", "todate": f"{t} {o2}"})
        return bool((r or {}).get("data"))

    def net_qty(self) -> dict:
        """net quantity per contract of this symbol held in the account."""
        r = self.api.position() or {}
        out = {}
        for p in r.get("data") or []:
            if p.get("tradingsymbol") in self.contracts:
                q = int(float(p.get("netqty") or 0))
                if q:
                    out[p["tradingsymbol"]] = q
        return out

    # ------------------------------------------------------------ orders
    def _params(self, con, side, qty, price, kind="LIMIT", trig=None, oid=None):
        c = self.contracts[con]
        p = {"variety": "STOPLOSS" if kind == "SL" else "NORMAL", "tradingsymbol": con, "symboltoken": c["token"],
             "transactiontype": side, "exchange": self.ex, "ordertype": "STOPLOSS_LIMIT" if kind == "SL" else "LIMIT",
             "producttype": "CARRYFORWARD", "duration": "DAY", "price": f"{price:.2f}", "quantity": str(int(qty)),
             "ordertag": "topbottom"}
        if trig is not None:
            p["triggerprice"] = f"{trig:.2f}"
        if oid:
            p["orderid"] = oid
            p.pop("ordertag")
        return p

    def order(self, oid) -> dict | None:
        r = self.api.orderBook() or {}
        for o in r.get("data") or []:
            if o.get("orderid") == oid:
                return dict(status=(o.get("status") or "").lower(), avg=float(o.get("averageprice") or 0),
                            filled=int(float(o.get("filledshares") or 0)), text=o.get("text") or "")
        return None

    def execute(self, con, side, qty, why, must_fill=False, timeout_s=90):
        """Marketable LIMIT order, re-priced every few seconds until filled. Returns avg fill or None."""
        slip = self.cfg["slippage_pct"] / 100
        q = self.quote(con)
        if self.dry:
            self.log(f"[DRY] {side} {qty} {con} @ ~{q['ltp']:.2f} ({why})")
            return round(q["ltp"], 2)
        price = self._round(con, q["ltp"] * (1 + slip) if side == "BUY" else q["ltp"] * (1 - slip), side == "BUY")
        oid = self.api.placeOrder(self._params(con, side, qty, price))
        if not oid:
            self.log(f"order rejected at placement: {side} {qty} {con} @ {price}")
            if must_fill:
                time.sleep(2)
                return self.execute(con, side, qty, why, must_fill, timeout_s - 30) if timeout_s > 30 else None
            return None
        self.log(f"order {oid}: {side} {qty} {con} LIMIT {price} ({why})")
        t0, last_mod = time.time(), time.time()
        limit_s = timeout_s * (6 if must_fill else 1)
        while time.time() - t0 < limit_s:
            time.sleep(1)
            o = self.order(oid)
            if o and o["status"] in DONE:
                return o["avg"]
            if o and o["status"] in DEAD:
                self.log(f"order {oid} {o['status']}: {o['text']}")
                if must_fill:
                    return self.execute(con, side, qty - (o["filled"] if o else 0), why, must_fill, timeout_s=timeout_s // 2) if timeout_s > 10 else None
                return None
            if time.time() - last_mod > 4:            # chase
                q = self.quote(con)
                new = self._round(con, q["ltp"] * (1 + slip) if side == "BUY" else q["ltp"] * (1 - slip), side == "BUY")
                if abs(new - price) > 1e-6:
                    try:
                        self.api.modifyOrder(self._params(con, side, qty, new, oid=oid))
                        price = new
                        self.log(f"order {oid} re-priced to {new}")
                    except Exception as e:  # noqa: BLE001
                        self.log(f"modify failed: {e}")
                last_mod = time.time()
        self.cancel(oid, "NORMAL")
        o = self.order(oid)
        if o and o["status"] in DONE:
            return o["avg"]
        return None

    def stop_limit(self, con, side, qty, trig):
        """resting STOPLOSS_LIMIT backstop; limit 1% beyond the trigger so it fills in a fast market."""
        if self.dry:
            self._dry_n += 1
            self.log(f"[DRY] backstop {side} {qty} {con} trigger {trig:.2f}")
            return f"DRY{self._dry_n}"
        trig = self._round(con, trig, side == "BUY")
        price = self._round(con, trig * (1.01 if side == "BUY" else 0.99), side == "BUY")
        oid = self.api.placeOrder(self._params(con, side, qty, price, kind="SL", trig=trig))
        if not oid:
            self.log("⚠️ backstop order rejected")
        return oid

    def cancel(self, oid, variety="STOPLOSS"):
        if not oid or str(oid).startswith("DRY"):
            return
        try:
            self.api.cancelOrder(oid, variety)
        except Exception as e:  # noqa: BLE001
            self.log(f"cancel {oid} failed: {e}")
