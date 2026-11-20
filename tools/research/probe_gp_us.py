"""pilot: US gap fill from Nasdaq on 300 tickers (20 Nov 2026)"""
import sys
import time
import pandas as pd
sys.path.insert(0, "tools")
import group_pulse as G
cf = G.CFG["US"]; u = G.universe("US")
tick = {s: s.replace("/", "-").replace(".", "-") + cf["suf"] for s in list(u.symbol)[:300]}
data = G.download(list(tick.values()))
C = pd.DataFrame({s: data[t].c for s, t in tick.items() if t in data and len(data[t]) > 160}).sort_index()
print("R| before", [(str(i)[:10], int(n)) for i, n in C.notna().sum(axis=1).tail(3).items()], flush=True)
t0 = time.time(); G.fill_gaps(data, "US")
C = pd.DataFrame({s: data[t].c for s, t in tick.items() if t in data and len(data[t]) > 160}).sort_index()
print("R| after", [(str(i)[:10], int(n)) for i, n in C.notna().sum(axis=1).tail(3).items()], "secs", round(time.time() - t0, 1))
t = next(iter(tick.values())); print("R| sample", t, data[t].tail(2).round(2).to_dict("index"))
