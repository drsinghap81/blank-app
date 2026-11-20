"""pilot: Nasdaq fill vs Yahoo on 300 US tickers (remove 19 Nov, refill, compare) (20 Nov 2026)"""
import sys
import time
import pandas as pd
sys.path.insert(0, "tools")
import group_pulse as G
cf = G.CFG["US"]; u = G.universe("US")
tick = {s: s.replace("/", "-").replace(".", "-") + cf["suf"] for s in list(u.symbol)[:300]}
data = G.download(list(tick.values()))
D = pd.Timestamp("2026-11-19")
keep = {t: x.loc[D].copy() for t, x in data.items() if D in x.index}
for t in keep:
    data[t] = data[t].drop(D)
t0 = time.time(); got = G.nasdaq_fill(data, list(keep), D)
diff = [abs(data[t].loc[D, "c"] / keep[t]["c"] - 1) * 100 for t in keep if D in data[t].index]
print("R| removed", len(keep), "refilled", got, "secs", round(time.time() - t0, 1), "| close diff vs Yahoo: median",
      round(float(pd.Series(diff).median()), 3), "% max", round(float(pd.Series(diff).max()), 2), "% ; >0.5%:", sum(d > 0.5 for d in diff))
