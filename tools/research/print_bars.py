"""print daily NSE bars for one stock (UNIV env = symbol) as R|B lines, for charts in chat."""
import json
import os

import yfinance as yf

s = os.environ.get("UNIV") or "LAURUSLABS"
x = yf.download(s + ".NS", start="2024-06-01", auto_adjust=False, progress=False).dropna()
x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
print("R|B " + json.dumps(dict(s=s, bars=[[str(d.date()), *[round(float(r[k]), 2) for k in ("Open", "High", "Low", "Close", "Volume")]] for d, r in x.iterrows()])), flush=True)
