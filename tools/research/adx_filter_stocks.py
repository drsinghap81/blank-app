"""ADX (14,14) + DI histogram as a filter on the live Cup 9/21 and Momentum entries, NSE stocks (25 Nov 2026, Amritpal: "does ADX add
value" -> "Yes" to a stock test after the Nifty pilot showed no edge on the index).
Entries = live rules (ath_confirm_test: Cup B wick close, Momentum C close confirm; next-day buy-stop). Indicator read at the signal
day's close (the session before the fill). Filters: all | ADX > 20 and histogram green | ADX > 25 and green | green only |
ADX rising | ADX > 20 rising and green | ADX < 20 (trendless) | ADX > 40 (stretched). Per trade, newest-first years, bull/bear,
10-slot CAGR / max DD. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import yfinance as yf  # noqa: E402


def adx(x, n=14):
    h, l, c = x.H, x.L, x.C
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=x.index); mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=x.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    r = lambda s: s.ewm(alpha=1 / n, adjust=False).mean()  # noqa: E731
    atr = r(tr); pdi = 100 * r(pdm) / atr; mdi = 100 * r(mdm) / atr
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0)
    return pdi - mdi, r(dx)


def main():
    nif = yf.download(AC.BENCH, start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load(); T = []
    for s, x in P.items():
        try:
            tt = AC.trades_for(s, x, reg)
            if not tt:
                continue
            hist, a = adx(x); rise = a > a.shift()
            for t in tt:
                i = x.index.searchsorted(t["d"]) - 1
                t.update(h=hist.iloc[i], a=a.iloc[i], up=bool(rise.iloc[i]))
            T += tt
        except Exception as e:  # noqa: BLE001
            print("err", s, e)
    T = pd.DataFrame(T); T = T[(T.d >= "2007-01-01") & (((T.sys == "tf") & (T.v == "B")) | ((T.sys == "mom") & (T.v == "C")))].copy()
    print(f"R| {len(P)} stocks, {len(T)} live-rule trades; ADX at signal: median {T.a.median():.0f}, green {(T.h > 0).mean() * 100:.0f}%, rising {T.up.mean() * 100:.0f}%", flush=True)
    F = {"all (live rules)": T.index == T.index, "ADX > 20 and green": (T.a > 20) & (T.h > 0), "ADX > 25 and green": (T.a > 25) & (T.h > 0),
         "green only": T.h > 0, "ADX rising": T.up, "ADX > 20, rising, green": (T.a > 20) & T.up & (T.h > 0),
         "ADX < 20 (trendless base)": T.a < 20, "ADX > 40 (stretched)": T.a > 40}
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 15:
                print(f"R| {nm:28s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; cg, dd = AC.port(X)
            print(f"R| {nm:28s} n {len(X):4d} ({len(X) / max((T.sys == sysk).sum(), 1) * 100:3.0f}%) | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | "
                  f"2021-26 {xb.ret.mean() * 100:+6.2f}% | bull {X[X.bull].ret.mean() * 100:+.2f}% bear {X[~X.bull].ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        X = T[T.sys == sysk]
        y = X.groupby(X.d.dt.year).apply(lambda g: f"all {g.ret.mean() * 100:+.1f}% / ADX>20+green {g[(g.a > 20) & (g.h > 0)].ret.mean() * 100:+.1f}%")
        print("R| by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:8]), flush=True)


if __name__ == "__main__":
    main()
