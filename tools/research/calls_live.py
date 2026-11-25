"""25 Nov 2026 (Amritpal: "how are the marine stocks doing as you indicated in the Today tab, till now"): the latest Today calls
(data/scan/today_calls.json.state, call-day closes) against live Yahoo prices (~15 min delayed), equal weight, vs Nifty."""
import json
from datetime import datetime, timedelta, timezone

import yfinance as yf

S = json.load(open("data/scan/today_calls.json.state")); d = S["days"][-1]
C = [c for c in S["calls"] if c["d"] == d]
syms = sorted({s for c in C for s in c["c0"]})
px = yf.download([s + ".NS" for s in syms] + ["^NSEI"], period="2d", interval="1m", progress=False, auto_adjust=False)["Close"].ffill().iloc[-1]
nf0 = C[0].get("nf0"); nfl = float(px.get("^NSEI", float("nan")))
print(f"R| calls from the {d} close, prices at {datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%H:%M')} IST (delayed); Nifty {nfl:,.0f}"
      + (f" ({(nfl / nf0 - 1) * 100:+.2f}% vs the call-day close, futures ref)" if nf0 else ""), flush=True)
for c in C:
    rs = [(s, float(px[s + ".NS"]) / v - 1) for s, v in c["c0"].items() if s + ".NS" in px and px[s + ".NS"] == px[s + ".NS"]]
    if not rs:
        continue
    avg = sum(r for _, r in rs) / len(rs) * 100; up = sum(r > 0 for _, r in rs)
    top = sorted(rs, key=lambda x: -x[1])
    print(f"R| {c['kind']:8s} {c['name'][:34]:34s} {avg:+6.2f}% | {up}/{len(rs)} up | best {', '.join(f'{s} {r * 100:+.1f}%' for s, r in top[:3])} | worst {', '.join(f'{s} {r * 100:+.1f}%' for s, r in top[-2:])}", flush=True)
