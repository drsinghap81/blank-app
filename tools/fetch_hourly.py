"""Hourly OHLCV (Yahoo 60m, last ~730 days) for the Nifty 500 + Nifty 50 index, for the short-swing research (11 Nov 2026).
Usage: python fetch_hourly.py -> hist/nse_1h.parquet (Datetime IST, SYMBOL, OHLCV). Research only; not used by the app."""
import os
import time
import pandas as pd
import yfinance as yf

os.makedirs("hist", exist_ok=True)
syms = pd.read_csv("data/universe/nifty500.csv")["Symbol"].dropna().astype(str).tolist()
tick = {s + ".NS": s for s in syms}; tick["^NSEI"] = "NIFTY50"
out = []
L = list(tick)
for k in range(0, len(L), 50):
    b = L[k:k + 50]
    for _ in range(3):
        try:
            d = yf.download(b, period="730d", interval="60m", auto_adjust=True, progress=False, group_by="column", threads=True)
            break
        except Exception as e:  # noqa: BLE001
            print("retry", e, flush=True); time.sleep(15); d = None
    if d is None or d.empty:
        continue
    for t in b:
        try:
            x = pd.DataFrame({c: d[c][t] for c in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
        except Exception:  # noqa: BLE001
            continue
        if len(x) < 200:
            continue
        x.index = pd.to_datetime(x.index); x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None) if x.index.tz is not None else x.index
        x["SYMBOL"] = tick[t]; out.append(x.reset_index().rename(columns={x.index.name or "index": "Datetime"}))
    print(k + len(b), "of", len(L), flush=True); time.sleep(2)
H = pd.concat(out, ignore_index=True)
H.columns = ["Datetime"] + list(H.columns[1:])
H.to_parquet("hist/nse_1h.parquet", index=False)
print("rows", len(H), "symbols", H.SYMBOL.nunique(), H.Datetime.min(), H.Datetime.max())
