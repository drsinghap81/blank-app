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


class AngelBroker:
    def __init__(self, cfg: dict, env: dict, log=print, cache_dir: str = "."):
        self.cfg, self.env, self.log = cfg, env, log
        self.dry = bool(cfg.get("dry_run", True))
        self.cache_dir = cache_dir
        self.api = None
        self.contracts = {}          # tradingsymbol -> dict(token, expiry: date, lot, tick)
        self._dry_n = 0

    # ------------------------------------------------------------ session
    def login(self):
        from SmartApi import SmartConnect   # pip install smartapi-python
        import pyotp
        e = self.env
        self.api = SmartConnect(api_key=e["ANGEL_API_KEY"])
        r = self.api.generateSession(e["ANGEL_CLIENT_CODE"], e["ANGEL_PIN"], pyotp.TOTP(e["ANGEL_TOTP_SECRET"]).now())
        if not r or not r.get("status"):
            raise RuntimeError(f"Angel login failed: {r}")
        self.log(f"Angel login OK ({e['ANGEL_CLIENT_CODE']}){' — DRY RUN, no orders will be sent' if self.dry else ''}")
        self.load_contracts()

    def logout(self):
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
        for x in rows:
            if x.get("exch_seg") == "NFO" and x.get("name") == sym and x.get("instrumenttype") == "FUTIDX":
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
        """near month = earliest expiry on/after today (same rule as the backtest series)."""
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
                r = self.api.ltpData("NFO", con, c["token"])
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
        r = self.api.getCandleData({"exchange": "NFO", "symboltoken": c["token"], "interval": "ONE_DAY",
                                    "fromdate": f"{start} 09:15", "todate": f"{end} 15:30"})
        out = []
        for row in (r or {}).get("data") or []:
            ts = datetime.fromisoformat(row[0][:19]).date()
            out.append((ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        return out

    def traded_today(self, con: str) -> bool:
        """holiday check: any 1-minute candle today?"""
        c = self.contracts[con]
        t = date.today()
        r = self.api.getCandleData({"exchange": "NFO", "symboltoken": c["token"], "interval": "ONE_MINUTE",
                                    "fromdate": f"{t} 09:15", "todate": f"{t} 09:30"})
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
             "transactiontype": side, "exchange": "NFO", "ordertype": "STOPLOSS_LIMIT" if kind == "SL" else "LIMIT",
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
