"""9/21: does the "50-day EMA rising (vs 10 sessions ago)" rule help? (22 Nov 2026, Amritpal: Data Patterns crossed 9/21 on 13 Nov
but its 50-day EMA was falling -> "if we release the 50 rising condition will it impact backtested results")
Same engine and rules as the live system (tools/research/concentrated_921.run: buy next open, 5-day-low stop <= 12%, Supertrend
exit, 10 positions, 1% risk, 3-month-strength ranking) with the adopted RED gate (no new buys on RED days). Variants:
  live      : 9/21 cross + Supertrend green + close > EMA50 + EMA50 rising + RSI >= 55 + within 30% of the 52-week high
  no_rise   : same without "EMA50 rising"
  no_50     : without both 50-day rules (close > EMA50 and rising)
Reports CAGR / max DD, newest-first windows, years, bull/bear, ex-Covid, trades, average trade, win rate.
PILOT env = 400 stocks. Output data/research/e50_rising_test.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402
import concentrated_921 as K  # noqa: E402
import light_distribution as LD  # noqa: E402
from holy_grail import report  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def main():
    d, _ = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:400]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"])
    d["r63"] = d.groupby("SYMBOL").CLOSE.transform(lambda s: s / s.shift(63) - 1)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    L = LD.light_series(d); red = set(L.index[L == "RED"])
    res = dict(method=__doc__)
    for nm, col in (("live", "sig"), ("no_rise", "sig_ne50"), ("no_50", "sig_no50")):
        x = d.copy(); x["sig"] = x[col].astype(bool); x.loc[x.Date.isin(red), "sig"] = False
        eq, T = K.run(x, 10, 0.01, "r63", 0)
        rp = report(eq, bull)
        st = dict(signals=int(x.sig.sum()), trades=len(T), avg=round(float(T.ret.mean() * 100), 2) if len(T) else None,
                  win=round(float((T.ret > 0).mean() * 100), 1) if len(T) else None)
        res[nm] = dict(stats=st, port={k: rp[k] for k in ("CAGR", "max DD", "1y", "2y", "3y", "5y", "years", "bull/bear a year", "ex-Covid")})
        print(f"R| {nm}: {st} | CAGR {rp['CAGR']} DD {rp['max DD']} | 1y {rp['1y']} 2y {rp['2y']} 3y {rp['3y']} 5y {rp['5y']} | years {rp['years']} | bull/bear {rp['bull/bear a year']} | ex-Covid {rp['ex-Covid']}", flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/e50_rising_test.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
