"""9/21 with the 'EMA 50 rising' rule relaxed (19 Nov 2026, Amritpal; the rule that kept VOLTAS, IREDA, MARUTI, PGEL,
ADVENZYMES, IDFCFIRSTB out on 19 Nov). Same engine and data as the live 9/21 tests (NSE, Yahoo 2016 -> today, survivors).
  V0 live: EMA 50 above its value 10 sessions earlier
  V1 EMA 50 flat or rising (no more than 0.5% below its value 10 sessions earlier)
  V2 no EMA 50 slope rule (close above EMA 50 still required)
  V3 V1 + RSI >= 50 instead of 55
Output: data/research/n921_relax.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402
from trend_bt_global import features, stats, supertrend_dir  # noqa: E402
import concentrated_921 as C  # noqa: E402


def variants(o, h, l, c, v, minval=1e7):
    x = pd.DataFrame({"OPEN": o, "HIGH": h, "LOW": l, "CLOSE": c}).dropna(); x = x[(x.CLOSE > 0) & (x.OPEN > 0)]
    val = (x.CLOSE * v.reindex(x.index).fillna(0)).rolling(20).mean(); cc = x.CLOSE
    e9, e21, e50 = (cc.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    d = cc.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn); st = supertrend_dir(x.HIGH.values, x.LOW.values, cc.values)
    hi = cc.rolling(250, min_periods=60).max(); n = np.arange(len(x))
    base = (e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (st == 1) & (cc > e50) & (val >= minval) & (n >= 120) & (cc >= 0.7 * hi)
    return pd.DataFrame({"V0": base & (e50 > e50.shift(10)) & (rsi >= 55), "V1": base & (e50 >= 0.995 * e50.shift(10)) & (rsi >= 55),
                         "V2": base & (rsi >= 55), "V3": base & (e50 >= 0.995 * e50.shift(10)) & (rsi >= 50)}, index=x.index)


def main():
    u = symbols("NSE"); tick = list(u.ticker); F = []
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]; D = None
        for _ in range(3):
            try:
                D = yf.download(ch, start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if D is None or D.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({k: D[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                f = features(t, x.Open, x.High, x.Low, x.Close, x.Volume, 1e7)
                if f is None:
                    continue
                vv = variants(x.Open, x.High, x.Low, x.Close, x.Volume).reindex(pd.to_datetime(f.Date.values)); vv.index = f.index
                F.append(pd.concat([f, vv.fillna(False).astype(bool)], axis=1))
            except Exception:  # noqa: BLE001
                continue
        print("downloaded", i + 200, len(F), flush=True); time.sleep(2)
    d = pd.concat(F, ignore_index=True).sort_values(["SYMBOL", "Date"]); g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max()); d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    res = dict(method=__doc__, check_V0_equals_live=bool((d.V0 == d.sig).mean() > 0.999))
    for vn in ("V0", "V1", "V2", "V3"):
        for label, (mp, rank) in (("10 positions, 3-month strength", (10, "r63")), ("5 positions, 3-month strength", (5, "r63")), ("10 positions, random", (10, "random"))):
            z = d.copy(); z["sig"] = z[vn]
            eq, T = C.run(z, mp, 0.01, rank, 0)
            a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
            k = f"{vn} | {label}"
            res[k] = dict(signals=int(z.sig.sum()), cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"],
                          trades=len(T), win=round(float((T.pnl > 0).mean() * 100)) if len(T) else None, avg=round(float(T.ret.mean() * 100), 2) if len(T) else None)
            print("R|", k, res[k], flush=True)
    print("R| V0 matches live signal:", res["check_V0_equals_live"])
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/n921_relax.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
