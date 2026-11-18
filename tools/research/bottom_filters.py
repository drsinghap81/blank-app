"""Bottom-pattern breakouts with trend / RSI filters (18 Nov 2026, Amritpal: "failed as price was below the moving average and
RSI below 60 - check").

Patterns exactly as tools/pattern_scan.py (zigzag 6% on closes, double bottom / tilted W / triple bottom / inverse H&S after a
20%+ fall, breakout = first close above the neckline within 60 days of the last low). Nifty 500 (current list), 2016 - Oct 2026,
Yahoo daily (adjusted). Each breakout: buy next open. Outcomes:
  classic : target = neckline + height (a high reaches it) vs SL = a close 4% under the neckline (6% IHS), whichever first,
            else the close 120 days later
  fixed   : return 20 / 60 / 120 days after the next open
Filters at the breakout close: above the 50-day SMA / 200-day SMA, RSI(14) > 60, and combinations.
Output: data/research/bottom_filters.json"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pattern_scan as PS  # noqa: E402


def events(sym, x):
    c = x.Close.to_numpy(float); h = x.High.to_numpy(float); o = x.Open.to_numpy(float); n = len(c); dts = x.index
    if n < 300:
        return []
    piv = PS.zigzag(c, PS.THR)
    rmax = pd.Series(c).rolling(250, min_periods=120).max().shift(1).to_numpy()
    rmin = pd.Series(c).rolling(250, min_periods=120).min().to_numpy()
    s50 = pd.Series(c).rolling(50).mean().to_numpy(); s200 = pd.Series(c).rolling(200).mean().to_numpy(); rv = PS.rsi(c)
    out, seen = [], set()
    for k in range(len(piv)):
        if piv[k][0] != "L":
            continue
        for typ, lows, peaks, neck in PS.patterns_at(piv, k):
            first = lows[0]; i1 = first[1]
            if np.isnan(rmax[i1]) or rmax[i1] < first[2] * (1 + PS.FALL) or first[2] > rmin[i1] * 1.05:
                continue
            last = lows[-1]; sig = None
            for j in range(last[3], min(n, last[1] + 60)):
                if c[j] < last[2]:
                    break
                if c[j] > neck:
                    sig = j; break
            if sig is None or sig + 1 >= n or sig in seen or c[sig] < 100:
                continue
            seen.add(sig)
            low0 = min(l_[2] for l_ in lows); tgt = neck + (neck - low0); sl = neck * (0.94 if typ == "IHS" else 0.96)
            e0 = o[sig + 1]; res, why = None, "time"
            for j in range(sig + 1, min(n, sig + 121)):
                if c[j] < sl:
                    res, why = c[j] / e0 - 1, "sl"; break
                if h[j] >= tgt:
                    res, why = max(tgt, o[j]) / e0 - 1, "target"; break
            if res is None:
                jj = min(n - 1, sig + 120); res = c[jj] / e0 - 1
            fw = {f"r{d}": (c[sig + d] / e0 - 1) * 100 if sig + d < n else np.nan for d in (20, 60, 120)}
            out.append(dict(sym=sym, d=dts[sig], typ=typ, classic=res * 100, why=why, above50=bool(c[sig] > s50[sig]), above200=bool(c[sig] > s200[sig]),
                            rsi=float(rv[sig]), rsi60=bool(rv[sig] > 60), s50_rising=bool(s50[sig] > s50[sig - 10]), **fw))
    return out


def main():
    syms = pd.read_csv("data/universe/nifty500.csv").Symbol.tolist(); ev = []; CT = []
    for a in range(0, len(syms), 60):
        b = [s + ".NS" for s in syms[a:a + 60]]
        D = yf.download(b, start="2015-01-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in b:
            try:
                x = D[t].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            ev += events(t[:-3], x)
            c_, o_ = x.Close.to_numpy(float), x.Open.to_numpy(float)
            for j in range(250, len(x) - 1, 20):                       # control: every 20th day of the same stocks
                if x.index[j] >= pd.Timestamp("2016-01-01") and c_[j] >= 100:
                    CT.append({f"r{d}": (c_[j + d] / o_[j + 1] - 1) * 100 if j + d < len(x) else np.nan for d in (20, 60, 120)})
        print("done", a + 60, len(ev), flush=True)
    E = pd.DataFrame(ev); E = E[E.d >= "2016-01-01"]

    def summ(Z):
        if len(Z) < 20:
            return dict(n=len(Z))
        r = Z.classic
        o = dict(n=len(Z), classic_avg=round(r.mean(), 2), win=round((r > 0).mean() * 100, 1), t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2),
                 target_hit=round((Z.why == "target").mean() * 100, 1), sl_hit=round((Z.why == "sl").mean() * 100, 1))
        for d in (20, 60, 120):
            o[f"r{d}"] = round(Z[f"r{d}"].mean(), 2)
        return o
    F = {"all": E.index == E.index, "above 50d": E.above50, "below 50d": ~E.above50, "above 200d": E.above200, "below 200d": ~E.above200,
         "RSI > 60": E.rsi60, "RSI <= 60": ~E.rsi60, "above 50d & RSI > 60": E.above50 & E.rsi60, "below 50d & RSI <= 60": ~E.above50 & ~E.rsi60,
         "above 200d & RSI > 60": E.above200 & E.rsi60, "above 50d & 200d & RSI > 60": E.above50 & E.above200 & E.rsi60,
         "below 200d & RSI <= 60": ~E.above200 & ~E.rsi60, "50d rising & RSI > 60": E.s50_rising & E.rsi60}
    res = dict(method=__doc__, control={f"r{d}": round(pd.DataFrame(CT)[f"r{d}"].mean(), 2) for d in (20, 60, 120)},
               groups={k: summ(E[m]) for k, m in F.items()})
    best = E[E.above50 & E.rsi60]
    res["above 50d & RSI > 60, classic by year"] = best.groupby(best.d.dt.year).classic.mean().round(2).to_dict()
    res["all, classic by year"] = E.groupby(E.d.dt.year).classic.mean().round(2).to_dict()
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/bottom_filters.json", "w"), indent=1, default=str)
    print("control", res["control"])
    for k, v in res["groups"].items():
        print(k, v, flush=True)


if __name__ == "__main__":
    main()
