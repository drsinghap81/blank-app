"""One-off (19 Nov 2026): 8 of today's missed gainers had an EMA 9/21 cross in the last 60 sessions but no 9/21 signal.
Which 9/21 rule failed on each cross day? (live rules: tools/trend_scan.py early())"""
import sys, os
import numpy as np
import pandas as pd
import yfinance as yf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from trend_scan import rsi, supertrend  # noqa: E402

for s in ["VOLTAS", "IREDA", "MARUTI", "WOCKPHARMA", "PGEL", "ADVENZYMES", "IDFCFIRSTB", "DHOOTTRANS"]:
    x = yf.Ticker(s + ".NS").history(period="2y", interval="1d", auto_adjust=True)
    x.index = x.index.tz_localize(None); x = x.iloc[:-1]                    # up to yesterday
    c, h, l, v = x.Close, x.High, x.Low, x.Volume
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    r = rsi(c); sd, _ = supertrend(h.values, l.values, c.values); hi = c.rolling(250, min_periods=60).max(); val = (c * v).rolling(20).mean() / 1e7
    for i in range(len(c) - 60, len(c)):
        if e9.iloc[i] > e21.iloc[i] and e9.iloc[i - 1] <= e21.iloc[i - 1]:
            f = []
            if sd[i] != 1: f.append("Supertrend red")
            if not c.iloc[i] > e50.iloc[i]: f.append("close below EMA50")
            if not e50.iloc[i] > e50.iloc[i - 10]: f.append("EMA50 not rising")
            if not r.iloc[i] >= 55: f.append(f"RSI {r.iloc[i]:.1f} < 55")
            if not c.iloc[i] >= 0.7 * hi.iloc[i]: f.append(f"{(c.iloc[i] / hi.iloc[i] - 1) * 100:.0f}% off 52w high (> 30%)")
            if not val.iloc[i] >= 1: f.append("illiquid")
            if len(c.iloc[:i + 1]) < 120: f.append("listed < 120 sessions")
            gain = (c.iloc[-1] / c.iloc[i] - 1) * 100
            print(f"M| {s} cross {c.index[i].date()}: {'SIGNAL (all rules passed)' if not f else 'failed: ' + ', '.join(f)} | since cross {gain:+.1f}%")
