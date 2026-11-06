"""Broker adapters for the live server.

AngelEquity  : Angel One SmartAPI, NSE cash (delivery). Funds, holdings, positions, order book, LTP, LIMIT / STOPLOSS_LIMIT
               orders (no market orders: SEBI 2026 API rules). Orders only from the static IP registered in your SmartAPI app.
MoomooRO     : moomoo (Futu OpenAPI via the OpenD gateway), READ-ONLY - account value and positions. No trade unlock, no orders.
MockBroker   : for tests / running without keys.
Secrets come from the server's environment (.env on the server), never from the app or the repo."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
IST = timezone(timedelta(hours=5, minutes=30))


def ist_now():
    return datetime.now(IST)


def market_open(t=None):
    t = t or ist_now()
    return t.weekday() < 5 and (9, 15) <= (t.hour, t.minute) < (15, 30)


def amo_window(t=None):
    """Angel accepts after-market orders roughly 15:45 - 08:57 IST (and on holidays/weekends)."""
    t = t or ist_now()
    hm = (t.hour, t.minute)
    return t.weekday() >= 5 or hm >= (15, 45) or hm < (8, 57)


class AngelEquity:
    def __init__(self, env: dict, cache_dir: str, log=print):
        self.env, self.cache_dir, self.log = env, cache_dir, log
        self.api, self.day, self.tokens = None, None, {}

    # session: TOTP from the server's secret (one-tap mode); a fresh session each trading day
    def _session(self):
        if self.api is not None and self.day == date.today():
            return self.api
        from SmartApi import SmartConnect  # pip install smartapi-python
        import pyotp
        e = self.env
        api = SmartConnect(api_key=e["ANGEL_API_KEY"])
        r = api.generateSession(e["ANGEL_CLIENT_CODE"], e["ANGEL_PIN"], pyotp.TOTP(e["ANGEL_TOTP_SECRET"]).now())
        if not r or not r.get("status"):
            raise RuntimeError(f"Angel login failed: {r.get('message') if isinstance(r, dict) else r}")
        # smartapi-python 1.5.5 still points GTT at /gtt-service/... ("no Route matched"); Angel's live routes:
        for k, v in {"api.gtt.create": "/rest/secure/angelbroking/gtt/v1/createRule", "api.gtt.modify": "/rest/secure/angelbroking/gtt/v1/modifyRule",
                     "api.gtt.cancel": "/rest/secure/angelbroking/gtt/v1/cancelRule"}.items():
            api._routes[k] = v
        self.api, self.day = api, date.today()
        self._load_tokens()
        self.log("Angel session OK")
        return api

    def _load_tokens(self):
        path = os.path.join(self.cache_dir, f"scrip_master_{date.today()}.json")
        if not os.path.exists(path):
            for f in os.listdir(self.cache_dir):
                if f.startswith("scrip_master_"):
                    os.remove(os.path.join(self.cache_dir, f))
            r = requests.get(MASTER_URL, timeout=120); r.raise_for_status()
            open(path, "wb").write(r.content)
        self.tokens = {x["symbol"]: dict(token=x["token"], tick=float(x.get("tick_size") or 5) / 100)
                       for x in json.load(open(path)) if x.get("exch_seg") == "NSE" and str(x.get("symbol", "")).endswith("-EQ")}

    def _ts(self, symbol):
        ts = f"{symbol}-EQ"
        if ts not in self.tokens:
            raise ValueError(f"{symbol}: not found in Angel's NSE equity list")
        return ts, self.tokens[ts]

    TOKEN_ERR = ("Invalid Token", "AG8001", "AG8002", "AG8003", "Token Expired", "token is invalid")

    def _call(self, fn, *a, tries=3):
        """Angel sometimes answers a burst of calls with an empty / non-JSON body (rate limit): retry briefly.
        If the session was replaced (e.g. the Top Bottom bot logged in with the same key), log in again once."""
        name = getattr(fn, "__name__", None)
        relogged = False
        for k in range(tries + 1):
            try:
                r = fn(*a)
                if isinstance(r, dict) and r.get("status") is False and any(w in str(r.get("message")) + str(r.get("errorcode")) for w in self.TOKEN_ERR) \
                        and not relogged and name:
                    self.api = None; relogged = True; fn = getattr(self._session(), name); continue
                return r
            except Exception as e:  # noqa: BLE001
                if any(w in str(e) for w in self.TOKEN_ERR) and not relogged and name:
                    self.api = None; relogged = True; fn = getattr(self._session(), name); continue
                if k >= tries - 1 or not any(w in str(e) for w in ("JSON", "Expecting value", "parse", "rate", "Access denied")):
                    raise
                time.sleep(0.8 * (k + 1))

    @staticmethod
    def _data(r):
        if isinstance(r, dict):
            if r.get("status") is False:
                raise RuntimeError(r.get("message") or "Angel error")
            return r.get("data")
        return r

    def account(self):
        api = self._session()
        f = self._data(self._call(api.rmsLimit)) or {}
        hold = self._data(self._call(api.holding)) or []
        pos = self._data(self._call(api.position)) or []
        H = [dict(symbol=str(h.get("tradingsymbol", "")).replace("-EQ", ""), qty=int(float(h.get("quantity") or 0)) + int(float(h.get("t1quantity") or 0)),
                  avg=float(h.get("averageprice") or 0), ltp=float(h.get("ltp") or 0), pnl=float(h.get("profitandloss") or 0)) for h in hold]
        P = [dict(symbol=str(p.get("tradingsymbol", "")).replace("-EQ", ""), qty=int(float(p.get("netqty") or 0)),
                  product=p.get("producttype"), ltp=float(p.get("ltp") or 0)) for p in pos if p.get("exchange") == "NSE"]
        cash = float(f.get("availablecash") or 0)
        return dict(broker="Angel One", cash=cash, net=float(f.get("net") or cash), holdings=H, positions=P,
                    holdings_value=sum(h["qty"] * h["ltp"] for h in H),
                    positions_value=sum(p["qty"] * p["ltp"] for p in P if str(p.get("product")).upper() in ("DELIVERY", "CNC") and p["qty"] > 0))

    def ltp(self, symbol):
        api = self._session(); ts, t = self._ts(symbol)
        d = self._data(self._call(api.ltpData, "NSE", ts, t["token"])) or {}
        return float(d.get("ltp") or 0)

    def quotes(self, symbols):
        """Live LTP + previous close for up to 50 NSE symbols in one call (Angel market-data 'OHLC' mode)."""
        api = self._session(); tok = {}
        for sym in symbols:
            ts = f"{sym}-EQ"
            if ts in self.tokens:
                tok[self.tokens[ts]["token"]] = sym
        out = {}
        ids = list(tok)
        for i in range(0, len(ids), 50):
            d = self._data(self._call(api.getMarketData, "OHLC", {"NSE": ids[i:i + 50]})) or {}
            for q in d.get("fetched") or []:
                sym = tok.get(str(q.get("symbolToken")))
                if sym:
                    out[sym] = dict(ltp=float(q.get("ltp") or 0), prev=float(q.get("close") or 0), high=float(q.get("high") or 0),
                                    low=float(q.get("low") or 0), open=float(q.get("open") or 0))
        return out

    def orders(self):
        api = self._session()
        return [dict(id=o.get("orderid"), symbol=str(o.get("tradingsymbol", "")).replace("-EQ", ""), side=o.get("transactiontype"),
                     qty=o.get("quantity"), price=o.get("price"), trigger=o.get("triggerprice"), status=o.get("status"),
                     avg=float(o.get("averageprice") or 0), filled=int(float(o.get("filledshares") or 0)),
                     variety=o.get("variety"), text=o.get("text"), time=o.get("updatetime"))
                for o in (self._data(self._call(api.orderBook)) or [])]

    def params(self, symbol, side, qty, price, kind="LIMIT", trigger=None, amo=False):
        ts, t = self._ts(symbol) if self.tokens else (f"{symbol}-EQ", dict(token="?", tick=0.05))
        tick = t["tick"] or 0.05
        rnd = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
        p = dict(variety="AMO" if amo else ("STOPLOSS" if kind == "SL" else "NORMAL"), tradingsymbol=ts, symboltoken=t["token"],
                 transactiontype=side, exchange="NSE", ordertype="STOPLOSS_LIMIT" if kind == "SL" else "LIMIT",
                 producttype="DELIVERY", duration="DAY", price=f"{rnd(price):.2f}", quantity=str(int(qty)))
        if kind == "SL":
            p["triggerprice"] = f"{rnd(trigger):.2f}"
        return p

    def place(self, p):
        api = self._session()
        if p["tradingsymbol"] not in self.tokens:
            raise ValueError("unknown symbol")
        p["symboltoken"] = self.tokens[p["tradingsymbol"]]["token"]
        r = self._call(api.placeOrderFullResponse, dict(p), tries=1) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("orderid"):
            return str(d["orderid"])
        raise RuntimeError(f"{r.get('message') or 'no order id'} [{r.get('errorcode') or '?'}]")


    def gtt_stop(self, symbol, qty, trigger, limit):
        """Angel GTT (good till triggered, 1 year): SELL `qty` when the price falls to `trigger`, as a LIMIT at `limit`.
        Sits on Angel's side, so it works even if this server is down."""
        api = self._session(); ts, t = self._ts(symbol); tick = t["tick"] or 0.05
        rnd = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
        p = dict(tradingsymbol=ts, symboltoken=str(t["token"]), exchange="NSE", producttype="DELIVERY", transactiontype="SELL",
                 price=f"{rnd(limit):.2f}", qty=str(int(qty)), disclosedqty=str(int(qty)), triggerprice=f"{rnd(trigger):.2f}", timeperiod="365")
        r = self._call(api._postRequest, "api.gtt.create", dict(p), tries=2) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("id"):
            return str(d["id"]), p
        raise RuntimeError(f"{r.get('message') or r} [{r.get('errorcode') or '?'}]")

    def gtt_cancel(self, rule_id, symbol):
        api = self._session(); ts, t = self._ts(symbol)
        r = self._call(api._postRequest, "api.gtt.cancel", dict(id=str(rule_id), symboltoken=str(t["token"]), exchange="NSE"), tries=2) or {}
        if not r.get("status"):
            raise RuntimeError(f"{r.get('message') or r} [{r.get('errorcode') or '?'}]")
        return r


class MoomooRO:
    """Read-only moomoo account via OpenD (host/port of the gateway on the same server). Needs `pip install futu-api`."""

    def __init__(self, env: dict):
        self.host = env.get("MOOMOO_OPEND_HOST", "127.0.0.1"); self.port = int(env.get("MOOMOO_OPEND_PORT", "11111"))
        self.markets = [m.strip() for m in env.get("MOOMOO_MARKETS", "AU,US").split(",") if m.strip()]
        self.enabled = env.get("MOOMOO_ENABLED", "0") == "1"

    def account(self):
        if not self.enabled:
            return dict(broker="moomoo", enabled=False)
        from futu import OpenSecTradeContext, RET_OK, SecurityFirm, TrdEnv, TrdMarket
        out = dict(broker="moomoo", enabled=True, accounts=[])
        for mk in self.markets:
            ctx = OpenSecTradeContext(filter_trdmarket=getattr(TrdMarket, mk), host=self.host, port=self.port,
                                      security_firm=SecurityFirm.FUTUAU)
            try:
                ret, acc = ctx.accinfo_query(trd_env=TrdEnv.REAL)
                ret2, pos = ctx.position_list_query(trd_env=TrdEnv.REAL)
                a = acc.iloc[0].to_dict() if ret == RET_OK and len(acc) else {}
                out["accounts"].append(dict(market=mk, total=a.get("total_assets"), cash=a.get("cash"), currency=a.get("currency"),
                                            positions=[dict(symbol=r.code, qty=float(r.qty), price=float(r.nominal_price), pnl=float(r.pl_val))
                                                       for r in pos.itertuples()] if ret2 == RET_OK else []))
            finally:
                ctx.close()
        return out


class MockBroker(AngelEquity):
    """Fake Angel account for tests and the demo mode (MOCK_BROKER=1)."""

    def __init__(self, *a, **k):
        self.placed = []; self.tokens = {}; self.hold = {"RELIANCE": 10}

    def account(self):
        H = [dict(symbol=s, qty=q, avg=100.0, ltp=100.0, pnl=0.0) for s, q in self.hold.items() if q > 0]
        return dict(broker="Angel One (mock)", cash=800000.0, net=2000000.0, holdings=H, positions=[], holdings_value=sum(h["qty"] * 100 for h in H))

    def ltp(self, symbol):
        return 100.0

    def quotes(self, symbols):
        return {s: dict(ltp=100.0 + i, prev=99.0 + i, high=101.0 + i, low=98.0 + i, open=99.5 + i) for i, s in enumerate(symbols)}

    def orders(self):
        return [dict(id=o["id"], symbol=o["p"]["tradingsymbol"].replace("-EQ", ""), side=o["p"]["transactiontype"], status=o["status"],
                     avg=float(o["p"]["price"]) if o["status"] == "complete" else 0.0,
                     filled=int(o["p"]["quantity"]) if o["status"] == "complete" else 0, text=o.get("text", "")) for o in self.placed]

    def place(self, p):
        oid = f"MOCK{len(self.placed) + 1}"; self.placed.append(dict(id=oid, p=p, status="complete"))
        sym = p["tradingsymbol"].replace("-EQ", ""); q = int(p["quantity"])
        self.hold[sym] = self.hold.get(sym, 0) + (q if p["transactiontype"] == "BUY" else -q)
        return oid

    def gtt_stop(self, symbol, qty, trigger, limit):
        self.gtts = getattr(self, "gtts", {}); gid = f"GTT{len(self.gtts) + 1}"
        self.gtts[gid] = dict(symbol=symbol, qty=qty, trigger=round(trigger, 2), price=round(limit, 2), active=True)
        return gid, self.gtts[gid]

    def gtt_cancel(self, rule_id, symbol):
        self.gtts[rule_id]["active"] = False; return {"status": True}
