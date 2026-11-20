"""probe: why group_pulse NSE / UK end on 18 Nov (20 Nov 2026) - replicate its download + day filters on a sample"""
import sys
import pandas as pd
sys.path.insert(0, "tools")
import group_pulse as G
from session import drop_partial
for mkt in ("NSE", "UK"):
    cf = G.CFG[mkt]; u = G.universe(mkt)
    tick = {s: s + cf["suf"] for s in list(u.symbol)[:300]}
    data = G.download(list(tick.values()) + [cf["bench"]])
    C = pd.DataFrame({s: data[t].c for s, t in tick.items() if t in data and len(data[t]) > 160}).sort_index()
    cnt = C.notna().sum(axis=1)
    print("R|", mkt, "raw tail", [(str(i)[:16], int(n)) for i, n in cnt.tail(4).items()], "index tz", C.index.tz)
    keep = cnt >= 0.5 * cnt.rolling(20, min_periods=1).max(); C2 = C[keep]
    print("R|", mkt, "after count filter", [str(i)[:10] for i in C2.index[-3:]], "after drop_partial", [str(i)[:10] for i in drop_partial(C2, mkt).index[-3:]])
    t0 = list(data)[0]; print("R|", mkt, "one series tail", t0, data[t0].tail(3).round(2).to_dict("index"))
