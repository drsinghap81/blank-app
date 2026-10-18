"""Download daily history used by the Top Bottom lab and save as CSV."""
import os
import yfinance as yf

os.makedirs("data", exist_ok=True)
for sym, name in [("^NSEBANK", "banknifty"), ("^NSEI", "nifty")]:
    df = yf.download(sym, start="2005-01-01", interval="1d", auto_adjust=False, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna().round(2)
    df.to_csv(f"data/{name}.csv")
    print(sym, len(df), df.index.min(), df.index.max())
