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


def view(C, bench, avg, step, smooth, n, names=None, partial=False):
    """25 Nov 2026 (Amritpal: "S&P 500 leading - is it correct?"): `now` is the last COMPLETED period - with a part week (partial=True)
    the label uses last Friday and the part week is `live` (the chart still draws it as the tail end); `was` is the period before `now`
    (it used to be the first point of the 8-week tail, so "moved this week" compared with 8 weeks ago); `start` = that first point."""
    names = names or NAMES
    rs = 100 * C.div(bench, axis=0); ratio = 100 * rs / rs.rolling(avg).mean(); mom = (100 * ratio / ratio.shift(step)).rolling(smooth).mean()
    out = {}
    for k in C.columns:
        p = pd.concat([ratio[k], mom[k]], axis=1).dropna().iloc[-n:]
        if len(p) < 3:
            continue
        P = [[str(i.date()), round(float(a), 2), round(float(b), 2)] for i, (a, b) in p.iterrows()]
        j = -2 if partial and len(P) >= 3 else -1
        out[names[k]] = dict(index=k, pts=P, now=Q(P[j][1], P[j][2]), was=Q(P[j - 1][1], P[j - 1][2]), start=Q(P[0][1], P[0][2]),
                             live=Q(P[-1][1], P[-1][2]) if j == -2 else None, partial=j == -2)
    return out


def history(C, bench, avg, step, smooth, names, keep):
    """21 Nov 2026 (Amritpal: "store sector rotation data so we can later see how the dots moved"): every point of every sector,
    {date: {name: [ratio, momentum]}} for the last `keep` periods (rebuilt from prices each run, so it is always complete)"""
    rs = 100 * C.div(bench, axis=0); ratio = 100 * rs / rs.rolling(avg).mean(); mom = (100 * ratio / ratio.shift(step)).rolling(smooth).mean()
    out = {}
    for d in ratio.index[-keep:]:
        row = {names[k]: [round(float(ratio.at[d, k]), 2), round(float(mom.at[d, k]), 2)] for k in C.columns if pd.notna(ratio.at[d, k]) and pd.notna(mom.at[d, k])}
        if row:
            out[str(d.date())] = row
    return out


def write_hist(path, C, bench, W, BW, names):
    h = dict(weekly=history(W, BW, 10, 1, 3, names, 104), daily=history(C, bench, 50, 10, 5, names, 260))
    json.dump(h, open(path, "w"), separators=(",", ":"))
    print("history", path, "weekly", len(h["weekly"]), "daily", len(h["daily"]))


def main():
    d = pd.read_csv(SRC, parse_dates=["Date"])
    C = d.pivot_table(index="Date", columns="INDEX", values="Close").sort_index()
    bench = C["NIFTY 50"]; C = C[[k for k in NAMES if k in C.columns]]
    W = C.resample("W-FRI").last(); BW = bench.resample("W-FRI").last(); part = bool(W.index[-1] > C.index[-1])
    if part:
        W.index = list(W.index[:-1]) + [C.index[-1]]; BW.index = W.index
    out = dict(asof=str(C.index[-1].date()), bench="Nifty 50", weekly=view(W, BW, 10, 1, 3, 8, partial=part), daily=view(C, bench, 50, 10, 5, 10),
               method=__doc__)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    write_hist(OUT.replace(".json", "_hist.json"), C, bench, W, BW, NAMES)
    for v in ("weekly", "daily"):
        print(v, {q: [k for k, r in out[v].items() if r["now"] == q] for q in ("Leading", "Improving", "Weakening", "Lagging")})


if __name__ == "__main__":
    main()
