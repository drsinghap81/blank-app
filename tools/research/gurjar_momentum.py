"""'Bullish momentum stocks' Chartink scanner (Sunil Gurjar) - backtested 19 Nov 2026 at Amritpal's request.

Scanner (daily, cash): close > 50; volume > SMA(volume, 20); SMA(close, 20) > SMA(close, 50); RSI(14) > 50; close > SMA(close, 50);
close > yesterday's high; SMA(volume, 20) > 500,000 shares. The scanner has no exit, so three exits are tested on the same engine
as the live 9/21 test (tools/research/concentrated_921.py: buy next open, stop = 5-day low (skip if > 12% away), 1% risk, 10
positions, costs 0.25% + 0.15% slippage a side):
  A  Supertrend(10,3) turns red -> next open         (the 9/21 system's exit)
  B  a close below SMA 20 -> next open
  C  a close below SMA 50 -> next open
Variant (Amritpal): pullback to the 20 SMA inside a tight 10-session range (<= 12%, also <= 8%), volume contracting in the range,
breakout close above the range high on >= 1.5x average volume.
'fresh' = only the first day a stock passes after not passing the day before (the raw scan repeats every day of a trend).
NSE stocks from Yahoo 2016 -> today (survivors). Reference: the 9/21 system on the same data.
Output: data/research/gurjar_momentum.json"""
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


def extra(x):
    c, v, h = x.Close, x.Volume.fillna(0), x.High
    d_ = c.diff(); up = d_.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d_.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn); s20, s50, vs = c.rolling(20).mean(), c.rolling(50).mean(), v.rolling(20).mean()
    g = (c > 50) & (v > vs) & (s20 > s50) & (rsi > 50) & (c > s50) & (c > h.shift(1)) & (vs > 500000)
    # 19 Nov 2026 (Amritpal's caveat): a pullback to the 20 SMA in a TIGHT range (high-to-low <= 12% over the last 10 sessions),
    # volume CONTRACTING in that range (its average below the 50-day average), then a breakout close above the range high on
    # HIGH volume (>= 1.5x the 20-day average) - the trend conditions as above
    l = x.Low; rh = h.shift(1).rolling(10).max(); rl = l.shift(1).rolling(10).min()
    tight = (rh / rl - 1) <= 0.12
    touch = (l.shift(1).rolling(10).min() <= s20.shift(1) * 1.02)                 # the range came back to (within 2% of) the 20 SMA
    vcon = v.shift(1).rolling(10).mean() < v.rolling(50).mean().shift(1)
    brk = (c > rh) & (v >= 1.5 * vs)
    t = (c > 50) & (s20 > s50) & (c > s50) & (rsi > 50) & (vs > 500000) & tight & touch & vcon & brk
    t12 = t & ((rh / rl - 1) <= 0.12)
    t8 = t & ((rh / rl - 1) <= 0.08)
    return pd.DataFrame({"g": g, "t": t12, "t8": t8, "b20": c < s20, "b50": c < s50}, index=x.index)


def main():
    u = symbols("NSE"); tick = list(u.ticker); F, E = [], []
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]
        for _ in range(3):
            try:
                D = yf.download(ch, start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20); D = None
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
    d = pd.concat(F, ignore_index=True).sort_values(["SYMBOL", "Date"])
    d[["g", "t", "t8", "b20", "b50"]] = d[["g", "t", "t8", "b20", "b50"]].fillna(False).astype(bool)
    gp = d.groupby("SYMBOL")
    d["g_fresh"] = d.g & ~gp.g.shift(1).fillna(False).astype(bool)
    d["near_high"] = d.CLOSE / gp.CLOSE.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = gp.CLOSE.transform(lambda s: s / s.shift(63) - 1)
    res = dict(method=__doc__, signals_raw=int(d.g.sum()), signals_fresh=int(d.g_fresh.sum()), signals_921=int(d.sig.sum()),
               signals_tight12=int(d.t.sum()), signals_tight8=int(d.t8.sum()))

    def go(label, sigcol, exitcol=None, rank="random", seed=0, mp=10):
        z = d.copy(); z["sig"] = z[sigcol]
        if exitcol:
            z["st"] = np.where(z[exitcol], -1, 1)
        eq, T = C.run(z, mp, 0.01, rank, seed)
        a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
        hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
        res[label] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                          win=round((T.pnl > 0).mean() * 100) if len(T) else None, avg_trade=round(T.ret.mean() * 100, 2) if len(T) else None,
                          hold_median_days=float(hold.median()) if len(hold) else None,
                          years={str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()})
        print(label, {k: res[label][k] for k in ("cagr", "maxdd", "cagr_22_26", "trades", "win", "hold_median_days")}, flush=True)
    for nm, col in (("raw", "g"), ("fresh", "g_fresh")):
        for ex_nm, ex in (("A Supertrend exit", None), ("B close < SMA20", "b20"), ("C close < SMA50", "b50")):
            go(f"Scanner {nm} | {ex_nm} | random", col, ex)
            go(f"Scanner {nm} | {ex_nm} | 3-month strength", col, ex, rank="r63")
    for nm, col in (("tight range <= 12%", "t"), ("tight range <= 8%", "t8")):
        for ex_nm, ex in (("A Supertrend exit", None), ("B close < SMA20", "b20"), ("C close < SMA50", "b50")):
            go(f"Pullback {nm} + volume dry-up + high-volume breakout | {ex_nm} | random", col, ex)
            go(f"Pullback {nm} + volume dry-up + high-volume breakout | {ex_nm} | 3-month strength", col, ex, rank="r63")
    go("9/21 system (reference) | random", "sig")
    go("9/21 system (reference) | 3-month strength", "sig", rank="r63")
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/gurjar_momentum.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
