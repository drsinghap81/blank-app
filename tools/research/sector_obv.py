"""Sector / industry OBV divergence as an early rotation clue (21 Nov 2026, Amritpal: "price rise volume fall, price fall volume
rise is disagreement - can it give some clue, or on balance volume rising / falling" -> "Yes do").

Universe: liquid NSE stocks with an NSE sector / basic industry (group_pulse 'nse' rows; today's members, survivors), Yahoo daily
2016 -> today (close + volume, adjusted). Groups: NSE sectors (3+ stocks) and NSE basic industries (5+ stocks).
Daily, per group:
  price index = equal-weight member returns; RS vs Nifty 50
  OBV         = cumulative sum over members of sign(daily return) x traded value, divided by the group's 50-day average daily
                traded value (so groups of any size are comparable; units = "average days of value")
Weekly (Friday close) features:
  obv10   = OBV change over the last 10 sessions (in average days)
  rs10    = group return minus Nifty's over the last 10 sessions (%)
  bull divergence = obv10 in the group's top third that week while rs10 < 0 (volume on up days dominates, price lagging)
  bear divergence = obv10 in the bottom third while rs10 > 0
Outcomes: next 4-week return vs Nifty; for groups not yet Improving / Leading (weekly RRG as the app), share that reach Improving or
Leading within 4 weeks. Rank correlation (IC) of obv10 with the next 4 weeks, alone and after removing price momentum (RS-momentum).
Newest-first windows (last 1 / 2 / 3 / 5 years), ex-Covid. PILOT env = 200 stocks, from 2023. Output data/research/sector_obv.json"""
import json
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

PILOT = bool(os.environ.get("PILOT"))


def download(syms, start):
    C, V = {}, {}
    for a in range(0, len(syms), 100):
        ch = [s + ".NS" for s in syms[a:a + 100]]
        for k in range(3):
            try:
                d = yf.download(ch, start=start, interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20 * (k + 1)); d = None
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                c, v = d["Close"][t], d["Volume"][t]
            except Exception:  # noqa: BLE001
                continue
            if c.notna().sum() > 120:
                C[t[:-3]] = c; V[t[:-3]] = v
        print("downloaded", a + len(ch), len(C), flush=True); time.sleep(2)
    return pd.DataFrame(C).sort_index(), pd.DataFrame(V).sort_index()


def ic(g, col):
    if len(g) < 6 or g[col].nunique() < 3:
        return np.nan
    return g[col].rank().corr(g.fwd4.rank())


def analyse(name, groups, C, V, ret, nif, res):
    val = (C * V).where(ret.notna())
    P, O = {}, {}
    for k, m in groups.items():
        m = [s for s in m if s in C.columns]
        if len(m) < 3:
            continue
        r = ret[m]; n = r.notna().sum(axis=1)
        P[k] = (1 + r.mean(axis=1).where(n >= 3).fillna(0)).cumprod()
        tv = val[m].sum(axis=1, min_count=1)
        flow = (np.sign(r) * val[m]).sum(axis=1, min_count=1)
        O[k] = (flow / tv.rolling(50, min_periods=30).mean()).fillna(0).cumsum()
    P = pd.DataFrame(P); O = pd.DataFrame(O)
    nifr = nif.reindex(P.index).ffill()
    rs10 = (P / P.shift(10) - 1).sub(nifr / nifr.shift(10) - 1, axis=0) * 100
    obv10 = O - O.shift(10)
    W = P.resample("W-FRI").last(); NW = nifr.resample("W-FRI").last()
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
    fwd = (W.shift(-4) / W - 1).sub(NW.shift(-4) / NW - 1, axis=0) * 100
    o10 = obv10.resample("W-FRI").last(); r10 = rs10.resample("W-FRI").last()
    rows = []
    for t in W.index:
        for k in W.columns:
            q = Q.at[t, k]
            if pd.isna(q) or pd.isna(o10.at[t, k]) or pd.isna(fwd.at[t, k]):
                continue
            fut = Q[k].loc[t:].iloc[1:5]
            rows.append(dict(w=t, g=k, q=q, obv10=float(o10.at[t, k]), rs10=float(r10.at[t, k]), mom=float(mom.at[t, k]), fwd4=float(fwd.at[t, k]),
                             to_IL=bool(fut.isin(["I", "L"]).any()), to_L=bool((fut == "L").any())))
    X = pd.DataFrame(rows)
    X["terc"] = X.groupby("w").obv10.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=[0, 1, 2]).astype(int) if len(s) >= 6 else np.nan)
    X["bull"] = (X.terc == 2) & (X.rs10 < 0); X["bear"] = (X.terc == 0) & (X.rs10 > 0)
    X = X[~((X.w >= "2020-02-15") & (X.w <= "2020-12-31"))]           # Covid treated as an exception
    out = dict(groups=int(X.g.nunique()), weeks=int(X.w.nunique()), group_weeks=len(X))

    def st(x):
        return dict(n=len(x), fwd4=round(float(x.fwd4.mean()), 2) if len(x) else None, up=round(float((x.fwd4 > 0).mean() * 100)) if len(x) else None)
    out["all"] = st(X)
    out["OBV top third"] = st(X[X.terc == 2]); out["OBV bottom third"] = st(X[X.terc == 0])
    out["bull divergence (OBV top third, price lagging)"] = st(X[X.bull]); out["bear divergence (OBV bottom third, price leading)"] = st(X[X.bear])
    out["agreement up (OBV top third, price leading)"] = st(X[(X.terc == 2) & (X.rs10 > 0)])
    out["agreement down (OBV bottom third, price lagging)"] = st(X[(X.terc == 0) & (X.rs10 < 0)])
    lag = X[X.q.isin(["G", "W"])]
    out["Lagging/Weakening: reach Improving or Leading in 4 weeks"] = {
        "bull divergence": round(float(lag[lag.bull].to_IL.mean() * 100), 1) if lag.bull.any() else None,
        "OBV bottom third": round(float(lag[lag.terc == 0].to_IL.mean() * 100), 1), "all": round(float(lag.to_IL.mean() * 100), 1),
        "n bull": int(lag.bull.sum())}
    imp = X[X.q == "I"]
    out["Improving: reach Leading in 4 weeks"] = {"OBV top third": round(float(imp[imp.terc == 2].to_L.mean() * 100), 1),
                                                   "OBV bottom third": round(float(imp[imp.terc == 0].to_L.mean() * 100), 1),
                                                   "all": round(float(imp.to_L.mean() * 100), 1)}
    end = X.w.max(); ics = {}
    for lbl, x in [("all", X)] + [(f"last {y}y", X[X.w > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)]:
        def resid(g):
            if len(g) < 6:
                return np.nan
            a, b = g.obv10.rank(), g.mom.rank(); beta = np.polyfit(b, a, 1)[0] if b.std() > 0 else 0
            return (a - beta * b).corr(g.fwd4.rank())
        ics[lbl] = dict(obv=round(float(x.groupby("w").apply(lambda g: ic(g, "obv10")).mean()), 3),
                        momentum=round(float(x.groupby("w").apply(lambda g: ic(g, "mom")).mean()), 3),
                        obv_after_momentum=round(float(x.groupby("w").apply(resid).mean()), 3), weeks=int(x.w.nunique()))
    out["rank correlation with next 4 weeks"] = ics
    res[name] = out
    for k, v in out.items():
        print(f"R| {name} | {k}: {v}", flush=True)
    # latest divergences (all weeks, Covid filter irrelevant now)
    t = o10.index[-1]
    latest = []
    for k in o10.columns:
        if pd.notna(o10.at[t, k]) and pd.notna(r10.at[t, k]):
            latest.append((k, round(float(o10.at[t, k]), 2), round(float(r10.at[t, k]), 2), Q[k].dropna().iloc[-1] if Q[k].notna().any() else None))
    latest.sort(key=lambda x: -x[1])
    print(f"R| {name} | latest {t.date()} (OBV 10d, RS 10d %, quadrant) top: {latest[:6]} bottom: {latest[-6:]}", flush=True)


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    SEC, IND = {}, {}
    for r in G["nse"]["rows"]:
        for m in r["members"]:
            SEC[m["symbol"]] = r.get("sector"); IND[m["symbol"]] = r["basic"]
    syms = sorted(SEC)
    if PILOT:
        syms = syms[:200]
    C, V = download(syms, "2022-06-01" if PILOT else "2015-06-01")
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); C.index = pd.to_datetime(C.index).tz_localize(None)
    V.index = C.index; ret.index = C.index
    print(f"R| stocks {C.shape[1]} from {C.index[0].date()} to {C.index[-1].date()}", flush=True)
    res = dict(method=__doc__)
    secs = {}
    for s, k in SEC.items():
        if k:
            secs.setdefault(k, []).append(s)
    inds = {}
    for s, k in IND.items():
        inds.setdefault(k, []).append(s)
    analyse("sectors", {k: v for k, v in secs.items() if len(v) >= 3}, C, V, ret, nif, res)
    analyse("industries", {k: v for k, v in inds.items() if len([s for s in v if s in C.columns]) >= 5}, C, V, ret, nif, res)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/sector_obv.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
