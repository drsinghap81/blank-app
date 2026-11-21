"""Industry results-season strength as a rotation clue (21 Nov 2026, Amritpal: "Yes" - the PSU banks reported +15-56% profit growth
between 14 Oct and 3 Nov 2026 at 6-11x earnings, just before their 5 Nov breakout).

Data: quarterly results with announcement dates (data/fundq shards: eps, net profit, 'known' = date the result was public), NSE basic
industries (group_pulse 'nse' rows; today's members - survivorship), Yahoo daily closes 2015 -> today, Nifty 50.
For every industry (3+ members with results) and every quarter end Q (2016 Q1 -> latest):
  event date  = the day 70% of its members had announced Q (only what was public that day is used)
  strength    = share of reporters with net profit up > 20% vs the same quarter a year earlier (prior-year profit > 0)
  accel       = share whose year-on-year growth improved vs the previous quarter's
  median YoY growth; valuation = median trailing P/E (price that day / last 4 quarters' EPS, positive EPS only)
Outcome from the next close: industry equal-weight return vs Nifty over 21 and 63 sessions; reached Leading (weekly RRG as the app)
within 8 weeks if not Leading at the event.
Report: rank correlation per quarter (IC) of strength / accel / median growth / cheapness with the outcome; top-fifth minus bottom-fifth
spread; 'strong + accelerating + cheap' (the PSU-bank profile) vs all; newest-first windows; by quarter-season.
PILOT env = 300 stocks from 2022. Output data/research/results_season.json"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sector_obv import download  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def quarters():
    Q = {}
    for f in glob.glob("data/fundq/*.json"):
        Q.update(json.load(open(f)))
    rows = []
    for s, v in Q.items():
        for x in v.get("q", []):
            if x.get("known") and x.get("end"):
                rows.append(dict(sym=s, end=pd.Timestamp(x["end"]), known=pd.Timestamp(x["known"]), eps=x.get("eps"), np_=x.get("np")))
    R = pd.DataFrame(rows).drop_duplicates(["sym", "end"]).sort_values(["sym", "end"])
    R["key"] = R.end.dt.year * 10 + R.end.dt.quarter
    prev = R.assign(key=R.key + 10)[["sym", "key", "np_"]].rename(columns={"np_": "np_ly"})
    R = R.merge(prev, on=["sym", "key"], how="left")
    R["yoy"] = np.where((R.np_ly > 0) & R.np_.notna(), (R.np_ / R.np_ly - 1) * 100, np.nan)
    R["yoy_prev"] = R.groupby("sym").yoy.shift(1)
    R["ttm_eps"] = R.groupby("sym").eps.transform(lambda s: s.rolling(4, min_periods=4).sum())
    return R


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    IND = {m["symbol"]: r["basic"] for r in G["nse"]["rows"] for m in r["members"]}
    R = quarters(); R = R[R.sym.isin(IND)]; R["ind"] = R.sym.map(IND)
    syms = sorted(R.sym.unique())
    if PILOT:
        syms = syms[:300]; R = R[R.sym.isin(syms)]
    print(f"R| results rows {len(R)}, stocks {R.sym.nunique()}, quarters {R.end.min().date()} -> {R.end.max().date()}", flush=True)
    C, _ = download(syms, "2021-06-01" if PILOT else "2015-06-01")
    C.index = pd.to_datetime(C.index).tz_localize(None)
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); nif = nif.reindex(C.index).ffill()
    members = {}
    for s, k in IND.items():
        if s in C.columns:
            members.setdefault(k, []).append(s)
    I = pd.DataFrame({k: (1 + ret[v].mean(axis=1).fillna(0)).cumprod() for k, v in members.items() if len(v) >= 3})
    W = I.resample("W-FRI").last(); NW = nif.resample("W-FRI").last()
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
    days = C.index
    ev = []
    for (ind, end), g in R[R.ind.isin(I.columns)].groupby(["ind", "end"]):
        g = g[g.known >= end]
        n_mem = len([s for s in members.get(ind, []) if s in set(R.sym)])
        if len(g) < 3 or n_mem < 3:
            continue
        kd = g.known.sort_values()
        need = int(np.ceil(0.7 * n_mem))
        if len(kd) < need:
            continue
        t = kd.iloc[need - 1]
        pos = days.searchsorted(t)
        if pos + 63 >= len(days) or pos < 1:
            continue
        t0 = days[pos]
        rep = g[g.known <= t]
        y = rep.yoy.dropna()
        if len(y) < 3:
            continue
        acc = rep.dropna(subset=["yoy", "yoy_prev"])
        pe = [C.at[t0, s] / e for s, e in zip(rep.sym, rep.ttm_eps) if s in C.columns and pd.notna(e) and e > 0 and pd.notna(C.at[t0, s])]
        f21 = (I[ind].iloc[pos + 21] / I[ind].iloc[pos] - 1 - (nif.iloc[pos + 21] / nif.iloc[pos] - 1)) * 100
        f63 = (I[ind].iloc[pos + 63] / I[ind].iloc[pos] - 1 - (nif.iloc[pos + 63] / nif.iloc[pos] - 1)) * 100
        wk = W.index.searchsorted(t0); q0 = Q[ind].iloc[wk - 1] if wk >= 1 else None
        toL = bool((Q[ind].iloc[wk:wk + 8] == "L").any())
        ev.append(dict(ind=ind, end=end, t=t0, n=len(rep), strong=float((y > 20).mean()), accel=float((acc.yoy > acc.yoy_prev).mean()) if len(acc) else np.nan,
                       med=float(y.median()), pe=float(np.median(pe)) if len(pe) >= 2 else np.nan, f21=f21, f63=f63, q0=q0, toL=toL))
    E = pd.DataFrame(ev)
    E = E[~((E.t >= "2020-02-15") & (E.t <= "2020-12-31"))]
    print(f"R| events {len(E)} ({E.ind.nunique()} industries, {E.end.nunique()} quarters), median reporters {E.n.median():.0f}", flush=True)
    res = dict(method=__doc__)

    def ic(col, out="f63", lo_good=False):
        v = E.groupby("end").apply(lambda g: ((-g[col]) if lo_good else g[col]).rank().corr(g[out].rank()) if g[col].notna().sum() >= 6 else np.nan)
        return round(float(v.mean()), 3), round(float(v.mean() / (v.std() / np.sqrt(v.notna().sum()))), 1) if v.notna().sum() > 2 else None

    def spread(col, out="f63", lo_good=False):
        def f(g):
            g = g.dropna(subset=[col])
            if len(g) < 10:
                return np.nan
            q = g[col].rank(pct=True); q = 1 - q if lo_good else q
            return g[q >= 0.8][out].mean() - g[q <= 0.2][out].mean()
        return round(float(E.groupby("end").apply(f).mean()), 2)
    out = {}
    for col, lg in (("strong", False), ("accel", False), ("med", False), ("pe", True)):
        out[col] = dict(ic21=ic(col, "f21", lg), ic63=ic(col, "f63", lg), top_minus_bottom_fifth_21=spread(col, "f21", lg), top_minus_bottom_fifth_63=spread(col, "f63", lg))
        print(f"R| {col}{' (cheaper = better)' if lg else ''}: {out[col]}", flush=True)
    res["signals"] = out
    E["pe_rank"] = E.groupby("end").pe.rank(pct=True)
    prof = (E.strong >= 0.5) & (E.accel >= 0.5) & (E.pe_rank <= 0.4)

    def st(x):
        nl = x[x.q0 != "L"]
        return dict(n=len(x), f21=round(float(x.f21.mean()), 2), f63=round(float(x.f63.mean()), 2), beat63=round(float((x.f63 > 0).mean() * 100)),
                    toL8=round(float(nl.toL.mean() * 100), 1) if len(nl) else None)
    sets = {"all": E.index == E.index, "half+ reporters up > 20%": E.strong >= 0.5, "growth accelerating in half+": E.accel >= 0.5,
            "PSU-bank profile: strong + accelerating + cheapest 40% P/E": prof, "strong + accelerating (any P/E)": (E.strong >= 0.5) & (E.accel >= 0.5),
            "weak: < 20% of reporters up > 20%": E.strong < 0.2}
    res["sets"] = {k: st(E[m]) for k, m in sets.items()}
    for k, v in res["sets"].items():
        print(f"R| {k}: {v}", flush=True)
    end_t = E.t.max()
    res["profile newest first"] = {f"last {y}y": st(E[prof & (E.t > end_t - pd.DateOffset(years=y))]) for y in (1, 2, 3, 5)}
    res["all newest first"] = {f"last {y}y": st(E[E.t > end_t - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)}
    print("R| profile newest first:", res["profile newest first"], flush=True)
    print("R| all newest first:", res["all newest first"], flush=True)
    psu = E[E.ind == "Public Sector Bank"].sort_values("end").tail(6)
    print("R| Public Sector Bank by quarter:", [(str(r.end.date()), str(r.t.date()), round(r.strong, 2), round(r.accel, 2) if pd.notna(r.accel) else None,
                                                  round(r.pe, 1) if pd.notna(r.pe) else None, round(r.f21, 1), round(r.f63, 1)) for r in psu.itertuples()], flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/results_season.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
