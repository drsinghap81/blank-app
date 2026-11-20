"""probe: group_pulse download + gap fill + day filters on a sample (20 Nov 2026)"""
import sys
import pandas as pd
sys.path.insert(0, "tools")
import group_pulse as G
from session import drop_partial
for mkt in ("NSE", "UK"):
    cf = G.CFG[mkt]; u = G.universe(mkt)
    tick = {s: s + cf["suf"] for s in list(u.symbol)[:300]}
    data = G.download(list(tick.values()) + [cf["bench"]]); G.fill_gaps(data, mkt)
    C = pd.DataFrame({s: data[t].c for s, t in tick.items() if t in data and len(data[t]) > 160}).sort_index()
    cnt = C.notna().sum(axis=1)
    print("R|", mkt, "tail counts", [(str(i)[:10], int(n)) for i, n in cnt.tail(4).items()])
    C2 = C[cnt >= 0.5 * cnt.rolling(20, min_periods=1).max()]
    print("R|", mkt, "ends", [str(i)[:10] for i in drop_partial(C2, mkt).index[-3:]])
