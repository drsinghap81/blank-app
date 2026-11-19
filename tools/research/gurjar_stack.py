"""Moving-average stack filter (19 Nov 2026, Amritpal: "20 rising above 50 rising and then 200 rising"):
close > SMA20 > SMA50 > SMA200, SMA20 above its value 5 sessions ago, SMA50 above 10 sessions ago, SMA200 above 20 sessions ago.
Applied to the signals below, with and without the stack, under both trade managements.

Based on gurjar_ema9_exit:
"breakout candle low is SL and 9 EMA 2 candles close is exit".

  stop : the low of the signal (breakout) candle, a resting stop from the next day (skip if > 12% below the next open)
  exit : two consecutive daily closes below EMA 9 -> sell next open
compared with the standard management (stop = 5-day low, exit when Supertrend(10,3) turns red) and the two mixes.
Signals: the tight-range (<= 12% / <= 8%) pullback-to-SMA20 + volume dry-up + high-volume breakout variant; plain 9/21;
9/21 + tight base + dry-up (F3); F3 + high-volume signal day (F4). Same data and engine as gurjar_921_combo.py.
Output: data/research/gurjar_stack.json"""
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
from gurjar_921_combo import extra as extra1  # noqa: E402


def extra(x):
    e = extra1(x); c = x.Close
    e9 = c.ewm(span=9, adjust=False).mean(); b = c < e9
    e["x9"] = b & b.shift(1, fill_value=False)
    e["sigLow"] = x.Low
    s20, s50, s200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    e["stack"] = (c > s20) & (s20 > s50) & (s50 > s200) & (s20 > s20.shift(5)) & (s50 > s50.shift(10)) & (s200 > s200.shift(20))
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
    cols = ["g", "t", "t8", "b20", "b50", "base12", "base8", "hv", "x9", "stack"]
    d[cols] = d[cols].fillna(False).astype(bool)
    gp = d.groupby("SYMBOL")
    d["near_high"] = d.CLOSE / gp.CLOSE.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = gp.CLOSE.transform(lambda s: s / s.shift(63) - 1)
    S0 = {"Tight range <=12% breakout": d.t, "Tight range <=8% breakout": d.t8, "9/21 plain": d.sig.copy(),
          "9/21 + tight base + dry-up (F3)": d.sig & d.base12, "F3 + high-volume signal day (F4)": d.sig & d.base12 & d.hv}
    S = {}
    for k, v in S0.items():
        S[k] = v; S[k + " + MA STACK"] = v & d["stack"]
    M = {"standard (5-day low stop, Supertrend exit)": (False, False),
         "YOURS: breakout-candle-low stop + 2 closes below 9 EMA": (True, True)}
    res = dict(method=__doc__, signals={k: int(v.sum()) for k, v in S.items()})
    for sl, sm in S.items():
        for ml, (cs, ex9) in M.items():
            z = d.copy(); z["sig"] = sm.values
            if cs:
                z["low5"] = z.sigLow
            if ex9:
                z["st"] = np.where(z.x9, -1, 1)
            for rank, mp in (("r63", 10), ("r63", 5), ("random", 10)):
                eq, T = C.run(z, mp, 0.01, rank, 0)
                a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
                b = stats(eq, "2017-01-01", "2021-12-31")
                hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
                yrs = {str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()}
                k = f"{sl} | {ml} | {mp} positions, {'random' if rank == 'random' else '3-month strength'}"
                res[k] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                              win=round((T.pnl > 0).mean() * 100) if len(T) else None, avg_trade=round(T.ret.mean() * 100, 2) if len(T) else None,
                              hold_median_days=float(hold.median()) if len(hold) else None, losing_years=sum(v < 0 for v in yrs.values()), years=yrs)
                print("R|", k, {x: res[k][x] for x in ("cagr", "maxdd", "cagr_22_26", "dd_22_26", "trades", "win", "hold_median_days")}, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/gurjar_stack.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
