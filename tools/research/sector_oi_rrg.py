"""Does futures OI build-up lead sector rotation? (21 Nov 2026, Amritpal: "is sector rotation having any relation with money flow,
OI or option data" -> "you can do a pilot run first").

Data (NSE public archives): F&O bhavcopy UDiFF (stock futures, all expiries: open interest summed per stock per day) and the CM
bhavcopy (closes), Jul 2024 -> today (UDiFF starts Jul 2024). Sector = NSE's own sector of each F&O stock (group_pulse 'nse' rows).
Weekly (Friday), per sector with 3+ F&O stocks:
  sector price index  = equal-weight of member stock returns (CM closes)
  RRG vs Nifty 50     = same formula as the app: RS-ratio = 100 x RS / 10-week avg; RS-momentum = 3-week avg of 100 x ratio / last
  OI build-up         = (stocks with price up & OI up > 2%) - (stocks with price down & OI up > 2%), as a share of members ("long
                        minus short build-up"); also total futures OI change % and short-covering share (price up, OI down)
Tests, using the build-up known at week t's close:
  1. next 4-week sector return vs Nifty by build-up tercile (all sector-weeks; and within each quadrant)
  2. Improving sectors: share that reach Leading within 4 weeks, by build-up tercile
  3. rank correlation of build-up with the next 4 weeks' excess return, vs the same for RS-momentum (price) alone, and build-up
     after removing RS-momentum (residual)
PILOT env = last 70 sessions (prints coverage, no tests). Output data/research/sector_oi_rrg.json"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import nse_bhav  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
CACHE = "/tmp/nse_fo"


def fo(d):
    ymd = d.strftime("%Y%m%d"); os.makedirs(CACHE, exist_ok=True); p = f"{CACHE}/{ymd}.pkl"
    if os.path.exists(p):
        return pd.read_pickle(p)
    for _ in range(3):
        try:
            r = requests.get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip", headers=H, timeout=40)
            if r.status_code == 404:
                return None
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); b = pd.read_csv(z.open(z.namelist()[0]))
                b = b[b.FinInstrmTp == "STF"]
                out = b.groupby("TckrSymb").OpnIntrst.sum().astype(float)
                out.to_pickle(p); return out
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    SEC = {m["symbol"]: r.get("sector") for r in G["nse"]["rows"] for m in r["members"]}
    end = date.today(); start = end - timedelta(days=105 if PILOT else 880)
    start = max(start, date(2024, 7, 8))
    OI, CL = {}, {}
    d = start; n = 0
    while d <= end:
        if d.weekday() < 5:
            o = fo(d)
            if o is not None:
                c = nse_bhav.bhav(d)
                if c is not None:
                    OI[pd.Timestamp(d)] = o; CL[pd.Timestamp(d)] = c.Close; n += 1
                    if n % 50 == 0:
                        print("sessions", n, d, flush=True)
            time.sleep(0.3)
        d += timedelta(days=1)
    OI = pd.DataFrame(OI).T.sort_index(); CL = pd.DataFrame(CL).T.sort_index()
    syms = [s for s in OI.columns if s in CL.columns and SEC.get(s)]
    OI, CL = OI[syms], CL[syms]
    print(f"R| sessions {len(OI)} ({OI.index[0].date()} -> {OI.index[-1].date()}), F&O stocks with a sector {len(syms)}, "
          f"unmapped F&O stocks {len([s for s in OI.columns if not SEC.get(s)])}", flush=True)
    sec_n = pd.Series({s: SEC[s] for s in syms}).value_counts()
    print("R| F&O stocks per sector:", sec_n.to_dict(), flush=True)
    nif = yf.download("^NSEI", start=str(OI.index[0].date() - timedelta(days=10)), auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); nif = nif.reindex(CL.index).ffill()
    # weekly
    Wc = CL.resample("W-FRI").last(); Wo = OI.resample("W-FRI").last(); Wn = nif.resample("W-FRI").last()
    rc = Wc.pct_change(fill_method=None).clip(-0.4, 0.4); ro = Wo.pct_change(fill_method=None).clip(-0.9, 3)
    secs = [s for s, k in sec_n.items() if k >= 3]
    rows = []
    idx = {}
    for s in secs:
        m = [x for x in syms if SEC[x] == s]
        idx[s] = (1 + rc[m].mean(axis=1).fillna(0)).cumprod()
        lb = ((rc[m] > 0) & (ro[m] > 0.02)).sum(axis=1); sb = ((rc[m] < 0) & (ro[m] > 0.02)).sum(axis=1)
        sc = ((rc[m] > 0) & (ro[m] < -0.02)).sum(axis=1); cnt = rc[m].notna().sum(axis=1).replace(0, np.nan)
        oi_chg = Wo[m].sum(axis=1).pct_change()
        for t in Wc.index:
            rows.append(dict(w=t, sec=s, build=float((lb[t] - sb[t]) / cnt[t]) if cnt[t] == cnt[t] else np.nan,
                             cover=float(sc[t] / cnt[t]) if cnt[t] == cnt[t] else np.nan, oi_chg=float(oi_chg[t]) if t in oi_chg else np.nan, n=int(cnt[t]) if cnt[t] == cnt[t] else 0))
    I = pd.DataFrame(idx)
    RS = 100 * I.div(Wn, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=I.index, columns=I.columns).where(ratio.notna() & mom.notna())
    fwd = (I.shift(-4) / I - 1).sub(Wn.shift(-4) / Wn - 1, axis=0) * 100
    D = pd.DataFrame(rows)
    D["q"] = [Q.at[r.w, r.sec] if r.w in Q.index else None for r in D.itertuples()]
    D["mom"] = [mom.at[r.w, r.sec] for r in D.itertuples()]
    D["fwd4"] = [fwd.at[r.w, r.sec] for r in D.itertuples()]
    D["toL4"] = [bool((Q[r.sec].loc[r.w:].iloc[1:5] == "L").any()) if r.w in Q.index else False for r in D.itertuples()]
    print("R| sector-weeks", len(D), "with build-up", int(D.build.notna().sum()), "with quadrant", int(D.q.notna().sum()),
          "with fwd 4w", int(D.fwd4.notna().sum()), flush=True)
    last = D[D.w == D.w.max()].sort_values("build", ascending=False)
    print("R| latest week", str(D.w.max().date()), "build-up by sector:", {r.sec: (round(r.build, 2), r.q) for r in last.itertuples()}, flush=True)
    res = dict(method=__doc__)
    if PILOT:
        return
    X = D.dropna(subset=["build", "fwd4", "q", "mom"]).copy()
    X["terc"] = X.groupby("w").build.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=["low", "mid", "high"]) if len(s) >= 6 else np.nan)
    out = {}
    for t in ("low", "mid", "high"):
        x = X[X.terc == t]; out[t] = dict(n=len(x), fwd4=round(x.fwd4.mean(), 2), up=round((x.fwd4 > 0).mean() * 100))
    res["by tercile"] = out; print("R| next 4 weeks vs Nifty by OI build-up tercile:", out, flush=True)
    for qq, nm in (("I", "Improving"), ("L", "Leading"), ("W", "Weakening"), ("G", "Lagging")):
        o = {}
        for t in ("low", "high"):
            x = X[(X.q == qq) & (X.terc == t)]; o[t] = dict(n=len(x), fwd4=round(x.fwd4.mean(), 2) if len(x) else None, toL=round(x.toL4.mean() * 100) if len(x) else None)
        res[f"in {nm}"] = o; print(f"R| {nm}: low build-up {o['low']} | high build-up {o['high']}  (toL = reached Leading within 4 weeks %)", flush=True)
    ic_b = X.groupby("w").apply(lambda g: g.build.rank().corr(g.fwd4.rank())).mean()
    ic_m = X.groupby("w").apply(lambda g: g.mom.rank().corr(g.fwd4.rank())).mean()
    ic_c = X.groupby("w").apply(lambda g: g.cover.rank().corr(g.fwd4.rank())).mean()
    ic_o = X.groupby("w").apply(lambda g: g.oi_chg.rank().corr(g.fwd4.rank())).mean()

    def resid(g):
        a = g.build.rank(); b = g.mom.rank(); beta = np.polyfit(b, a, 1)[0] if b.std() > 0 else 0
        return (a - beta * b).corr(g.fwd4.rank())
    ic_r = X.groupby("w").apply(resid).mean()
    res["rank correlation with next 4 weeks"] = dict(build=round(ic_b, 3), price_momentum=round(ic_m, 3), short_covering=round(ic_c, 3),
                                                     oi_change=round(ic_o, 3), build_after_momentum=round(ic_r, 3), weeks=int(X.w.nunique()))
    print("R| rank correlation with next 4 weeks:", res["rank correlation with next 4 weeks"], flush=True)
    half = sorted(X.w.unique()); mid = half[len(half) // 2]
    for nm, x in (("first half", X[X.w < mid]), ("second half", X[X.w >= mid])):
        print(f"R| {nm}: build IC {x.groupby('w').apply(lambda g: g.build.rank().corr(g.fwd4.rank())).mean():.3f}, "
              f"momentum IC {x.groupby('w').apply(lambda g: g.mom.rank().corr(g.fwd4.rank())).mean():.3f}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/sector_oi_rrg.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
