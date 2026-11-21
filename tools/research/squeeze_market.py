"""Market-wide short squeeze after a falling market (21 Nov 2026, Amritpal: "in the PSU bank thing one thing was a short squeeze, as
markets were continuously falling").

The Nov 2026 move: Nifty fell through October, FIIs were extremely short index futures (long % 9-12), then covered (13.6 on 4 Nov ->
21.5 on 5 Nov -> 37 by 12 Nov) and high-beta sectors (PSU banks) led. Test 2016 -> today:
  data   : NSE participant-wise OI (FII index-futures long %, tools/research/fii_oi_filter.fii_series), sector indices
           (data/scan/index_ohlcv.csv.gz)
  setup  : market fell - Nifty >= 5% below its 60-day high - while FIIs are extremely short (long % <= 20)
  trigger: (a) FII long % up >= 5 points over 3 sessions from <= 20 (covering starts)   (b) a Nifty up-day >= 1.5% during the setup
           (c) both on the same day. One event per 20 sessions.
Outcomes: Nifty next 5/10/20/60 sessions vs all days; each sector index's next 20 / 60 sessions vs Nifty, and whether the sectors that
fell MOST in the 20 sessions before (or the high-beta ones) lead - rank correlation and top-3 vs bottom-3 spread. Lists every event.
Output data/research/squeeze_market.json"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fii_oi_filter import fii_series, one  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def events(mask, gap=20):
    out, last = [], -999
    idx = list(mask.index)
    for i, (t, m) in enumerate(mask.items()):
        if m and i - last > gap:
            out.append(t); last = i
    return out


def main():
    if PILOT:      # FII files for Aug-Nov 2026 only (coverage check)
        rows = [r for r in map(one, pd.bdate_range("2026-08-01", pd.Timestamp.today())) if r]
        F = pd.DataFrame(rows, columns=["Date", "fl", "fs", "cl", "cs"]).set_index("Date").sort_index(); F["long"] = F.fl / (F.fl + F.fs) * 100
        print("R| pilot FII", len(F), F.index.min(), F.index.max(), F["long"].round(1).tail(15).to_dict(), flush=True)
    else:
        F = fii_series()
    d = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
    C = d.pivot_table(index="Date", columns="INDEX", values="Close").sort_index()
    nif = C["NIFTY 50"]; secs = [k for k in C.columns if k not in ("NIFTY 50", "NIFTY 500")]
    F = F.reindex(C.index).ffill(limit=3)
    L = F["long"]
    dd = nif / nif.rolling(60).max() - 1
    setup = (dd <= -0.05) & (L <= 20)
    trigA = setup & (L - L.shift(3) >= 5) & (L.shift(3) <= 20)
    trigB = setup & (nif.pct_change() >= 0.015)
    trigC = trigA & trigB
    fw = {k: (nif.shift(-k) / nif - 1) * 100 for k in (5, 10, 20, 60)}
    res = dict(method=__doc__, fii_days=int(L.notna().sum()), base={})
    base_idx = nif.index[:-60]
    res["base"] = {f"{k}d": round(float(fw[k].reindex(base_idx).mean()), 2) for k in fw}
    print("R| FII days", int(L.notna().sum()), "| Nifty any day:", res["base"], "| setup days", int(setup.sum()), flush=True)
    beta = {}
    r = C.pct_change()
    for s in secs:
        x = r[[s, "NIFTY 50"]].dropna()
        beta[s] = float(x[s].cov(x["NIFTY 50"]) / x["NIFTY 50"].var()) if len(x) > 250 else np.nan
    for nm, m in (("A FII covering from <= 20%", trigA), ("B Nifty +1.5% day in a falling market", trigB), ("C both same day", trigC),
                  ("setup day (falling market + FII <= 20%)", setup)):
        E = [t for t in events(m.fillna(False)) if t <= nif.index[-21]]
        o = {"n": len(E)}
        for k in fw:
            v = fw[k].reindex(E).dropna()
            o[f"{k}d"] = (round(float(v.mean()), 2), round(float((v > 0).mean() * 100))) if len(v) else None
        # sectors after the event
        rows = []
        for t in E:
            i = C.index.get_loc(t)
            if i + 20 >= len(C) or i < 20:
                continue
            for s in secs:
                if pd.isna(C[s].iloc[i]) or pd.isna(C[s].iloc[i - 20]):
                    continue
                prior = (C[s].iloc[i] / C[s].iloc[i - 20] - 1 - (nif.iloc[i] / nif.iloc[i - 20] - 1)) * 100
                f20 = (C[s].iloc[i + 20] / C[s].iloc[i] - 1 - (nif.iloc[i + 20] / nif.iloc[i] - 1)) * 100
                f60 = (C[s].iloc[min(i + 60, len(C) - 1)] / C[s].iloc[i] - 1 - (nif.iloc[min(i + 60, len(C) - 1)] / nif.iloc[i] - 1)) * 100
                rows.append(dict(t=t, s=s, prior=prior, f20=f20, f60=f60, beta=beta.get(s)))
        S = pd.DataFrame(rows)
        if len(S):
            ic_fall = S.groupby("t").apply(lambda g: (-g.prior).rank().corr(g.f20.rank())).mean()
            ic_beta = S.groupby("t").apply(lambda g: g.beta.rank().corr(g.f20.rank())).mean()
            sp = S.groupby("t").apply(lambda g: g.nsmallest(3, "prior").f20.mean() - g.nlargest(3, "prior").f20.mean()).mean()
            spb = S.groupby("t").apply(lambda g: g.nlargest(3, "beta").f20.mean() - g.nsmallest(3, "beta").f20.mean()).mean()
            o["sectors: fell most before -> lead next 20d (rank corr)"] = round(float(ic_fall), 2)
            o["sectors: 3 that fell most minus 3 that held best, next 20d"] = round(float(sp), 2)
            o["sectors: high beta lead (rank corr)"] = round(float(ic_beta), 2)
            o["sectors: 3 highest beta minus 3 lowest, next 20d"] = round(float(spb), 2)
            o["by sector, avg next 20d / 60d vs Nifty"] = {s: (round(float(g.f20.mean()), 1), round(float(g.f60.mean()), 1)) for s, g in S.groupby("s")}
        o["events"] = [(str(t.date()), round(float(L.get(t, np.nan)), 1), round(float(dd.get(t, np.nan)) * 100, 1),
                        round(float(fw[20].get(t, np.nan)), 1) if pd.notna(fw[20].get(t, np.nan)) else None) for t in E]
        res[nm] = o
        for k, v in o.items():
            print(f"R| {nm} | {k}: {v}", flush=True)
    recent = [(str(t.date()), round(float(L[t]), 1), round(float(dd[t]) * 100, 1)) for t in trigA.index[trigA.fillna(False)] if t >= pd.Timestamp("2026-09-01")]
    print("R| recent covering triggers (date, FII long %, Nifty from 60-day high %):", recent, flush=True)
    print("R| sector betas:", {k: round(v, 2) for k, v in sorted(beta.items(), key=lambda z: -(z[1] or 0))}, flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/squeeze_market.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
