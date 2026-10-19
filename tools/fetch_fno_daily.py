import os, pandas as pd, yfinance as yf
os.makedirs("fno_daily", exist_ok=True)
syms = pd.read_csv("data/universe/fno_stocks.csv")["Symbol"].astype(str).tolist()
syms += ["NIFTYBEES"]
ok = 0
for k in range(0, len(syms), 50):
    chunk = [s + ".NS" for s in syms[k:k + 50]]
    d = yf.download(chunk, start="2008-01-01", interval="1d", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    for t in chunk:
        try:
            x = d[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
            if len(x) > 250:
                x.round(3).to_csv(f"fno_daily/{t[:-3].replace('&','_')}.csv"); ok += 1
        except Exception:
            pass
print("saved", ok, "of", len(syms))
