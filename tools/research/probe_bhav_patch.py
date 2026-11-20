"""pilot of tools/nse_bhav.py on real Yahoo downloads (20 Nov 2026)"""
import sys
import time
sys.path.insert(0, "tools")
import pandas as pd
import yfinance as yf
import nse_bhav
nse_bhav.install()
u = pd.read_csv("data/universe/nse_industry.csv") if False else None
tk = ["RELIANCE.NS", "SBIN.NS", "20MICRONS.NS", "ASTRAL.NS", "BALRAMCHIN.NS", "SHREEJISPG.NS", "ANGELONE.NS", "^NSEI"]
for kw in (dict(period="3y", group_by="column", auto_adjust=True), dict(period="max", group_by="column", auto_adjust=False),
           dict(period="1y", group_by="ticker", auto_adjust=False)):
    t0 = time.time(); d = yf.download(tk, interval="1d", progress=False, threads=True, **kw)
    c = d["Close"] if kw["group_by"] == "column" else pd.DataFrame({t: d[t]["Close"] for t in tk})
    print("R|", kw, "secs", round(time.time() - t0, 1), "last rows", [str(i)[:10] for i in c.index[-3:]], "19 Nov closes",
          c.loc[[i for i in c.index if str(i)[:10] == "2026-11-19"]].round(2).to_dict("records"), "stats", dict(nse_bhav.STATS))
x = yf.download("20MICRONS.NS", period="2y", interval="1d", progress=False, auto_adjust=False)
print("R| single", [str(i)[:10] for i in x.index[-3:]], x.tail(2).round(2).to_dict("records"))
big = [s + ".NS" for s in pd.read_csv("data/universe/themes.csv").Symbol.astype(str).unique()[:300]]
t0 = time.time(); d = yf.download(big, period="max", interval="1d", progress=False, group_by="column", auto_adjust=False, threads=True)
print("R| 300 tickers max: secs", round(time.time() - t0, 1), "shape", d.shape, "19 Nov present", int(d["Close"].loc[[i for i in d.index if str(i)[:10] == "2026-11-19"]].notna().sum(axis=1).iloc[0]), "stats", dict(nse_bhav.STATS))
