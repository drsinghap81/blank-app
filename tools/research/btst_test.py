"""BTST on strong closes of the day's top gainers (19 Nov 2026, Amritpal: "if today's candle closes strong for these top gainers
- bullish engulfing, thrusting, pro gap - is it a good BTST trade? check at 3:20 pm and carry overnight").
NSE stocks from Yahoo 2016 -> today (survivors), liquid >= Rs 5 cr/day (20-day avg, known the day before). Buy at the day's CLOSE
(stand-in for 3:20 pm), sell at: next OPEN (BTST), next CLOSE, or the close 3 days later. Costs 0.25% round trip + 0.05% slippage
a side. Industry = today's NSE classification (data/scan/sectors.json).
  G1 top 20 gainers of the day, close in the top 20% of the day's range
  G2 G1 + beats its industry's median move and Nifty that day
  G3 day's gain >= 3% and bullish engulfing (yesterday red, today opens <= yesterday's close and closes >= yesterday's open)
  G4 'pro gap' held: opened >= 1% above yesterday's high... relaxed to >= 1% above yesterday's close, closed >= open, close in top 25%
  G0 baseline: every liquid stock every day (what a random overnight hold makes)
Split by Nifty up / down day and by year. Output: data/research/btst_test.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402

COST = 0.0025 + 2 * 0.0005


def main():
    S = json.load(open("data/scan/sectors.json")); ind = S["symbols"]
    tick = list(symbols("NSE").ticker); P = {}
    for i in range(0, len(tick), 200):
        for _ in range(3):
            try:
                D = yf.download(tick[i:i + 200], start="2015-09-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20); D = None
        if D is None or D.empty:
            continue
        for k in ("Open", "High", "Low", "Close", "Volume"):
            P.setdefault(k, []).append(D[k])
        print("downloaded", i + 200, flush=True); time.sleep(2)
    O, H, L, C, V = (pd.concat(P[k], axis=1) for k in ("Open", "High", "Low", "Close", "Volume"))
    nif = yf.download("^NSEI", start="2015-09-01", auto_adjust=True, progress=False)["Close"].squeeze().reindex(C.index).ffill()
    liq = ((C * V).rolling(20).mean().shift(1) >= 5e7) & (C >= 50)
    chg = C.pct_change() * 100
    rng = (H - L).replace(0, np.nan); clv = (C - L) / rng
    nchg = nif.pct_change() * 100
    im = pd.DataFrame(index=C.index)
    groups = {}
    for t in C.columns:
        g = ind.get(t[:-3])
        if g:
            groups.setdefault(g, []).append(t)
    indmed = pd.DataFrame({g: chg[m].where(liq[m]).median(axis=1) for g, m in groups.items()})
    IM = pd.DataFrame({t: indmed[ind[t[:-3]]] for t in C.columns if ind.get(t[:-3]) in indmed}).reindex(columns=C.columns)
    rank = chg.where(liq).rank(axis=1, ascending=False)
    G = {"G0 baseline: any liquid stock": liq & chg.notna(),
         "G1 top 20 gainers, close in top 20% of range": liq & (rank <= 20) & (clv >= 0.8),
         "G2 G1 + beats industry median and Nifty": liq & (rank <= 20) & (clv >= 0.8) & (chg > IM.fillna(-99)) & chg.gt(nchg, axis=0),
         "G3 +3% day, bullish engulfing": liq & (chg >= 3) & (C.shift(1) < O.shift(1)) & (O <= C.shift(1)) & (C >= O.shift(1)),
         "G4 gap up >= 1% held, close in top 25%": liq & (O >= C.shift(1) * 1.01) & (C >= O) & (clv >= 0.75) & (chg >= 2)}
    X = {"next open (BTST)": O.shift(-1) / C - 1, "next close": C.shift(-1) / C - 1, "3 days later close": C.shift(-3) / C - 1}
    up = nchg > 0
    res = dict(method=__doc__)
    for gname, mask in G.items():
        m = mask & (C.index >= "2016-06-01")[:, None]
        for xname, R in X.items():
            r = (R - COST).where(m).stack()
            if not len(r):
                continue
            dts = r.index.get_level_values(0)
            ru, rd = r[up.reindex(dts).values], r[~up.reindex(dts).values]
            yrs = {str(y): round(float(r[dts.year == y].mean() * 100), 2) for y in sorted(set(dts.year))}
            # simple daily portfolio: equal weight across that day's picks (max 5 by gain), compounded, for the BTST exits
            k = f"{gname} | exit {xname}"
            res[k] = dict(trades=int(len(r)), per_year=round(len(r) / 10.4, 0), avg=round(float(r.mean() * 100), 3), median=round(float(r.median() * 100), 3),
                          win=round(float((r > 0).mean() * 100)), nifty_up_days=round(float(ru.mean() * 100), 3), nifty_down_days=round(float(rd.mean() * 100), 3),
                          worst=round(float(r.min() * 100), 1), by_year=yrs)
            print("R|", k, {q: res[k][q] for q in ("trades", "avg", "median", "win", "nifty_up_days", "nifty_down_days")}, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/btst_test.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
