"""Hourly (60m, ~730 days) Yahoo bars for Nifty, Bank Nifty, NIFTYBEES (volume proxy for VWAP). -> hourly/*.csv"""
import os, yfinance as yf, pandas as pd
os.makedirs("hourly", exist_ok=True)
for sym, name in [("^NSEI", "nifty"), ("NIFTYBEES.NS", "niftybees"), ("^NSEBANK", "banknifty")]:
    for iv, per in [("60m", "730d"), ("15m", "60d"), ("5m", "60d")]:
        d = yf.download(sym, period=per, interval=iv, auto_adjust=False, progress=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        d.index = d.index.tz_convert("Asia/Kolkata")
        d.to_csv(f"hourly/{name}_{iv}.csv"); print(name, iv, len(d), d.index.min(), d.index.max())
