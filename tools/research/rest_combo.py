"""9/21 + the 40-week rest breakout as two pots of money (19 Nov 2026, Amritpal: "yes" - test them together).

Systems (same data as rest_breakout_40w.py: NSE stocks from Yahoo 2016 -> today, survivors):
  9/21  : the live rules, 10 positions, 1% risk, 3-month strength (tools/research/concentrated_921.py)
  REST6 : 40-week rest of 6 weeks + weekly-close trendline break, stop at the rest low, no target, exit on a weekly close below
          the 40-week SMA, 10 positions, 1% risk (tools/research/rest_breakout_40w.py, mode C); REST6V = with volume drying
Mix: each system runs in its own pot; pots are set back to the target split at every month-end (weights 100/0 ... 50/50) and
also left alone (no rebalance). Also: monthly return correlation, and how many REST trades started while 9/21 already held the
same stock. Output: data/research/rest_combo.json"""
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
from trend_bt_global import features, stats  # noqa: E402
import concentrated_921 as C  # noqa: E402
import rest_breakout_40w as R  # noqa: E402


def mix(a, b, wa, rebalance=True):
    """two equity curves (same weekly dates) -> combined curve with wa in a, 1-wa in b"""
    ra, rb = a.pct_change().fillna(0), b.pct_change().fillna(0)
    va, vb, out = wa, 1 - wa, []
    for i, d in enumerate(a.index):
        va *= 1 + ra.iloc[i]; vb *= 1 + rb.iloc[i]; out.append(va + vb)
        if rebalance and i + 1 < len(a.index) and a.index[i + 1].month != d.month:
            t = va + vb; va, vb = t * wa, t * (1 - wa)
    return pd.Series(out, index=a.index)


def main():
    u = symbols("NSE"); tick = list(u.ticker); W, F = {}, []
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]; D = None
        for _ in range(3):
            try:
                D = yf.download(ch, start="2014-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if D is None or D.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({k: D[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x = x[(x.Close > 0) & (x.Open > 0)]
                if len(x) < 400:
                    continue
                w = R.weekly(x); w["ma"] = w.C.rolling(40).mean(); w["r63"] = w.C / w.C.shift(13) - 1; W[t] = w
                f = features(t, x.Open, x.High, x.Low, x.Close, x.Volume, 1e7)
                if f is not None:
                    F.append(f)
            except Exception:  # noqa: BLE001
                continue
        print("downloaded", i + 200, len(W), flush=True); time.sleep(2)
    d = pd.concat(F, ignore_index=True).sort_values(["SYMBOL", "Date"]); g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max()); d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    e921, T921 = C.run(d, 10, 0.01, "r63", 0)
    e921w = e921.resample("W-FRI").last().dropna()
    res = dict(method=__doc__)
    for name, vol in (("REST6", False), ("REST6V", True)):
        S = {}
        for sym, w in W.items():
            for t, stop, tgt in R.setups(sym, w, 6, vol):
                if t + 1 < len(w):
                    S.setdefault(w.index[t], []).append((sym, stop, tgt, float(w.r63.iloc[t]) if np.isfinite(w.r63.iloc[t]) else -9))
        er, TR = R.run(W, S, "C", 0)
        idx = e921w.index.intersection(er.index)
        a, b = e921w.reindex(idx).ffill(), er.reindex(idx).ffill()
        ma, mb = a.resample("ME").last().pct_change().dropna(), b.resample("ME").last().pct_change().dropna()
        same = 0
        for _, r in TR.iterrows():
            h = T921[(T921.sym == r.sym) & (pd.to_datetime(T921.entry) <= pd.Timestamp(r.entry)) & (pd.to_datetime(T921.exit) >= pd.Timestamp(r.entry))]
            same += len(h) > 0
        res[name] = dict(trades=len(TR), monthly_corr_with_921=round(float(ma.corr(mb)), 2),
                         started_while_921_held_same_stock=f"{same} of {len(TR)} ({round(same / max(1, len(TR)) * 100)}%)")
        print("R|", name, res[name], flush=True)
        for wa in (1.0, 0.8, 0.7, 0.6, 0.5, 0.0):
            for reb in (True, False):
                if wa in (1.0, 0.0) and not reb:
                    continue
                m = mix(a, b, wa, reb)
                x, y, z = stats(m, "2017-01-01", "2030-01-01"), stats(m, "2017-01-01", "2021-12-31"), stats(m, "2022-01-01", "2030-01-01")
                k = f"{name} | 9/21 {int(wa * 100)}% / REST {int(round((1 - wa) * 100))}%{'' if reb else ' (no rebalance)'}"
                yrs = {str(k2.year): round(v * 100, 1) for k2, v in m.resample("YE").last().pct_change().dropna().items()}
                res[k] = dict(cagr=x["cagr"], maxdd=x["maxdd"], cagr_17_21=y["cagr"], cagr_22_26=z["cagr"], dd_22_26=z["maxdd"],
                              losing_years=sum(v < 0 for v in yrs.values()), years=yrs)
                print("R|", k, {q: res[k][q] for q in ("cagr", "maxdd", "cagr_17_21", "cagr_22_26", "dd_22_26", "losing_years")}, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rest_combo.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
