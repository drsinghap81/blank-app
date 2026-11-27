"""Broker adapters for the live server.

AngelEquity  : Angel One SmartAPI, NSE cash (delivery). Funds, holdings, positions, order book, LTP, LIMIT / STOPLOSS_LIMIT
               orders (no market orders: SEBI 2026 API rules). Orders only from the static IP registered in your SmartAPI app.
MoomooRO     : moomoo (Futu OpenAPI via the OpenD gateway), READ-ONLY - account value and positions. No trade unlock, no orders.
MockBroker   : for tests / running without keys.
Secrets come from the server's environment (.env on the server), never from the app or the repo."""
from __future__ import annotations

import glob
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")

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
        api = None
        # 18 Nov 2026: use the Top Bottom bot's session when it has one today - a second login with the same API key can end the
        # bot's session (the bot now logs in again by itself, but sharing avoids the tug of war altogether)
        sf = e.get("TB_SESSION_FILE") or "/opt/trenddesk/var/tb/session.json"
        try:
            d = json.load(open(sf))
            if d.get("day") == str(date.today()) and d.get("access_token") and d["access_token"] != getattr(self, "_bad_token", None):
                api = SmartConnect(api_key=e["ANGEL_API_KEY"], access_token=d["access_token"], refresh_token=d.get("refresh_token"),
                                   feed_token=d.get("feed_token"), userId=d.get("userId"))
                self.log("Angel session shared from the Top Bottom bot")
        except Exception:  # noqa: BLE001
            api = None
        if api is None:
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
                    self._bad_token = getattr(self.api, "access_token", None); self.api = None; relogged = True; fn = getattr(self._session(), name); continue
                return r
            except Exception as e:  # noqa: BLE001
                if any(w in str(e) for w in self.TOKEN_ERR) and not relogged and name:
                    self._bad_token = getattr(self.api, "access_token", None); self.api = None; relogged = True; fn = getattr(self._session(), name); continue
                rate = any(w in str(e) for w in ("access rate", "Access denied"))
                if k >= tries or not (rate or any(w in str(e) for w in ("JSON", "Expecting value", "parse"))):
                    raise
                time.sleep((1.5 if rate else 0.8) * (k + 1))   # 11 Nov 2026: Angel's rate limit needs a longer pause

    @staticmethod
    def _data(r):
        if isinstance(r, dict):
            if r.get("status") is False:
                raise RuntimeError(r.get("message") or "Angel error")
            return r.get("data")
        return r

    @staticmethod
    def _hqty(h):
        """Shares held. Angel's "quantity" already includes unsettled T1 shares on some responses and not on others, so
        take the larger of quantity and settled + T1 (never quantity + T1, which counted recent buys twice)."""
        q = int(float(h.get("quantity") or 0)); t1 = int(float(h.get("t1quantity") or 0)); rq = int(float(h.get("realisedquantity") or 0))
        return max(q, rq + t1)

    def account(self):
        api = self._session()
        f = self._data(self._call(api.rmsLimit)) or {}
        hold = self._data(self._call(api.holding)) or []
        pos = self._data(self._call(api.position)) or []
        H = [dict(symbol=str(h.get("tradingsymbol", "")).replace("-EQ", ""), qty=self._hqty(h),
                  avg=float(h.get("averageprice") or 0), ltp=float(h.get("ltp") or 0), pnl=float(h.get("profitandloss") or 0),
                  close=float(h.get("close") or 0) or None) for h in hold]
        P = [dict(symbol=str(p.get("tradingsymbol", "")).replace("-EQ", ""), qty=int(float(p.get("netqty") or 0)),
                  product=p.get("producttype"), ltp=float(p.get("ltp") or 0)) for p in pos if p.get("exchange") == "NSE"]
        avail = float(f.get("availablecash") or 0); coll = float(f.get("collateral") or 0)
        # Angel's availablecash = ledger cash + margin from pledged shares (11 Nov 2026: Funds showed ledger 10.86 L + pledge
        # 1.18 L = 12.04 L). Pledge margin can't buy delivery shares and those shares are already in holdings, so take it out.
        cash = avail - coll if 0 < coll <= avail else avail
        # 16 Nov 2026: money blocked for pending orders (Angel "utiliseddebits") is still yours: Angel's ledger was 5.84 L while
        # availablecash dropped to 3.40 L with 3.60 L utilised for a pending order, and the account value fell 3.6 L that never
        # left. Add the blocked part back, minus what today's executed delivery buys cost (those shares are counted already).
        util = float(f.get("utiliseddebits") or 0)
        bought = sum(float(p.get("totalbuyvalue") or p.get("buyamount") or 0) for p in pos
                     if p.get("exchange") == "NSE" and str(p.get("producttype")).upper() in ("DELIVERY", "CNC"))
        cash += max(0.0, util - bought)
        return dict(broker="Angel One", cash=cash, net=float(f.get("net") or cash), holdings=H, positions=P,
                    rms=dict(availablecash=avail, net=float(f.get("net") or 0), collateral=float(f.get("collateral") or 0),
                             utiliseddebits=float(f.get("utiliseddebits") or 0), m2munrealized=float(f.get("m2munrealized") or 0),
                             utilisedspan=float(f.get("utilisedspan") or 0), availablelimitmargin=float(f.get("availablelimitmargin") or 0)),
                    holdings_value=sum(h["qty"] * h["ltp"] for h in H),
                    positions_value=self._pos_value(H, P))

    @staticmethod
    def _pos_value(H, P):
        """Today's delivery buys (position book) not already in the holdings list. Angel sometimes lists a same-day CNC
        buy in both; adding both doubled those shares in the account value (11 Nov 2026)."""
        held = {}
        for h in H:
            held[h["symbol"]] = held.get(h["symbol"], 0) + h["qty"]
        v = 0.0
        for p in P:
            if str(p.get("product")).upper() in ("DELIVERY", "CNC") and p["qty"] > 0:
                extra = max(0, p["qty"] - held.get(p["symbol"], 0))
                held[p["symbol"]] = max(0, held.get(p["symbol"], 0) - p["qty"])
                v += extra * p["ltp"]
        return v

    def ltp(self, symbol):
        api = self._session(); ts, t = self._ts(symbol)
        d = self._data(self._call(api.ltpData, "NSE", ts, t["token"])) or {}
        return float(d.get("ltp") or 0)

    def index_quotes(self):
        """Nifty 50, Bank Nifty and Sensex from Angel (index tokens), as a backup to Yahoo for the Markets strip."""
        api = self._session(); out = {}
        d = self._data(self._call(api.getMarketData, "OHLC", {"NSE": ["99926000", "99926009"], "BSE": ["99919000"]})) or {}
        names = {"99926000": "Nifty 50", "99926009": "Bank Nifty", "99919000": "Sensex"}
        for q in d.get("fetched") or []:
            n = names.get(str(q.get("symbolToken")))
            if n and q.get("ltp"):
                out[n] = dict(ltp=float(q["ltp"]), prev=float(q.get("close") or 0) or None, high=float(q.get("high") or 0), low=float(q.get("low") or 0),
                              open=float(q.get("open") or 0), t=None)
        return out

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

    def fo_quotes(self, exchange, tokens):
        """19 Nov 2026 (option trader live feed): Angel market-data FULL quotes, 50 tokens a call (limit 10/s, so far lighter than
        one candle-history call per contract). token -> dict(ltp, high, low, open, vol = cumulative day volume, atp = avg traded price)."""
        api = self._session(); out = {}; ids = [str(t) for t in tokens]
        for i in range(0, len(ids), 50):
            d = self._data(self._call(api.getMarketData, "FULL", {exchange: ids[i:i + 50]})) or {}
            for q in d.get("fetched") or []:
                g = lambda *ks: next((float(q[k]) for k in ks if q.get(k) not in (None, "")), 0.0)  # noqa: E731  field names vary
                out[str(q.get("symbolToken"))] = dict(ltp=g("ltp"), high=g("high"), low=g("low"), open=g("open"),
                                                      vol=g("tradeVolume", "volume", "totalTradedVolume", "vtt"),
                                                      atp=g("avgPrice", "averagePrice", "atp", "averageTradedPrice"))
        return out

    def orders(self):
        api = self._session()
        return [dict(id=o.get("orderid"), symbol=str(o.get("tradingsymbol", "")).replace("-EQ", ""), side=o.get("transactiontype"),
                     qty=o.get("quantity"), price=o.get("price"), trigger=o.get("triggerprice"), status=o.get("status"),
                     avg=float(o.get("averageprice") or 0), filled=int(float(o.get("filledshares") or 0)),
                     variety=o.get("variety"), text=o.get("text"), time=o.get("updatetime"))
                for o in (self._data(self._call(api.orderBook)) or [])]

    def trades(self):
        """Today's fills (Angel's trade book; it only shows the current day). Read only."""
        api = self._session()
        return [dict(id=f"{t.get('fillid')}:{t.get('orderid')}", symbol=str(t.get("tradingsymbol", "")).replace("-EQ", ""), side=t.get("transactiontype"),
                     qty=float(t.get("fillsize") or 0), price=float(t.get("fillprice") or 0), product=t.get("producttype"),
                     exchange=t.get("exchange"), time=t.get("filltime"))
                for t in (self._data(self._call(api.tradeBook)) or [])]

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


    # 18 Nov 2026: option orders for the 5-minute option trader (NFO, intraday product, limit / stop-limit only - SEBI 2026)
    def nfo_order(self, tsym, token, side, qty, price, trigger=None, tick=0.05):
        api = self._session()
        rnd = lambda v: round(max(tick, round(v / tick) * tick), 2)  # noqa: E731
        p = dict(variety="STOPLOSS" if trigger else "NORMAL", tradingsymbol=tsym, symboltoken=str(token), transactiontype=side,
                 exchange="NFO", ordertype="STOPLOSS_LIMIT" if trigger else "LIMIT", producttype="INTRADAY", duration="DAY",
                 price=f"{rnd(price):.2f}", quantity=str(int(qty)))
        if trigger:
            p["triggerprice"] = f"{rnd(trigger):.2f}"
        r = self._call(api.placeOrderFullResponse, p, tries=1) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("orderid"):
            return str(d["orderid"])
        raise RuntimeError(f"{r.get('message') or 'no order id'} [{r.get('errorcode') or '?'}]")

    def cancel_order(self, oid, variety="NORMAL"):
        api = self._session()
        return self._call(api.cancelOrder, oid, variety, tries=1)

    def order_map(self):
        """order id -> dict(status, avg, filled) from today's order book."""
        return {str(o["id"]): o for o in self.orders()}

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

    def gtt_oco(self, symbol, qty, target, stop, stop_limit):
        """11 Nov 2026: Angel GTT OCO (1 year): SELL `qty` at the target OR at the stop, whichever comes first; the other leg is
        cancelled. Target leg: trigger `target`, LIMIT 0.5% below (fills in a fast move). Stop leg: trigger `stop`, LIMIT
        `stop_limit`. SmartAPI: gttType=OCO with stoplosstriggerprice / stoplossprice. Raises if Angel refuses it."""
        api = self._session(); ts, t = self._ts(symbol); tick = t["tick"] or 0.05
        rnd = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
        p = dict(tradingsymbol=ts, symboltoken=str(t["token"]), exchange="NSE", producttype="DELIVERY", transactiontype="SELL",
                 gttType="OCO", price=f"{rnd(target * 0.995):.2f}", triggerprice=f"{rnd(target):.2f}",
                 stoplossprice=f"{rnd(stop_limit):.2f}", stoplosstriggerprice=f"{rnd(stop):.2f}",
                 qty=str(int(qty)), disclosedqty=str(int(qty)), timeperiod="365")
        r = self._call(api._postRequest, "api.gtt.create", dict(p), tries=1) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("id"):
            return str(d["id"]), p
        raise RuntimeError(f"{r.get('message') or r} [{r.get('errorcode') or '?'}]")

    def gtt_buy(self, symbol, qty, trigger, limit):
        """Angel GTT BUY (1 year): when the price reaches `trigger`, a LIMIT buy at `limit` goes in. Used for your own picks
        pushed to Live (10 Nov 2026). Sits on Angel's side, so it works even if this server is down."""
        api = self._session(); ts, t = self._ts(symbol); tick = t["tick"] or 0.05
        rnd = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
        p = dict(tradingsymbol=ts, symboltoken=str(t["token"]), exchange="NSE", producttype="DELIVERY", transactiontype="BUY",
                 price=f"{rnd(limit):.2f}", qty=str(int(qty)), disclosedqty=str(int(qty)), triggerprice=f"{rnd(trigger):.2f}", timeperiod="365")
        r = self._call(api._postRequest, "api.gtt.create", dict(p), tries=1) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("id"):
            return str(d["id"]), p
        raise RuntimeError(f"{r.get('message') or r} [{r.get('errorcode') or '?'}]")

    def gtt_modify(self, rule_id, symbol, qty, trigger, limit):
        """Move an existing GTT stop to a new trigger / limit (used by the daily trail; only ever raised)."""
        api = self._session(); ts, t = self._ts(symbol); tick = t["tick"] or 0.05
        rnd = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
        p = dict(id=str(rule_id), symboltoken=str(t["token"]), exchange="NSE", price=f"{rnd(limit):.2f}", qty=str(int(qty)),
                 disclosedqty=str(int(qty)), triggerprice=f"{rnd(trigger):.2f}", timeperiod="365")
        r = self._call(api._postRequest, "api.gtt.modify", dict(p), tries=2) or {}
        if not r.get("status"):
            raise RuntimeError(f"{r.get('message') or r} [{r.get('errorcode') or '?'}]")
        return str((r.get("data") or {}).get("id") or rule_id), p

    def daily_candles(self, symbol, days=420):
        """Completed daily candles from Angel's historical API: list of (date 'YYYY-MM-DD', open, high, low, close)."""
        api = self._session(); ts, t = self._ts(symbol); now = ist_now()
        r = self._call(api.getCandleData, dict(exchange="NSE", symboltoken=str(t["token"]), interval="ONE_DAY",
                                                fromdate=(now - timedelta(days=days)).strftime("%Y-%m-%d 09:15"),
                                                todate=now.strftime("%Y-%m-%d %H:%M")), tries=4) or {}
        rows = self._data(r) or []
        out = [(str(x[0])[:10], float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in rows]
        today = now.date().isoformat()
        if out and out[-1][0] == today and (now.hour, now.minute) < (15, 35):
            out = out[:-1]                                   # today's candle is not complete yet
        time.sleep(0.6)                                      # Angel: ~3 historical calls a second (kept below it)
        return out

    # ---- F&O / MCX (17 Nov 2026): read-only helpers for the derivatives watch (no orders)
    def fo_positions(self):
        """Open NFO / MCX / BFO / CDS positions from Angel's position book (read only)."""
        api = self._session(); out = []
        for p in (self._data(self._call(api.position)) or []):
            if p.get("exchange") not in ("MCX", "NFO", "BFO", "CDS") or int(float(p.get("netqty") or 0)) == 0:
                continue
            nq = int(float(p.get("netqty") or 0))
            out.append(dict(exchange=p.get("exchange"), tsym=p.get("tradingsymbol"), token=str(p.get("symboltoken")), name=p.get("symbolname") or p.get("name"),
                            netqty=nq, side="BUY" if nq > 0 else "SELL", avg=float(p.get("avgnetprice") or p.get("buyavgprice" if nq > 0 else "sellavgprice") or 0),
                            ltp=float(p.get("ltp") or 0), pnl=float(p.get("unrealised") or p.get("pnl") or 0), lotsize=int(float(p.get("lotsize") or 1)),
                            expiry=p.get("expirydate"), strike=float(p.get("strikeprice") or 0) or None, opt=p.get("optiontype") or None,
                            itype=p.get("instrumenttype"), product=p.get("producttype")))
        return out

    _mst_lock = __import__("threading").Lock()

    def _master(self):
        """Angel's futures & options contracts, once per day per process. 19 Nov 2026: one load at a time (two threads used to
        load the whole ~40 MB master together on a 400 MB server) and only F&O rows / the fields we use are kept in memory."""
        if getattr(self, "_mst", None) is not None and getattr(self, "_mst_day", None) == date.today():
            return self._mst
        with self._mst_lock:
            if getattr(self, "_mst", None) is None or getattr(self, "_mst_day", None) != date.today():
                self._session()                                # writes today's master to the cache (_load_tokens)
                path = os.path.join(self.cache_dir, f"scrip_master_{date.today()}.json")
                raw = json.load(open(path)) if os.path.exists(path) else requests.get(MASTER_URL, timeout=120).json()
                keep = ("token", "symbol", "name", "expiry", "strike", "lotsize", "instrumenttype", "exch_seg", "tick_size")
                M = [{k: x.get(k) for k in keep} for x in raw if x.get("exch_seg") in ("NFO", "BFO", "MCX")
                     and str(x.get("instrumenttype", ""))[:3] in ("OPT", "FUT")]
                del raw
                import gc
                gc.collect()
                self._mst, self._mst_day = M, date.today()
        return self._mst
        with self._mst_lock:
            if getattr(self, "_mst", None) is None or getattr(self, "_mst_day", None) != date.today():
                path = os.path.join(self.cache_dir, f"scrip_master_{date.today()}.json")
                keep = ("token", "symbol", "name", "expiry", "strike", "lotsize", "instrumenttype", "exch_seg", "tick_size")
                if os.path.exists(path):
                    M = json.load(open(path))
                else:
                    self._session()
                    M = [{k: x.get(k) for k in keep} for x in requests.get(MASTER_URL, timeout=120).json()
                         if x.get("exch_seg") in ("NSE", "NFO", "BSE", "BFO", "MCX")]
                    try:
                        for old in glob.glob(os.path.join(self.cache_dir, "scrip_master_*.json")):
                            os.remove(old)
                        json.dump(M, open(path + ".tmp", "w"), separators=(",", ":")); os.replace(path + ".tmp", path)
                    except Exception:  # noqa: BLE001
                        pass
                self._mst, self._mst_day = M, date.today()
        return self._mst

    def fut_for(self, exchange, name, min_expiry):
        """The futures contract of `name` on `exchange` with the nearest expiry on/after min_expiry (datetime.date)."""
        best = None
        for x in self._master():
            if x.get("exch_seg") == exchange and x.get("name") == name and str(x.get("instrumenttype", "")).startswith("FUT"):
                try:
                    e = datetime.strptime(x["expiry"], "%d%b%Y").date()
                except Exception:  # noqa: BLE001
                    continue
                if e >= min_expiry and (best is None or e < best[0]):
                    best = (e, x["symbol"], str(x["token"]))
        return best

    def fut_info(self, exchange, name, min_expiry):
        """19 Nov 2026 (Turtle MCX): nearest futures contract expiring on/after min_expiry, with Angel's lot size and tick."""
        best = None
        for x in self._master():
            if x.get("exch_seg") == exchange and x.get("name") == name and str(x.get("instrumenttype", "")).startswith("FUT"):
                try:
                    e = datetime.strptime(x["expiry"], "%d%b%Y").date()
                except Exception:  # noqa: BLE001
                    continue
                if e >= min_expiry and (best is None or e < best["expiry"]):
                    best = dict(expiry=e, tsym=x["symbol"], token=str(x["token"]), lotsize=int(float(x.get("lotsize") or 1)),
                                tick=(float(x.get("tick_size") or 5) / 100) or 0.05)
        if best:
            best["expiry"] = str(best["expiry"])
        return best

    def fut_order(self, exchange, tsym, token, side, qty, price, trigger=None, tick=0.05, product="CARRYFORWARD"):
        """Futures order (MCX / NFO), limit or stop-limit (SEBI 2026), DAY validity, carry-forward product."""
        api = self._session()
        rnd = lambda v: round(max(tick, round(v / tick) * tick), 2)  # noqa: E731
        p = dict(variety="STOPLOSS" if trigger else "NORMAL", tradingsymbol=tsym, symboltoken=str(token), transactiontype=side,
                 exchange=exchange, ordertype="STOPLOSS_LIMIT" if trigger else "LIMIT", producttype=product, duration="DAY",
                 price=f"{rnd(price):.2f}", quantity=str(int(qty)))
        if trigger:
            p["triggerprice"] = f"{rnd(trigger):.2f}"
        r = self._call(api.placeOrderFullResponse, p, tries=1) or {}
        d = r.get("data") or {}
        if r.get("status") and d.get("orderid"):
            return str(d["orderid"])
        raise RuntimeError(f"{r.get('message') or 'no order id'} [{r.get('errorcode') or '?'}]")

    def candles_ex(self, exchange, token, days=60):
        """Daily candles for any exchange token: list of (date, o, h, l, c), today's included (the caller decides)."""
        api = self._session(); now = ist_now()
        r = self._call(api.getCandleData, dict(exchange=exchange, symboltoken=str(token), interval="ONE_DAY",
                                                fromdate=(now - timedelta(days=days)).strftime("%Y-%m-%d 09:00"),
                                                todate=now.strftime("%Y-%m-%d %H:%M")), tries=4) or {}
        time.sleep(0.6)
        return [(str(x[0])[:10], float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in (self._data(r) or [])]

    def opt_token(self, name, expiry, strike, typ, exchange="NFO"):
        """token + trading symbol of an option from Angel's scrip master (expiry: date; strike in rupees; typ CE/PE)."""
        exp = expiry.strftime("%d%b%Y").upper()
        for x in self._master():
            if x.get("exch_seg") == exchange and x.get("name") == name and str(x.get("instrumenttype", "")).startswith("OPT") \
                    and str(x.get("expiry", "")).upper() == exp and str(x.get("symbol", "")).endswith(typ) \
                    and abs(float(x.get("strike") or 0) / 100 - float(strike)) < 0.01:
                return str(x["token"]), x["symbol"]
        return None

    def candles_int(self, exchange, token, interval, days):
        """intraday candles (FIVE_MINUTE / FIFTEEN_MINUTE / ONE_HOUR): list of (iso time, o, h, l, c, v)."""
        api = self._session(); now = ist_now()
        r = self._call(api.getCandleData, dict(exchange=exchange, symboltoken=str(token), interval=interval,
                                                fromdate=(now - timedelta(days=days)).strftime("%Y-%m-%d 09:15"),
                                                todate=now.strftime("%Y-%m-%d %H:%M")), tries=4) or {}
        time.sleep(0.4)
        return [(str(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5] if len(x) > 5 else 0)) for x in (self._data(r) or [])]

    def ltp_ex(self, exchange, tsym, token):
        api = self._session()
        d = self._data(self._call(api.ltpData, exchange, tsym, str(token))) or {}
        return float(d.get("ltp") or 0)

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


def _mm():
    """moomoo SDK: `moomoo-api` (import moomoo) or `futu-api` (import futu) - same OpenD protocol."""
    try:
        import moomoo as m  # noqa: F401
    except ImportError:
        import futu as m  # noqa: F401
    return m


class MoomooTrade(MoomooRO):
    """US orders on moomoo through OpenD (14 Nov 2026). MOOMOO_TRADE=1 turns it on. MOOMOO_ENV=SIMULATE (paper, default)
    or REAL (needs MOOMOO_TRADE_PWD in the server's .env to unlock trading). Every call opens and closes its own context."""

    def __init__(self, env: dict):
        super().__init__(env)
        self.trade_on = env.get("MOOMOO_TRADE", "0") == "1"
        self.env_name = "REAL" if env.get("MOOMOO_ENV", "SIMULATE").upper() == "REAL" else "SIMULATE"
        self.pwd = env.get("MOOMOO_TRADE_PWD", ""); self.acc = int(env.get("MOOMOO_US_ACC_ID", "0") or 0)
        self.firm = env.get("MOOMOO_FIRM", "FUTUAU")

    def _q(self):
        m = _mm(); return m, m.OpenQuoteContext(host=self.host, port=self.port)

    def _t(self, mk="US"):
        m = _mm()
        t = m.OpenSecTradeContext(filter_trdmarket=getattr(m.TrdMarket, mk), host=self.host, port=self.port, security_firm=getattr(m.SecurityFirm, self.firm))
        # 28 Nov 2026: OpenD keeps trading unlocked once unlocked, but this unlocked on EVERY call - sending 5 orders (each with its
        # status checks) hit moomoo's "Maximum 10 times per 30 seconds" and ACGL was refused. Now: unlock at most every 10 minutes,
        # and on a rate-limit answer wait and retry instead of failing the order.
        if self.env_name == "REAL" and time.time() - getattr(self, "_unl_at", 0) > 600:
            for wait in (4, 8, 16, 0):
                ret, d = t.unlock_trade(password=self.pwd)
                if ret == m.RET_OK:
                    self._unl_at = time.time(); break
                if "frequency" not in str(d).lower() or not wait:
                    t.close(); raise RuntimeError(f"moomoo unlock failed: {d}")
                time.sleep(wait)
        return m, t, getattr(m.TrdEnv, self.env_name)

    @staticmethod
    def code(sym, mk="US"):
        return f"{mk}." + sym.replace("-", ".")

    def snapshot(self, syms, mk="US"):
        m, q = self._q(); out = {}
        try:
            for i in range(0, len(syms), 380):
                ret, d = q.get_market_snapshot([self.code(s, mk) for s in syms[i:i + 380]])
                if ret != m.RET_OK:
                    raise RuntimeError(f"moomoo snapshot: {d}")
                for r in d.itertuples():
                    out[r.code[3:].replace(".", "-")] = dict(last=float(r.last_price), low=float(r.low_price), high=float(r.high_price), open=float(r.open_price),
                                                             prev=float(r.prev_close_price), ut=str(r.update_time))
        finally:
            q.close()
        return out

    def us_positions(self):
        m, t, env = self._t()
        try:
            ret, d = t.position_list_query(trd_env=env, acc_id=self.acc, refresh_cache=True)
            if ret != m.RET_OK:
                raise RuntimeError(f"moomoo positions: {d}")
            return {r.code[3:].replace(".", "-"): float(r.qty) for r in d.itertuples() if r.code.startswith("US.") and float(r.qty) > 0}
        finally:
            t.close()

    def us_deals(self, days=40):
        """17 Nov 2026: the REAL account's US fills (read only - no unlock, no orders) for the trade journal: list of
        dict(deal_id, sym, side BUY/SELL, qty, price, time 'YYYY-MM-DD HH:MM:SS' New York)."""
        m = _mm()
        t = m.OpenSecTradeContext(filter_trdmarket=m.TrdMarket.US, host=self.host, port=self.port, security_firm=getattr(m.SecurityFirm, self.firm))
        try:
            end = datetime.now(ET_TZ); start = end - timedelta(days=days); out = {}
            ret, d = t.history_deal_list_query(start=start.strftime("%Y-%m-%d %H:%M:%S"), end=end.strftime("%Y-%m-%d %H:%M:%S"),
                                               trd_env=m.TrdEnv.REAL, acc_id=self.acc)
            frames = [d] if ret == m.RET_OK else []
            ret2, d2 = t.deal_list_query(trd_env=m.TrdEnv.REAL, acc_id=self.acc, refresh_cache=True)
            if ret2 == m.RET_OK:
                frames.append(d2)
            if not frames:
                raise RuntimeError(f"moomoo deals: {d}")
            for f in frames:
                for r in f.itertuples():
                    if not str(r.code).startswith("US."):
                        continue
                    out[str(r.deal_id)] = dict(deal_id=str(r.deal_id), sym=str(r.code)[3:].replace(".", "-"), side="SELL" if "SELL" in str(r.trd_side) else "BUY",
                                               qty=float(r.qty), price=float(r.price), time=str(r.create_time)[:19])
            return sorted(out.values(), key=lambda x: x["time"])
        finally:
            t.close()

    def us_cash(self):
        m, t, env = self._t()
        try:
            ret, d = t.accinfo_query(trd_env=env, acc_id=self.acc, refresh_cache=True, currency=m.Currency.USD)
            if ret != m.RET_OK:
                raise RuntimeError(f"moomoo account: {d}")
            r = d.iloc[0]
            for k in ("us_cash", "cash", "power"):
                try:
                    v = float(r[k])
                    if v == v:
                        return v
                except (KeyError, TypeError, ValueError):
                    pass
            return 0.0
        finally:
            t.close()

    def place(self, sym, side, qty, otype, price, aux=None, tif="DAY", mk="US", remark="trenddesk-rsi2", _again=True):
        m, t, env = self._t(mk)
        try:
            ret, d = t.place_order(price=float(price), qty=float(qty), code=self.code(sym, mk), trd_side=getattr(m.TrdSide, side),
                                   order_type=getattr(m.OrderType, otype), trd_env=env, acc_id=self.acc if mk == "US" else 0,
                                   time_in_force=getattr(m.TimeInForce, tif), aux_price=aux, remark=remark)
            if ret != m.RET_OK:
                if _again and "unlock" in str(d).lower():        # OpenD lost the unlock (e.g. restarted): unlock again, once
                    self._unl_at = 0; t.close(); t = None
                    return self.place(sym, side, qty, otype, price, aux=aux, tif=tif, mk=mk, remark=remark, _again=False)
                raise RuntimeError(str(d))
            return str(d["order_id"].iloc[0])
        finally:
            if t is not None:
                t.close()

    def order(self, oid, mk="US"):
        m, t, env = self._t(mk); acc = self.acc if mk == "US" else 0
        try:
            ret, d = t.order_list_query(order_id=oid, trd_env=env, acc_id=acc, refresh_cache=True)
            if ret == m.RET_OK and d.empty:
                ret, d = t.history_order_list_query(trd_env=env, acc_id=acc); d = d[d.order_id == oid] if ret == m.RET_OK else d
            if ret != m.RET_OK or d.empty:
                return dict(status="UNKNOWN", dealt=0.0, avg=0.0)
            r = d.iloc[0]
            return dict(status=str(r.order_status), dealt=float(r.dealt_qty or 0), avg=float(r.dealt_avg_price or 0))
        finally:
            t.close()

    def cancel(self, oid, mk="US"):
        m, t, env = self._t(mk)
        try:
            ret, _ = t.modify_order(m.ModifyOrderOp.CANCEL, oid, 0, 0, trd_env=env, acc_id=self.acc if mk == "US" else 0)
            return ret == m.RET_OK
        finally:
            t.close()

    def modify(self, oid, qty, price, aux=None, mk="US"):
        """27 Nov 2026: move a resting stop in place (no moment without one). Raises when moomoo refuses."""
        m, t, env = self._t(mk)
        try:
            ret, d = t.modify_order(m.ModifyOrderOp.NORMAL, oid, float(qty), float(price), trd_env=env,
                                    acc_id=self.acc if mk == "US" else 0, aux_price=aux)
            if ret != m.RET_OK:
                raise RuntimeError(str(d))
            return True
        finally:
            t.close()

    def orders_today(self, mk="US"):
        """24 Nov 2026: today's orders in this market (manual order ticket): list of dict(id, sym, side, qty, price, aux, type, status, dealt, avg, time)."""
        m, t, env = self._t(mk)
        try:
            ret, d = t.order_list_query(trd_env=env, acc_id=self.acc if mk == "US" else 0, refresh_cache=True)
            if ret != m.RET_OK:
                raise RuntimeError(str(d))
            return [dict(id=str(r.order_id), sym=str(r.code).split(".", 1)[-1], side="SELL" if "SELL" in str(r.trd_side) else "BUY",
                         qty=float(r.qty), price=float(r.price or 0), aux=float(getattr(r, "aux_price", 0) or 0), type=str(r.order_type),
                         status=str(r.order_status), dealt=float(r.dealt_qty or 0), avg=float(r.dealt_avg_price or 0), time=str(r.create_time)[:19])
                    for r in d.itertuples()]
        finally:
            t.close()

    def positions(self, mk="US"):
        m, t, env = self._t(mk)
        try:
            ret, d = t.position_list_query(trd_env=env, acc_id=self.acc if mk == "US" else 0, refresh_cache=True)
            if ret != m.RET_OK:
                raise RuntimeError(str(d))
            return [dict(sym=str(r.code).split(".", 1)[-1], qty=float(r.qty), cost=float(getattr(r, "cost_price", 0) or 0),
                         price=float(getattr(r, "nominal_price", 0) or 0), pnl=float(getattr(r, "pl_val", 0) or 0)) for r in d.itertuples() if float(r.qty) != 0]
        finally:
            t.close()

    def cash(self, mk="US"):
        """24 Nov 2026: cash in the market's currency (USD for US, AUD for AU) - for the moomoo Top Bottom sizing check."""
        m, t, env = self._t(mk)
        try:
            ret, d = t.accinfo_query(trd_env=env, acc_id=self.acc if mk == "US" else 0, refresh_cache=True,
                                     currency=getattr(m.Currency, "USD" if mk == "US" else "AUD"))
            if ret != m.RET_OK:
                raise RuntimeError(f"moomoo account: {d}")
            r = d.iloc[0]
            for k in ("cash", "power"):
                try:
                    v = float(r[k])
                    if v == v:
                        return v
                except (KeyError, TypeError, ValueError):
                    pass
            return 0.0
        finally:
            t.close()


class MockMoomoo:
    """Fake moomoo for tests (MOCK_BROKER=1): fills limit/market orders at once, keeps stop orders open."""

    def __init__(self, *a, **k):
        self.enabled = self.trade_on = True; self.env_name = "SIMULATE"; self.px = {}; self.prev = {}; self.pos = {}; self.orders = {}; self.n = 0

    def account(self):
        return dict(broker="moomoo (mock)", enabled=True, accounts=[])

    def snapshot(self, syms, mk="US"):
        return {s: dict(last=self.px.get(s, 100.0), low=self.px.get(s, 100.0), open=self.px.get(s, 100.0), prev=self.prev.get(s, 100.0),
                        ut=datetime.now(ET_TZ).strftime("%Y-%m-%d %H:%M:%S")) for s in syms}

    def us_positions(self):
        return {k: v for k, v in self.pos.items() if v > 0}

    def us_cash(self):
        return 1e6

    def us_deals(self, days=40):
        return list(getattr(self, "deals", []))

    def place(self, sym, side, qty, otype, price, aux=None, tif="DAY", mk="US", remark=""):
        self.n += 1; oid = f"MM{self.n}"
        if getattr(self, "reject", None) and otype in self.reject:
            raise RuntimeError(f"order type {otype} not supported")
        if otype in ("STOP", "STOP_LIMIT"):
            self.orders[oid] = dict(sym=sym, qty=qty, stop=aux, status="SUBMITTED", dealt=0.0, avg=0.0); return oid
        if side == "SELL" and getattr(self, "lock_by_stop", False) and any(o["sym"] == sym and o["status"] == "SUBMITTED" and o.get("stop") is not None
                                                                         for o in self.orders.values()):
            raise RuntimeError("insufficient sellable quantity")
        px = self.px.get(sym, 100.0); self.pos[sym] = self.pos.get(sym, 0) + (qty if side == "BUY" else -qty)
        self.orders[oid] = dict(sym=sym, qty=qty, status="FILLED_ALL", dealt=float(qty), avg=px); return oid

    def cash(self, mk="US"):
        return 1e6

    def orders_today(self, mk="US"):
        return [dict(id=k, sym=o["sym"], side="BUY", qty=o["qty"], price=0.0, aux=float(o.get("stop") or 0), type="?", status=o["status"],
                     dealt=o["dealt"], avg=o["avg"], time="") for k, o in self.orders.items()]

    def positions(self, mk="US"):
        return [dict(sym=k, qty=float(v), cost=0.0, price=self.px.get(k, 100.0), pnl=0.0) for k, v in self.pos.items() if v]

    def order(self, oid, mk="US"):
        o = self.orders.get(oid) or dict(status="UNKNOWN", dealt=0.0, avg=0.0); return dict(status=o["status"], dealt=o["dealt"], avg=o["avg"])

    def cancel(self, oid, mk="US"):
        if oid in self.orders and self.orders[oid]["status"] == "SUBMITTED":
            self.orders[oid]["status"] = "CANCELLED_ALL"
        return True

    def modify(self, oid, qty, price, aux=None, mk="US"):
        if getattr(self, "refuse_modify", False):
            raise RuntimeError("modify refused")
        self.orders[oid]["stop"] = aux; return True

    def trigger(self, oid, px):
        """test helper: a resting stop fires and fills at px."""
        o = self.orders[oid]; o.update(status="FILLED_ALL", dealt=float(o["qty"]), avg=px); self.pos[o["sym"]] = self.pos.get(o["sym"], 0) - o["qty"]


class MockBroker(AngelEquity):
    """Fake Angel account for tests and the demo mode (MOCK_BROKER=1)."""

    def __init__(self, *a, **k):
        self.placed = []; self.tokens = {}; self.hold = {"RELIANCE": 10}; self.fills = []
        self.nfo = {}

    def nfo_order(self, tsym, token, side, qty, price, trigger=None, tick=0.05):
        oid = f"N{len(self.nfo) + 1}"
        self.nfo[oid] = dict(id=oid, symbol=tsym, side=side, qty=qty, price=price, trigger=trigger, status="open", avg=0.0, filled=0)
        return oid

    def cancel_order(self, oid, variety="NORMAL"):
        if oid in self.nfo:
            self.nfo[oid]["status"] = "cancelled"
        return {"status": True}

    def order_map(self):
        return dict(self.nfo)

    def account(self):
        H = [dict(symbol=s, qty=q, avg=100.0, ltp=100.0, pnl=0.0) for s, q in self.hold.items() if q > 0]
        return dict(broker="Angel One (mock)", cash=800000.0, net=2000000.0, holdings=H, positions=[], holdings_value=sum(h["qty"] * 100 for h in H))

    def ltp(self, symbol):
        return 100.0

    def trades(self):
        return list(self.fills)

    def fo_positions(self):
        if hasattr(self, "fo"):
            return list(self.fo)
        net = {}                                             # 26 Nov 2026: net option quantity from the filled fake NFO orders
        for o in getattr(self, "nfo", {}).values():
            if o["status"] == "complete":
                net[o["symbol"]] = net.get(o["symbol"], 0) + (o["qty"] if o["side"] == "BUY" else -o["qty"])
        return [dict(exchange="NFO", tsym=k, netqty=v) for k, v in net.items() if v]

    def fut_for(self, exchange, name, min_expiry):
        return getattr(self, "fut", None)

    def fut_info(self, exchange, name, min_expiry):
        return getattr(self, "futinfo", None)

    def fut_order(self, exchange, tsym, token, side, qty, price, trigger=None, tick=0.05, product="CARRYFORWARD"):
        oid = f"F{len(getattr(self, 'nfo', {})) + 1}"
        self.nfo[oid] = dict(id=oid, symbol=tsym, side=side, qty=qty, price=price, trigger=trigger, status="open", avg=0.0, filled=0, exchange=exchange)
        return oid

    def candles_ex(self, exchange, token, days=60):
        return list(getattr(self, "fcandles", []))

    def ltp_ex(self, exchange, tsym, token):
        return getattr(self, "fltp", {}).get(tsym, 0.0)

    def opt_token(self, name, expiry, strike, typ, exchange="NFO"):
        return ("77", f"{name}{expiry:%d%b%y}{int(strike)}{typ}".upper())

    def candles_int(self, exchange, token, interval, days):
        return list(getattr(self, "icandles", []))

    def fo_quotes(self, exchange, tokens):
        return {str(t): dict(v) for t, v in getattr(self, "fq", {}).items() if str(t) in {str(x) for x in tokens}}

    def quotes(self, symbols):
        return {s: dict(ltp=100.0 + i, prev=99.0 + i, high=101.0 + i, low=98.0 + i, open=99.5 + i) for i, s in enumerate(symbols)}

    def index_quotes(self):
        return {"Nifty 50": dict(ltp=25000.0, prev=24900.0, high=25050.0, low=24880.0, open=24910.0, t=None)}

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

    def gtt_oco(self, symbol, qty, target, stop, stop_limit):
        self.gtts = getattr(self, "gtts", {}); gid = f"GTTO{len(self.gtts) + 1}"
        self.gtts[gid] = dict(symbol=symbol, qty=qty, target=round(target, 2), trigger=round(stop, 2), price=round(stop_limit, 2), oco=True, active=True)
        return gid, self.gtts[gid]

    def gtt_buy(self, symbol, qty, trigger, limit):
        self.gtts = getattr(self, "gtts", {}); gid = f"GTTB{len(self.gtts) + 1}"
        self.gtts[gid] = dict(symbol=symbol, qty=qty, trigger=round(trigger, 2), price=round(limit, 2), side="BUY", active=True)
        return gid, self.gtts[gid]

    def gtt_modify(self, rule_id, symbol, qty, trigger, limit):
        self.gtts[rule_id].update(trigger=round(trigger, 2), price=round(limit, 2)); return rule_id, self.gtts[rule_id]

    def daily_candles(self, symbol, days=420):
        # steady uptrend 50 -> ~150 over 300 sessions (weekdays), so the averages rise under the price
        out, d, px = [], date(2025, 8, 1), 50.0
        while len(out) < 300:
            if d.weekday() < 5:
                px *= 1.0037; out.append((d.isoformat(), px * 0.995, px * 1.01, px * 0.99, px))
            d += timedelta(days=1)
        return out
