"""'Heavy turnover while price goes nowhere' as an early rotation clue (21 Nov 2026, Amritpal: "Yes" to testing the PSU-bank look-back
pattern across all industries).

Part A (this script, 2016 -> today, Yahoo daily close + volume, 1,889 NSE stocks in NSE sectors / 104+ basic industries; survivors):
  turnover x  = group's traded value over the last 5 sessions / its average over the 60 sessions before that
  flat        = group's 10-session return within +-3% (equal weight)
  SIGNAL      = turnover x >= 1.5 AND flat (the PSU banks, 14-27 Oct 2026)  - also x >= 2.0, and "heavy but moving" as a control
Weekly (Friday close) sampling; outcomes: next 4 / 8 weeks return vs Nifty 50; groups not already Leading: share reaching Leading
within 4 / 8 weeks (weekly RRG as the app); newest-first windows and ex-Covid.
Part B (PCR + FII, Jul 2024 on) is tools/research/quiet_turnover_pcr.py. PILOT env = 200 stocks from 2022.
Output data/research/quiet_turnover.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sector_obv import download  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def groups_frame(groups, C, V, ret, nif):
    val = (C * V).where(ret.notna())
    P, T = {}, {}
    for k, m in groups.items():
        m = [s for s in m if s in C.columns]
        if len(m) < 3:
            continue
        r = ret[m]; n = r.notna().sum(axis=1)
        P[k] = (1 + r.mean(axis=1).where(n >= 3).fillna(0)).cumprod()
        T[k] = val[m].sum(axis=1, min_count=1)
    P = pd.DataFrame(P); T = pd.DataFrame(T)
    tx = T.rolling(5).mean() / T.shift(5).rolling(60, min_periods=40).mean()
    r10 = (P / P.shift(10) - 1) * 100
    nifr = nif.reindex(P.index).ffill()
    W = P.resample("W-FRI").last(); NW = nifr.resample("W-FRI").last()
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
    f4 = (W.shift(-4) / W - 1).sub(NW.shift(-4) / NW - 1, axis=0) * 100
    f8 = (W.shift(-8) / W - 1).sub(NW.shift(-8) / NW - 1, axis=0) * 100
    txw = tx.resample("W-FRI").last(); r10w = r10.resample("W-FRI").last()
    rows = []
    for t in W.index:
        for k in W.columns:
            q = Q.at[t, k]
            if pd.isna(q) or pd.isna(txw.at[t, k]) or pd.isna(f4.at[t, k]):
                continue
            fut = Q[k].loc[t:]
            rows.append(dict(w=t, g=k, q=q, tx=float(txw.at[t, k]), r10=float(r10w.at[t, k]), f4=float(f4.at[t, k]),
                             f8=float(f8.at[t, k]) if pd.notna(f8.at[t, k]) else np.nan,
                             L4=bool((fut.iloc[1:5] == "L").any()), L8=bool((fut.iloc[1:9] == "L").any())))
    X = pd.DataFrame(rows)
    X = X[~((X.w >= "2020-02-15") & (X.w <= "2020-12-31"))].copy()
    t = txw.index[-1]   # latest week (no outcome yet): groups showing the pattern now
    X.attrs["now"] = sorted([(k, round(float(txw.at[t, k]), 2), round(float(r10w.at[t, k]), 1), Q[k].dropna().iloc[-1] if Q[k].notna().any() else None)
                             for k in txw.columns if pd.notna(txw.at[t, k]) and txw.at[t, k] >= 1.5 and abs(r10w.at[t, k]) <= 3], key=lambda z: -z[1])
    X.attrs["now_date"] = str(t.date())
    return X


def st(x):
    nl = x[x.q != "L"]
    return dict(n=len(x), f4=round(float(x.f4.mean()), 2) if len(x) else None, up4=round(float((x.f4 > 0).mean() * 100)) if len(x) else None,
                f8=round(float(x.f8.mean()), 2) if len(x) else None, toL4=round(float(nl.L4.mean() * 100), 1) if len(nl) else None,
                toL8=round(float(nl.L8.mean() * 100), 1) if len(nl) else None)


def analyse(name, X, res):
    flat = X.r10.abs() <= 3
    sets = {"all group-weeks": X.index == X.index, "flat (10-day within +-3%), normal turnover": flat & (X.tx < 1.2),
            "SIGNAL: turnover >= 1.5x and flat": flat & (X.tx >= 1.5), "SIGNAL strong: turnover >= 2x and flat": flat & (X.tx >= 2.0),
            "control: turnover >= 1.5x and price up > 3%": (X.tx >= 1.5) & (X.r10 > 3), "control: turnover >= 1.5x and price down > 3%": (X.tx >= 1.5) & (X.r10 < -3),
            "SIGNAL in Lagging / Improving only": flat & (X.tx >= 1.5) & X.q.isin(["G", "I"])}
    out = {k: st(X[m]) for k, m in sets.items()}
    end = X.w.max(); sig = flat & (X.tx >= 1.5)
    out["SIGNAL newest first"] = {f"last {y}y": st(X[sig & (X.w > end - pd.DateOffset(years=y))]) for y in (1, 2, 3, 5)}
    out["all newest first"] = {f"last {y}y": st(X[X.w > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)}
    res[name] = out
    for k, v in out.items():
        print(f"R| {name} | {k}: {v}", flush=True)
    print(f"R| {name} | showing the pattern now ({X.attrs.get('now_date')}): {X.attrs.get('now', [])[:15]}", flush=True)


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    SEC, IND = {}, {}
    for r in G["nse"]["rows"]:
        for m in r["members"]:
            SEC[m["symbol"]] = r.get("sector"); IND[m["symbol"]] = r["basic"]
    syms = sorted(SEC)[:200] if PILOT else sorted(SEC)
    C, V = download(syms, "2022-01-01" if PILOT else "2015-06-01")
    C.index = pd.to_datetime(C.index).tz_localize(None); V.index = C.index
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    print(f"R| stocks {C.shape[1]} {C.index[0].date()} -> {C.index[-1].date()}", flush=True)
    res = dict(method=__doc__)
    secs, inds = {}, {}
    for s, k in SEC.items():
        if k:
            secs.setdefault(k, []).append(s)
    for s, k in IND.items():
        inds.setdefault(k, []).append(s)
    analyse("sectors", groups_frame({k: v for k, v in secs.items() if len(v) >= 3}, C, V, ret, nif), res)
    analyse("industries", groups_frame({k: v for k, v in inds.items() if len([s for s in v if s in C.columns]) >= 5}, C, V, ret, nif), res)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/quiet_turnover.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
