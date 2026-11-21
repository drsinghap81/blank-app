"""9/21 trend system on ETFs (22 Nov 2026, Amritpal: "also add ETF to the 9/21 system and check").

Same rules and engine as the live India 9/21 (tools/trend_bt_global.features signal: EMA9 crosses above EMA21, Supertrend green,
close > rising EMA50, RSI >= 55, within 30% of the 52-week high, liquid; tools/research/concentrated_921.run: next-open entry,
5-day-low stop <= 12% away, Supertrend exit, 10 positions, 1% risk, 3-month-strength ranking), RED-light buys skipped.
Universe: the app's ETF list (data/scan/funds.json, kind 'etf', leveraged / inverse dropped) - India (NSE) and US.
Runs, Jun 2016 -> today:
  India ETFs alone | India stocks alone (the live system) | India stocks + ETFs in one pool
  US ETFs alone (US costs and US traffic light)
Reports CAGR / max DD, newest-first windows, years, bull / bear, ex-Covid, trades, average trade, win.
PILOT env = India + 40 US ETFs, no stock runs, no RED gate. Output data/research/etf_921_test.json"""
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import features, load  # noqa: E402
from global_universe import MARKETS  # noqa: E402
import concentrated_921 as K  # noqa: E402
from holy_grail import report  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
LEV = re.compile(r"ultra|short|bear|inverse|2x|3x|-1x|leverag|daily|vix|volatil", re.I)
BENCH = {"NSE": "^NSEI", "US": "^GSPC"}


def etfs(mk):
    F = json.load(open("data/scan/funds.json"))["rows"]
    fm = {"NSE": "IN", "US": "US"}[mk]
    t = sorted({(r["key"].split(":", 1)[-1] + (".NS" if mk == "NSE" else "")) for r in F
                if r.get("market") == fm and r.get("kind") == "etf" and not LEV.search(r.get("name", ""))})
    return t[:40] if PILOT and mk == "US" else t


def panel(tickers, mk):
    minval = MARKETS[mk]["min_value"]; out = []
    for a in range(0, len(tickers), 80):
        ch = tickers[a:a + 80]; d = None
        for _ in range(3):
            try:
                d = yf.download(ch, start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                f = features(t, d["Open"][t], d["High"][t], d["Low"][t], d["Close"][t], d["Volume"][t], minval)
            except Exception:  # noqa: BLE001
                f = None
            if f is not None:
                out.append(f)
        time.sleep(2)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def bull_of(mk):
    b = yf.download(BENCH[mk], start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    b.index = pd.to_datetime(b.index).tz_localize(None)
    return b > b.rolling(200).mean()


def light(d, mk):
    """RED = 10-session 9/21 breadth negative (the market's stocks) AND benchmark weekly close below its 30-week SMA"""
    from signal_breadth import breadth
    B = breadth(d)
    b = yf.download(BENCH[mk], start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    b.index = pd.to_datetime(b.index).tz_localize(None)
    w = b.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = (w < w.rolling(30).mean())
    idx_bad = below.reindex(B.index, method="ffill").shift(1).fillna(False).astype(bool)
    return set(B.index[B.W1.fillna(False).astype(bool) & idx_bad])


def go(name, d, mk, red, bull, res):
    if not len(d):
        print("R|", name, "no data", flush=True); return
    d = d.sort_values(["SYMBOL", "Date"]).copy()
    d["r63"] = d.groupby("SYMBOL").CLOSE.transform(lambda s: s / s.shift(63) - 1)
    if red:
        d.loc[d.Date.isin(red), "sig"] = False
    K.CFG = MARKETS[mk]
    eq, T = K.run(d, 10, 0.01, "r63", 0)
    rp = report(eq, bull)
    st = dict(symbols=int(d.SYMBOL.nunique()), signals=int(d.sig.sum()), trades=len(T),
              avg=round(float(T.ret.mean() * 100), 2) if len(T) else None, win=round(float((T.ret > 0).mean() * 100), 1) if len(T) else None,
              etf_trades=int(T.sym.isin(set(d.SYMBOL[d.is_etf.astype(bool)])).sum()) if len(T) and "is_etf" in d.columns else None)
    res[name] = dict(stats=st, port={k: rp[k] for k in ("CAGR", "max DD", "1y", "2y", "3y", "5y", "years", "bull/bear a year", "ex-Covid")})
    print(f"R| {name}: {st} | CAGR {rp['CAGR']} DD {rp['max DD']} | 1y {rp['1y']} 2y {rp['2y']} 3y {rp['3y']} 5y {rp['5y']} | years {rp['years']} | bull/bear {rp['bull/bear a year']} | ex-Covid {rp['ex-Covid']}", flush=True)


def main():
    res = dict(method=__doc__)
    # India
    E = panel(etfs("NSE"), "NSE"); E["is_etf"] = True
    print("R| India ETFs liquid", E.SYMBOL.nunique() if len(E) else 0, flush=True)
    bull = bull_of("NSE")
    if PILOT:
        go("India ETFs (no RED gate)", E, "NSE", set(), bull, res)
    else:
        S, _ = load("NSE"); S["is_etf"] = False
        red = light(S, "NSE")
        go("India ETFs", E, "NSE", red, bull, res)
        go("India stocks (live 9/21)", S, "NSE", red, bull, res)
        go("India stocks + ETFs", pd.concat([S, E], ignore_index=True), "NSE", red, bull, res)
        del S
    # US
    U = panel(etfs("US"), "US"); U["is_etf"] = True
    print("R| US ETFs liquid", U.SYMBOL.nunique() if len(U) else 0, flush=True)
    bu = bull_of("US")
    if PILOT:
        go("US ETFs (no RED gate)", U, "US", set(), bu, res)
    else:
        SU, _ = load("US"); red_us = light(SU, "US"); del SU
        go("US ETFs", U, "US", red_us, bu, res)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/etf_921_test.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
