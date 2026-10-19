import os, yfinance as yf, pandas as pd
os.makedirs("intraday", exist_ok=True)
for sym, name in [("^NSEI", "nifty"), ("^NSEBANK", "banknifty")]:
    for iv, per in [("5m", "60d"), ("15m", "60d"), ("60m", "730d")]:
        try:
            d = yf.download(sym, period=per, interval=iv, auto_adjust=False, progress=False)
            if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
            d = d[["Open", "High", "Low", "Close"]].dropna()
            d.index = d.index.tz_convert("Asia/Kolkata")
            d.to_csv(f"intraday/{name}_{iv}.csv"); print(name, iv, len(d), d.index.min(), d.index.max())
        except Exception as e:
            print(name, iv, "fail", e)
