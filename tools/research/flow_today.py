"""One-off (19 Nov 2026, Amritpal: "how does this money flow?" + why 17 of today's top gainers were in none of our systems).
Part 1 - money flow today by industry / theme (liquid NSE stocks, Yahoo daily bars with today's partial bar):
  rel. volume = today's traded value / (20-day average x share of the session gone), net flow = value in up stocks - value in
  down stocks, breadth = share of stocks up.
Part 2 - for each missed gainer, every system rule checked on the last close before today (why it was not flagged)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402

u = symbols("NSE"); tick = list(u.ticker)
O, H, Lo, C, V = [], [], [], [], []
for i in range(0, len(tick), 250):
    D = yf.download(tick[i:i + 250], period="2y", interval="1d", progress=False, auto_adjust=True, threads=True)
    O.append(D["Open"]); H.append(D["High"]); Lo.append(D["Low"]); C.append(D["Close"]); V.append(D["Volume"])
O, H, Lo, C, V = (pd.concat(x, axis=1) for x in (O, H, Lo, C, V))
ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
frac = min(1.0, max(0.05, ((ist.hour * 60 + ist.minute) - (9 * 60 + 15)) / 375))
chg = (C.iloc[-1] / C.iloc[-2] - 1) * 100
valT = C.iloc[-1] * V.iloc[-1] / 1e7; avg = (C * V).iloc[-21:-1].mean() / 1e7
liq = avg[avg >= 5].index
S = json.load(open("data/scan/sectors.json")); ind = S["symbols"]; th = S.get("themes", {})
print(f"IST {ist:%H:%M} session share {frac:.2f}; liquid {len(liq)}")


def agg(groups):
    out = []
    for g, mem in groups.items():
        m = [t for t in mem if t in liq and pd.notna(chg.get(t))]
        if len(m) < 5:
            continue
        vt, va = float(valT[m].sum()), float(avg[m].sum())
        net = float(sum(valT[t] * np.sign(chg[t]) for t in m))
        out.append(dict(group=g, n=len(m), rel_vol=round(vt / (va * frac), 2), net_flow_cr=round(net), value_cr=round(vt),
                        up=round(float((chg[m] > 0).mean()) * 100), median=round(float(chg[m].median()), 2)))
    return sorted(out, key=lambda r: -r["net_flow_cr"])


gi, gt = {}, {}
for t in tick:
    s = t[:-3]
    if ind.get(s):
        gi.setdefault(ind[s], []).append(t)
    for x in th.get(s, []):
        gt.setdefault(x.replace("NIFTY ", ""), []).append(t)
for name, G in (("INDUSTRY", gi), ("THEME", gt)):
    A = agg(G)
    for r in A[:8] + A[-5:]:
        print(f"F| {name} {json.dumps(r)}")

MISSED = ["VOLTAS", "TATATECH", "IREDA", "SJS", "MARUTI", "WOCKPHARMA", "PGEL", "ADVENZYMES", "COLPAL", "SYMPHONY", "DABUR",
          "PREMEXPLN", "IDFCFIRSTB", "TMPV", "DIXON", "SEDEMAC", "DHOOTTRANS"]
for s in MISSED:
    t = s + ".NS"
    if t not in C:
        print("W|", s, "no data"); continue
    c, h, l, o, v = C[t].iloc[:-1].dropna(), H[t].iloc[:-1], Lo[t].iloc[:-1], O[t].iloc[:-1], V[t].iloc[:-1]
    if len(c) < 60:
        print("W|", s, f"listed only {len(c)} sessions"); continue
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    d_ = c.diff(); up = d_.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d_.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    hi = c.iloc[-250:].max(); last = c.iloc[-1]
    s50 = c.rolling(50).mean(); s200 = c.rolling(200).mean()
    cross = [str(c.index[i].date()) for i in range(len(c) - 60, len(c)) if e9.iloc[i] > e21.iloc[i] and e9.iloc[i - 1] <= e21.iloc[i - 1]]
    ath = C[t].dropna(); ath_hi = ath.iloc[:-1].max(); months_since = (ath.index[-2] - ath.iloc[:-1].idxmax()).days / 30.4
    rng10 = h.iloc[-10:].max() / l.iloc[-10:].min() - 1
    why = dict(close=round(float(last), 2), today=round(float(chg[t]), 2), above_ema50=bool(last > e50.iloc[-1]), ema50_rising=bool(e50.iloc[-1] > e50.iloc[-11]),
               ema9_above_21=bool(e9.iloc[-1] > e21.iloc[-1]), rsi=round(float(rsi.iloc[-1]), 1), off_52w_high_pct=round(float((last / hi - 1) * 100), 1),
               r3m=round(float((last / c.iloc[-64] - 1) * 100), 1), above_200=bool(last > s200.iloc[-1]) if np.isfinite(s200.iloc[-1]) else None,
               crosses_9_21_last_60d=cross[-3:], months_since_ath=round(months_since, 1), off_ath_pct=round(float((last / ath_hi - 1) * 100), 1),
               range_10d_pct=round(float(rng10 * 100), 1), value_cr=round(float(avg.get(t, 0)), 1))
    print("W|", s, json.dumps(why))
