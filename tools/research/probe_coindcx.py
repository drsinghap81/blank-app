"""Probe CoinDCX public futures data (29 Nov 2026, before the BTC/ETH Top Bottom paper bot on the server).
Checks: daily candle boundaries (UTC?), history depth, closes vs Yahoo, live price endpoints, INR-margined instruments, fees/increments."""
import json
import time
from datetime import datetime, timezone

import requests
import yfinance as yf

H = {"User-Agent": "Mozilla/5.0"}


def get(url, **p):
    try:
        r = requests.get(url, params=p, headers=H, timeout=20)
        return r.status_code, r.text
    except Exception as ex:  # noqa: BLE001
        return -1, str(ex)


def candles(pair, res, days):
    now = int(time.time())
    s, t = get("https://public.coindcx.com/market_data/candlesticks", pair=pair, **{"from": now - days * 86400, "to": now}, resolution=res, pcode="f")
    try:
        d = json.loads(t)
    except Exception:  # noqa: BLE001
        print(f"R| candles {pair} {res} status {s} body {t[:200]}"); return []
    rows = d.get("data") or []
    print(f"R| candles {pair} {res} {days}d: status {s} s={d.get('s')} n={len(rows)} keys={list(rows[0].keys()) if rows else None}")
    return rows


for pair in ("B-BTC_USDT", "B-ETH_USDT"):
    rows = candles(pair, "1D", 40)
    rows = sorted(rows, key=lambda r: r["time"])
    for r in rows[-4:]:
        ts = r["time"] / (1000 if r["time"] > 1e11 else 1)
        print(f"R|   {pair} {datetime.fromtimestamp(ts, timezone.utc):%Y-%m-%d %H:%M}Z o{r['open']} h{r['high']} l{r['low']} c{r['close']}")
    y = yf.download(pair[2:5] + "-USD", period="10d", interval="1d", progress=False, auto_adjust=False)
    y.columns = [c[0] if isinstance(c, tuple) else c for c in y.columns]
    print("R|   yahoo closes:", [(str(i.date()), round(float(v), 1)) for i, v in y.Close.tail(4).items()])
    for days in (400, 1200, 2000):
        rr = candles(pair, "1D", days)
        if rr:
            t0 = min(r["time"] for r in rr); t0 = t0 / (1000 if t0 > 1e11 else 1)
            print(f"R|   earliest {datetime.fromtimestamp(t0, timezone.utc):%Y-%m-%d}")
    rows = candles(pair, "1", 1)
    if rows:
        r = max(rows, key=lambda r: r["time"]); ts = r["time"] / (1000 if r["time"] > 1e11 else 1)
        print(f"R|   last 1m {datetime.fromtimestamp(ts, timezone.utc):%H:%M}Z c{r['close']}  now {datetime.now(timezone.utc):%H:%M}Z")
    s, t = get("https://api.coindcx.com/exchange/v1/derivatives/futures/data/trades", pair=pair)
    print(f"R| trades {pair} status {s}: {t[:200]}")

for url in ("https://public.coindcx.com/market_data/v3/current_prices/futures/rt", "https://public.coindcx.com/market_data/current_prices/futures/rt"):
    s, t = get(url)
    try:
        d = json.loads(t); pr = d.get("prices") or d
        print(f"R| rt {url} status {s} keys {list(d.keys())[:5]} BTC {json.dumps((pr or {}).get('B-BTC_USDT'))[:300]}")
    except Exception:  # noqa: BLE001
        print(f"R| rt {url} status {s} body {t[:150]}")

for m in ("INR", "USDT"):
    s, t = get("https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments", **{"margin_currency_short_name[]": m})
    try:
        L = json.loads(t); print(f"R| active {m}: status {s} n={len(L)} btc/eth: {[x for x in L if x in ('B-BTC_USDT', 'B-ETH_USDT')]}")
    except Exception:  # noqa: BLE001
        print(f"R| active {m}: status {s} {t[:150]}")
    for pair in ("B-BTC_USDT", "B-ETH_USDT"):
        s, t = get("https://api.coindcx.com/exchange/v1/derivatives/futures/data/instrument", pair=pair, margin_currency_short_name=m)
        try:
            i = json.loads(t)["instrument"]
            print(f"R| inst {pair} {m}: " + json.dumps({k: i.get(k) for k in ("status", "price_increment", "quantity_increment", "min_quantity", "min_notional",
                                                                              "maker_fee", "taker_fee", "max_leverage_long", "order_types", "margin_currency_short_name")}))
        except Exception:  # noqa: BLE001
            print(f"R| inst {pair} {m}: status {s} {t[:150]}")
s, t = get("https://api.coindcx.com/api/v1/derivatives/futures/data/conversions")
print(f"R| conversions status {s}: {t[:300]}")
