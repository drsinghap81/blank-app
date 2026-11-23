"""Top Bottom on the 'high beta / wide ATR / high IV' F&O list Amritpal pasted (24 Nov 2026). Daily NSE prices (Yahoo + bhavcopy patch,
cash prices as a stand-in for futures), long + short and buy-only, stock rules 1.5/3/3, buffer 0.05%, 0.1% cost. Same split as
claude/top-bottom-instrument-screen.md: 2010-17 vs 2018-26, plus last 5 / 2 years and current ATR%."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
import topbottom_backtest as tbb  # noqa: E402

L = ["ADANIENT", "GODREJPROP", "MAZDOCK", "DIXON", "TRENT", "HAL", "BDL", "CANBK", "PNB", "HINDALCO", "VEDL", "DLF", "PRESTIGE", "KAYNES"]
SPLIT = pd.Timestamp("2018-01-01")


def perf(t):
    if t is None or t.empty:
        return "-"
    r = t.Pct / 100 - 0.001; yrs = max((t.ExitDate.max() - t.EntryDate.min()).days / 365.25, 0.5)
    eq = (1 + r).cumprod(); g, b = r[r > 0].sum(), -r[r < 0].sum()
    return f"n{len(t)} PF {g / b if b else 9:.2f} {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%/yr DD {((eq / eq.cummax()) - 1).min() * 100:.0f}%"


for s in L:
    d = yf.download(s + ".NS", start="2009-06-01", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.High >= x.Low) & (x.index >= "2010-01-01")]
    if len(x) < 300:
        print(f"R| {s} | too little data"); continue
    tr = pd.concat([x.High - x.Low, (x.High - x.Close.shift()).abs(), (x.Low - x.Close.shift()).abs()], axis=1).max(axis=1)
    atr = (tr.ewm(alpha=1 / 14, adjust=False).mean() / x.Close * 100).iloc[-250:].median()
    out = {}
    for lab, lo in (("both", False), ("buy-only", True)):
        t = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5, long_only=lo))
        t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ExitDate"] = pd.to_datetime(t.ExitDate); end = t.ExitDate.max()
        out[lab] = (f"2010-17 {perf(t[t.EntryDate < SPLIT])} | 2018-26 {perf(t[t.EntryDate >= SPLIT])} | last 5y {perf(t[t.ExitDate > end - pd.DateOffset(years=5)])} | "
                    f"last 2y {perf(t[t.ExitDate > end - pd.DateOffset(years=2)])}")
    print(f"R| {s:10s} since {x.index[0].date()} ATR {atr:.1f}% | BOTH {out['both']}", flush=True)
    print(f"R| {s:10s}  BUY-ONLY {out['buy-only']}", flush=True)
