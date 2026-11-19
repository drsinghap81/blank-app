"""Do stocks entering the Nifty 50 run up before the rebalance? (19 Nov 2026, Amritpal: "Yes")

Events: Nifty 50 replacements 2017-2026 (Wikipedia list + NSE press release of 10 Aug 2026). T = last session before the change takes
effect (index funds buy at that close). NSE announces scheduled changes about 4-7 weeks before T; brokers predict them months earlier
from free-float market-cap ranks, so three windows (sessions relative to T):
  anticipation  T-60 .. T-30   (mostly before the announcement)
  run-in        T-30 .. T      (announcement -> index-fund buying)
  after         T .. T+20
Return of the stock minus Nifty over the same window. Exclusions are shown too (should be the mirror image).
'special' = unscheduled change (merger, demerger, Yes Bank) - shown separately. Output: data/research/index_inclusion.json"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

INC = [("2017-03-31", "IBULHSGFIN", "SAMMAANCAP"), ("2017-03-31", "IOC", "IOC"), ("2017-05-26", "VEDL", "VEDL", "special"),
       ("2017-09-29", "BAJFINANCE", "BAJFINANCE"), ("2017-09-29", "HINDPETRO", "HINDPETRO"), ("2017-09-29", "UPL", "UPL"),
       ("2018-04-02", "BAJAJFINSV", "BAJAJFINSV"), ("2018-04-02", "GRASIM", "GRASIM"), ("2018-04-02", "TITAN", "TITAN"),
       ("2018-09-28", "JSWSTEEL", "JSWSTEEL"), ("2019-03-29", "BRITANNIA", "BRITANNIA"), ("2019-09-27", "NESTLEIND", "NESTLEIND"),
       ("2020-03-19", "SHREECEM", "SHREECEM", "special"), ("2020-07-31", "HDFCLIFE", "HDFCLIFE", "special"),
       ("2020-09-25", "SBILIFE", "SBILIFE"), ("2020-09-25", "DIVISLAB", "DIVISLAB"), ("2021-03-31", "TATACONSUM", "TATACONSUM"),
       ("2022-03-31", "APOLLOHOSP", "APOLLOHOSP"), ("2022-09-30", "ADANIENT", "ADANIENT"), ("2023-07-13", "LTIM", "LTIM", "special"),
       ("2024-03-28", "SHRIRAMFIN", "SHRIRAMFIN"), ("2024-09-30", "BEL", "BEL"), ("2024-09-30", "TRENT", "TRENT"),
       ("2025-03-28", "JIOFIN", "JIOFIN"), ("2025-03-28", "ZOMATO", "ETERNAL"), ("2025-09-30", "INDIGO", "INDIGO"),
       ("2025-09-30", "MAXHEALTH", "MAXHEALTH"), ("2026-09-30", "BSE", "BSE")]
EXC = [("2017-03-31", "BHEL", "BHEL"), ("2017-03-31", "IDEA", "IDEA"), ("2017-09-29", "ACC", "ACC"), ("2017-09-29", "BANKBARODA", "BANKBARODA"),
       ("2017-09-29", "TATAPOWER", "TATAPOWER"), ("2018-04-02", "AMBUJACEM", "AMBUJACEM"), ("2018-04-02", "AUROPHARMA", "AUROPHARMA"),
       ("2018-04-02", "BOSCHLTD", "BOSCHLTD"), ("2018-09-28", "LUPIN", "LUPIN"), ("2019-03-29", "HINDPETRO", "HINDPETRO"),
       ("2019-09-27", "IBULHSGFIN", "SAMMAANCAP"), ("2020-09-25", "ZEEL", "ZEEL"), ("2021-03-31", "GAIL", "GAIL"), ("2022-03-31", "IOC", "IOC"),
       ("2022-09-30", "SHREECEM", "SHREECEM"), ("2024-03-28", "UPL", "UPL"), ("2024-09-30", "DIVISLAB", "DIVISLAB"), ("2024-09-30", "LTIM", "LTIM"),
       ("2025-03-28", "BPCL", "BPCL"), ("2025-03-28", "BRITANNIA", "BRITANNIA"), ("2025-09-30", "HEROMOTOCO", "HEROMOTOCO"),
       ("2025-09-30", "INDUSINDBK", "INDUSINDBK"), ("2026-09-30", "WIPRO", "WIPRO")]
WIN = {"anticipation T-60..T-30": (-60, -30), "run-in T-30..T": (-30, 0), "after T..T+20": (0, 20), "whole T-60..T": (-60, 0)}


def main():
    tick = sorted({e[2] + ".NS" for e in INC + EXC})
    D = yf.download(tick + ["^NSEI"], start="2016-06-01", auto_adjust=True, progress=False)["Close"]
    D.index = pd.to_datetime(D.index).tz_localize(None)
    nif = D["^NSEI"].ffill()
    res = dict(method=__doc__)
    for side, ev in (("inclusions", INC), ("exclusions", EXC)):
        rows = []
        for e in ev:
            dt, name, yt = e[0], e[1], e[2] + ".NS"; special = len(e) > 3
            s = D[yt].dropna() if yt in D else pd.Series(dtype=float)
            if s.empty:
                print("no data", name); continue
            idx = s.index; i = idx.searchsorted(pd.Timestamp(dt)) - 1      # last session before the effective date
            if i < 0:
                continue
            row = dict(date=dt, stock=name, special=special)
            for k, (a, b) in WIN.items():
                if i + a < 0 or i + b >= len(idx):
                    row[k] = None; continue
                d0, d1 = idx[i + a], idx[i + b]
                r = s.iloc[i + b] / s.iloc[i + a] - 1; n = nif.loc[d1] / nif.loc[d0] - 1
                row[k] = round(float((r - n) * 100), 1)
            rows.append(row); print("E|", side, row, flush=True)
        T = pd.DataFrame(rows)
        out = dict(events=rows)
        for grp, m in (("scheduled", ~T.special), ("all", T.special | ~T.special)):
            out[grp] = {k: dict(n=int(T.loc[m, k].notna().sum()), avg=round(float(T.loc[m, k].mean()), 1), median=round(float(T.loc[m, k].median()), 1),
                                beat_nifty=round(float((T.loc[m, k].dropna() > 0).mean() * 100))) for k in WIN}
            print("R|", side, grp, out[grp], flush=True)
        res[side] = out
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/index_inclusion.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
