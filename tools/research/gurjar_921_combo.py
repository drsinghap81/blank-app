"""9/21 entries filtered by the Chartink 'bullish momentum' scanner + tight range + volume (19 Nov 2026, Amritpal).

Same data/engine as tools/research/gurjar_momentum.py (NSE stocks from Yahoo 2016 -> today, survivors; buy next open,
stop = 5-day low, 1% risk, Supertrend(10,3) exit, costs 0.25% + 0.15% slippage a side). A 9/21 signal is taken only when:
  F1  the scanner passed the same day
  F2  the scanner passed on any of the last 5 sessions
  F3  the last 10 sessions were a tight range (<= 12%) with volume below the 50-day average (the base), no breakout needed
  F4  F3 + the signal day's volume >= 1.5x the 20-day average
  F5  F3 with the range <= 8%
  F6  a tight-range high-volume breakout (the variant) happened on any of the last 10 sessions
  F7  F2 + F3
Reference: plain 9/21. Output: data/research/gurjar_921_combo.json"""
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
from gurjar_momentum import extra as extra0  # noqa: E402


def extra(x):
    e = extra0(x)
    c, v, h, l = x.Close, x.Volume.fillna(0), x.High, x.Low
    rh = h.shift(1).rolling(10).max(); rl = l.shift(1).rolling(10).min(); rng = rh / rl - 1
    vcon = v.shift(1).rolling(10).mean() < v.rolling(50).mean().shift(1)
    e["base12"] = (rng <= 0.12) & vcon
    e["base8"] = (rng <= 0.08) & vcon
    e["hv"] = v >= 1.5 * v.rolling(20).mean()
    return e


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
            except Exception:  # noqa: BLE001
                f = None
            if f is None:
                continue
            ex = extra(x).reindex(pd.to_datetime(f.Date.values)); ex.index = f.index
            F.append(pd.concat([f, ex], axis=1))
        print("downloaded", i + 200, len(F), flush=True); time.sleep(2)
    d = pd.concat(F, ignore_index=True).sort_values(["SYMBOL", "Date"]).reset_index(drop=True)
    cols = ["g", "t", "t8", "b20", "b50", "base12", "base8", "hv"]
    d[cols] = d[cols].fillna(False).astype(bool)
    gp = d.groupby("SYMBOL")
    d["g5"] = gp.g.transform(lambda s: s.astype(int).rolling(5, min_periods=1).max()).astype(bool)
    d["t10"] = gp.t.transform(lambda s: s.astype(int).rolling(10, min_periods=1).max()).astype(bool)
    d["near_high"] = d.CLOSE / gp.CLOSE.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = gp.CLOSE.transform(lambda s: s / s.shift(63) - 1)
    base = d.sig.copy()
    F_ = {"9/21 plain (reference)": base,
          "F1 9/21 + scanner same day": base & d.g,
          "F2 9/21 + scanner in last 5 days": base & d.g5,
          "F3 9/21 + tight base <=12% + volume dry-up": base & d.base12,
          "F4 F3 + high-volume signal day": base & d.base12 & d.hv,
          "F5 9/21 + tight base <=8% + volume dry-up": base & d.base8,
          "F6 9/21 + tight-range breakout in last 10 days": base & d.t10,
          "F7 scanner in last 5 days + tight base <=12%": base & d.g5 & d.base12}
    res = dict(method=__doc__, signals={k: int(v.sum()) for k, v in F_.items()})
    print(res["signals"], flush=True)
    for label, m in F_.items():
        for rank, mp in (("random", 10), ("r63", 10), ("r63", 5)):
            z = d.copy(); z["sig"] = m.values
            eq, T = C.run(z, mp, 0.01, rank, 0)
            a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
            hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
            yrs = {str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()}
            k = f"{label} | {mp} positions, {'random' if rank == 'random' else '3-month strength'}"
            res[k] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                          win=round((T.pnl > 0).mean() * 100) if len(T) else None, avg_trade=round(T.ret.mean() * 100, 2) if len(T) else None,
                          hold_median_days=float(hold.median()) if len(hold) else None, losing_years=sum(v < 0 for v in yrs.values()), years=yrs)
            print("R|", k, {x: res[k][x] for x in ("cagr", "maxdd", "cagr_22_26", "dd_22_26", "trades", "win", "hold_median_days")}, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/gurjar_921_combo.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
