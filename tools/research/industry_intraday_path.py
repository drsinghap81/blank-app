"""When in the day did the top industries make their move? (20 Nov 2026) 5-minute Yahoo bars, equal-weight industry path vs the
previous close, for the 8 industries shown at the top of Markets > India (old groups) and the top NSE official sectors."""
import json
import sys
sys.path.insert(0, "tools")
import pandas as pd
import yfinance as yf
G = json.load(open("data/scan/group_pulse.json")); day = G["asof"]
rows = sorted(G["rows"], key=lambda r: -(r.get("d1") or -99))[:8]
syms = sorted({m["symbol"] for r in rows for m in r["members"]})
d = yf.download([s + ".NS" for s in syms], period="5d", interval="5m", progress=False, group_by="column", auto_adjust=False, threads=True)
C = d["Close"]; C.columns = [c[:-3] for c in C.columns]
C.index = C.index.tz_convert("Asia/Kolkata") if C.index.tz is not None else C.index
days = sorted({t.date() for t in C.index}); D = pd.Timestamp(day).date(); prev = [x for x in days if x < D][-1]
pc = C[[t.date() == prev for t in C.index]].ffill().iloc[-1]; X = C[[t.date() == D for t in C.index]].ffill()
for r in rows:
    ss = [m["symbol"] for m in r["members"] if m["symbol"] in X.columns]
    path = ((X[ss] / pc[ss] - 1) * 100).mean(axis=1)
    if path.empty:
        continue
    fin = path.iloc[-1]; half = path[path >= fin / 2]; t_half = half.index[0].strftime("%H:%M") if len(half) else "-"
    lo_t = path.idxmin().strftime("%H:%M"); hi_t = path.idxmax().strftime("%H:%M")
    at = lambda hm: round(float(path[[t.strftime("%H:%M") <= hm for t in path.index]].iloc[-1]), 2)  # noqa: E731
    print(f"R| {r['group']}: open {path.iloc[0]:+.2f}% | 10:00 {at('10:00'):+.2f} | 11:00 {at('11:00'):+.2f} | 13:00 {at('13:00'):+.2f} | "
          f"14:30 {at('14:30'):+.2f} | close {fin:+.2f}% | half the gain by {t_half} | low {path.min():+.2f}% at {lo_t} | high {path.max():+.2f}% at {hi_t}", flush=True)
