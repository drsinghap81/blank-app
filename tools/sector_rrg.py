"""Relative rotation of NSE's official sector indices vs Nifty 50 (20 Nov 2026, Amritpal: a cleaner version of the sector RRG he
uses elsewhere). Source: data/scan/index_ohlcv.csv.gz (NSE ind_close_all, 2016 ->). Two views:
  weekly : RS-ratio = 100 x RS / 10-week avg RS; momentum = 3-week avg of 100 x ratio / last week's ratio; last 8 weeks
  daily  : RS-ratio = 100 x RS / 50-day avg RS; momentum = 5-day avg of 100 x ratio / ratio 10 days ago; last 10 sessions
(same formulas as tools/group_pulse.py rrg and the backtests). Output: data/scan/sector_rrg.json"""
import json
import os

import pandas as pd

SRC = "data/scan/index_ohlcv.csv.gz"; OUT = "data/scan/sector_rrg.json"
NAMES = {"NIFTY BANK": "Bank Nifty", "NIFTY PRIVATE BANK": "Pvt Bank", "NIFTY PSU BANK": "PSU Bank", "NIFTY FINANCIAL SERVICES": "Fin Services",
         "NIFTY CAPITAL MARKETS": "Capital Mkts", "NIFTY IT": "IT", "NIFTY PHARMA": "Pharma", "NIFTY HEALTHCARE INDEX": "Healthcare",
         "NIFTY FMCG": "FMCG", "NIFTY AUTO": "Auto", "NIFTY METAL": "Metal", "NIFTY ENERGY": "Energy", "NIFTY OIL & GAS": "Oil & Gas",
         "NIFTY REALTY": "Realty", "NIFTY MEDIA": "Media", "NIFTY INFRASTRUCTURE": "Infra", "NIFTY COMMODITIES": "Commodities",
         "NIFTY CONSUMER DURABLES": "Cons Durables", "NIFTY INDIA CONSUMPTION": "Consumption", "NIFTY INDIA DEFENCE": "Defence",
         "NIFTY CPSE": "CPSE", "NIFTY PSE": "PSE", "NIFTY MNC": "MNC", "NIFTY SERVICES SECTOR": "Services",
         "NIFTY MIDCAP 150": "Midcap 150", "NIFTY SMALLCAP 250": "Smallcap 250"}
Q = lambda x, y: "Leading" if x >= 100 and y >= 100 else "Weakening" if x >= 100 else "Lagging" if y < 100 else "Improving"  # noqa: E731


def view(C, bench, avg, step, smooth, n, names=None):
    names = names or NAMES
    rs = 100 * C.div(bench, axis=0); ratio = 100 * rs / rs.rolling(avg).mean(); mom = (100 * ratio / ratio.shift(step)).rolling(smooth).mean()
    out = {}
    for k in C.columns:
        p = pd.concat([ratio[k], mom[k]], axis=1).dropna().iloc[-n:]
        if len(p) < 3:
            continue
        P = [[str(i.date()), round(float(a), 2), round(float(b), 2)] for i, (a, b) in p.iterrows()]
        out[names[k]] = dict(index=k, pts=P, now=Q(P[-1][1], P[-1][2]), was=Q(P[0][1], P[0][2]))
    return out


def main():
    d = pd.read_csv(SRC, parse_dates=["Date"])
    C = d.pivot_table(index="Date", columns="INDEX", values="Close").sort_index()
    bench = C["NIFTY 50"]; C = C[[k for k in NAMES if k in C.columns]]
    W = C.resample("W-FRI").last(); BW = bench.resample("W-FRI").last()
    if W.index[-1] > C.index[-1]:
        W.index = list(W.index[:-1]) + [C.index[-1]]; BW.index = W.index
    out = dict(asof=str(C.index[-1].date()), bench="Nifty 50", weekly=view(W, BW, 10, 1, 3, 8), daily=view(C, bench, 50, 10, 5, 10),
               method=__doc__)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    for v in ("weekly", "daily"):
        print(v, {q: [k for k, r in out[v].items() if r["now"] == q] for q in ("Leading", "Improving", "Weakening", "Lagging")})


if __name__ == "__main__":
    main()
