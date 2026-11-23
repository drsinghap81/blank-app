"""How did this week's Pulse rotation basket do today? (23 Nov 2026) Yahoo daily: Friday close -> today, and today's open -> close
(the rule buys at Monday's open), vs Nifty 50 and Nifty Bank. Read-only."""
import json

import pandas as pd
import yfinance as yf

P = json.load(open("data/scan/pulse_rot.json")); names = list(P["pos"])
T = [s + ".NS" for s in names] + ["^NSEI", "^NSEBANK", "^CNXIT"]
d = yf.download(T, period="7d", interval="1d", progress=False, auto_adjust=False, group_by="ticker")
rows = []
for t in T:
    x = d[t].dropna(subset=["Close"])
    if len(x) < 2:
        continue
    f, z = x.iloc[-2], x.iloc[-1]
    rows.append(dict(sym=t.replace(".NS", ""), day=str(x.index[-1].date()), fri=round(f.Close, 2), open=round(z.Open, 2), close=round(z.Close, 2),
                     from_fri=round((z.Close / f.Close - 1) * 100, 2), from_open=round((z.Close / z.Open - 1) * 100, 2)))
R = pd.DataFrame(rows)
for _, r in R.iterrows():
    print(f"R| {r.sym} | {r.day} | Fri {r.fri} open {r.open} close {r.close} | vs Fri {r.from_fri:+.2f}% | open->close {r.from_open:+.2f}%", flush=True)
B = R[R.sym.isin(names)]
print(f"R| BASKET ({len(B)}) | vs Fri {B.from_fri.mean():+.2f}% | from Monday open {B.from_open.mean():+.2f}%", flush=True)
