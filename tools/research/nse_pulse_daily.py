"""Daily NSE-industry Pulse rank per stock, point in time (20 Nov 2026, for the option backtest's 'puts on weak-Pulse stocks, calls
on strong' test). For each day: Pulse of each NSE basic industry (3+ liquid stocks; share of its stocks trending over the last 21
sessions, the app's rule) ranked 0-1 across industries; every member stock gets its industry's rank.
Output data/research/nse_pulse_daily.json = {date: {SYMBOL: rank}} for the last 120 sessions. LIMIT env = pilot."""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools/research")
import industry_basket_intraday as B  # noqa: E402

IND, SYMS = B.IND, B.SYMS


def daily():
    out = {}
    for a in range(0, len(SYMS), 100):
        ch = [s + ".NS" for s in SYMS[a:a + 100]]
        for k in range(4):
            d = yf.download(ch, period="3y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=False)
            c = d["Close"] if len(d) else pd.DataFrame()
            got = [t for t in ch if t in c.columns and c[t].notna().sum() > 200]
            for t in got:
                out[t[:-3]] = c[t]
            if len(got) >= 0.9 * len(ch):
                break
            print("chunk", a, "got", len(got), "of", len(ch), "retry", k + 1, flush=True); time.sleep(30 * (k + 1))
        time.sleep(3)
    b = yf.download("^NSEI", period="3y", interval="1d", progress=False, auto_adjust=True)["Close"]
    return pd.DataFrame(out).sort_index(), (b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b)


C, bench = daily()
bench = bench.reindex(C.index).ffill()
print("R| daily", C.shape, "of", len(SYMS), flush=True)
rpi = lambda k: 100 * (C / C.shift(k)).div(bench / bench.shift(k), axis=0)  # noqa: E731
w = (rpi(10) + rpi(63) + rpi(126)) / 3
e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
hi52 = C.rolling(250, min_periods=120).max()
tr = ((w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52)).astype(float).where(C.notna())
share = tr.rolling(21, min_periods=15).mean()
P = pd.DataFrame({k: share[[s for s in v if s in share.columns]].mean(axis=1) for k, v in IND.items()})
pct = P.rank(axis=1, pct=True).iloc[-120:]
out = {}
for d, row in pct.iterrows():
    out[str(d.date())] = {s: round(float(row[k]), 3) for k, v in IND.items() if pd.notna(row.get(k)) for s in v}
# 21 Nov 2026: weekly relative-rotation quadrant of each NSE industry vs Nifty 50 (same formula as the app), per stock and day
# (a Friday's quadrant applies from the next session), for the option backtest's "calls in Leading / puts in Lagging" test
idx = {}
for k, v in IND.items():
    ss = [x for x in v if x in C.columns]
    if len(ss) >= 3:
        r = C[ss].pct_change(fill_method=None).clip(-0.3, 0.3); n = r.notna().sum(axis=1)
        idx[k] = (1 + r.mean(axis=1).where(n >= 3).fillna(0)).cumprod()
I = pd.DataFrame(idx); Wk = I.resample("W-FRI").last(); NB = bench.resample("W-FRI").last()
RS = 100 * Wk.div(NB, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
Qw = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=Wk.index, columns=Wk.columns).where(ratio.notna() & mom.notna())
Qd = Qw.reindex(I.index, method="ffill").iloc[-120:]
quad = {str(d.date()): {s: row[k] for k, v in IND.items() if isinstance(row.get(k), str) for s in v} for d, row in Qd.iterrows()}
os.makedirs("data/research", exist_ok=True)
json.dump(quad, open("data/research/nse_quad_daily.json", "w"), separators=(",", ":"))
lq = sorted(quad)[-1]
print("R| quadrant days", len(quad), "last", lq, "SBIN", quad[lq].get("SBIN"), "counts", pd.Series(list(quad[lq].values())).value_counts().to_dict(), flush=True)
json.dump(out, open("data/research/nse_pulse_daily.json", "w"), separators=(",", ":"))
last = sorted(out)[-1]
print("R| days", len(out), "first", min(out), "last", last, "stocks", len(out[last]), "SBIN", out[last].get("SBIN"), "top",
      sorted(((round(float(pct.iloc[-1][k]), 2), k) for k in IND if pd.notna(pct.iloc[-1].get(k))), reverse=True)[:5], flush=True)
