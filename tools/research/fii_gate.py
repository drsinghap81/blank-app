"""FII cash-flow gates for the system tests (22 Nov 2026, Amritpal: "test all systems against regular FII buying").

NSDL daily 'Equity / Stock Exchange' FPI net investment (Rs cr), scraped by tools/research/fii_test.daily (cached in
data/research/fii_daily.csv). A reporting date covers trades up to the previous session, so every gate is shifted one session
(a value is only used from the next session on - no look-ahead).
Gates (True = new buys allowed that day):
  buy20   FII bought regularly: 20-session net > 0
  buy60   FII bought regularly: 60-session net > 0
  noheavy not heavy FII selling: the 20-session net is not in its bottom 20% of the past year"""
import os
import sys
from datetime import date

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CSV = "data/research/fii_daily.csv"
NAMES = {"buy20": "only while FII bought regularly (20-day net > 0)", "buy60": "only while FII bought regularly (60-day net > 0)",
         "noheavy": "skip while FII sell heavily (20-day net in its bottom 20%)"}


def daily():
    if os.path.exists(CSV):
        s = pd.read_csv(CSV, index_col=0).iloc[:, 0]; s.index = pd.to_datetime(s.index)
        if len(s) > 2000:
            return s.sort_index()
    import fii_test as FT
    FT.START = date(2015, 1, 1)
    s = FT.daily(); os.makedirs("data/research", exist_ok=True); s.to_csv(CSV)
    return s


def gates(days):
    """days: trading-day index. Returns DataFrame of bool gates on those days (+ f20 / f60 for reporting)."""
    F = daily(); days = pd.DatetimeIndex(days)
    f = F.reindex(days.union(F.index)).fillna(0.0).loc[days].shift(1)        # used from the next session
    f20, f60 = f.rolling(20, min_periods=15).sum(), f.rolling(60, min_periods=45).sum()
    p20 = f20.rolling(250, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    G = pd.DataFrame(index=days)
    G["buy20"] = f20 > 0; G["buy60"] = f60 > 0; G["noheavy"] = ~(p20 < 0.2)
    G["f20"] = f20; G["f60"] = f60
    print("R| FII gate days", len(days), "share allowed:", {k: round(float(G[k].mean()) * 100) for k in NAMES}, "data", F.index.min().date(), F.index.max().date(), flush=True)
    return G
