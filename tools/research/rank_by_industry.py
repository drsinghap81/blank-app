"""Top-down step 3 test: when there are more buy signals than free slots, does picking stocks in strong industries help? (21 Nov 2026,
Amritpal: "Yes" to testing the alignment ranking before building it into the app.)

Systems with today's live rules and the adopted RED-light gate (no new buys on a RED day):
  9/21 : tools/research/concentrated_921.run (buy next open, 5-day-low stop, Supertrend exit), 10 positions, 1% risk
  ATH  : monthly ATH breakouts (tools/ath_scan.analyse, base >= 24 months, 30-week SMA exit), Rs 20 L, 10 equal positions
         (the book that has competition for slots), via tools/research/ath_red_skip.sim
Ranking of competing same-day signals (all known on the signal day):
  r63       : 3-month return (the current choice for 9/21)
  random    : 3 seeds (baseline)
  results   : the stock's NSE industry's latest completed results season (point-in-time: the day 70% had reported) - share of
              reporters with net profit up > 20% y/y, plus half the share whose growth accelerated
  pulse     : industry Pulse = share of the industry's stocks 'trending' over the last 21 sessions (above a rising 150-day SMA,
              EMA9 > EMA21, within 25% of the 52-week high, 3-month return beating Nifty)
  combo     : average of the results and pulse ranks; r63 breaks ties
Industry = NSE basic industry (today's members, survivorship). Report: CAGR / max DD, newest-first windows, years, bull / bear, ex-Covid.
PILOT env = 400 stocks, 1 seed, 9/21 only. Output data/research/rank_by_industry.json"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402
import concentrated_921 as K  # noqa: E402
import light_distribution as LD  # noqa: E402
from results_season import quarters  # noqa: E402
from holy_grail import report  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def industry_results(IND, days):
    """daily results score per industry (step function from each season's 70%-reported day)"""
    R = quarters(); R = R[R.sym.isin(IND)]; R["ind"] = R.sym.map(IND)
    have = R.groupby("ind").sym.nunique()
    rows = []
    for (ind, end), g in R.groupby(["ind", "end"]):
        g = g[g.known >= end]; n = have.get(ind, 0)
        need = int(np.ceil(0.7 * n))
        if n < 3 or len(g) < need:
            continue
        t = g.known.sort_values().iloc[need - 1]
        y = g[g.known <= t]
        yy = y.yoy.dropna(); a = y.dropna(subset=["yoy", "yoy_prev"])
        if len(yy) < 3:
            continue
        rows.append(dict(ind=ind, t=t, score=float((yy > 20).mean() + 0.5 * ((a.yoy > a.yoy_prev).mean() if len(a) else 0))))
    S = pd.DataFrame(rows).sort_values("t")
    out = {}
    for ind, g in S.groupby("ind"):
        s = pd.Series(g.score.values, index=g.t.values)
        s = s[~s.index.duplicated(keep="last")]
        out[ind] = s.reindex(s.index.union(days)).sort_index().ffill().reindex(days)
    return pd.DataFrame(out)


def industry_pulse(d, IND, nif):
    C = d.pivot(index="Date", columns="SYMBOL", values="CLOSE").sort_index()
    e9, e21 = C.ewm(span=9, adjust=False).mean(), C.ewm(span=21, adjust=False).mean()
    s150 = C.rolling(150).mean(); hi = C.rolling(250, min_periods=120).max()
    n = nif.reindex(C.index).ffill()
    rs = (C / C.shift(63)).div(n / n.shift(63), axis=0)
    tr = ((e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi) & (rs > 1)).astype(float).where(C.notna())
    t21 = tr.rolling(21, min_periods=10).mean()
    cols = {}
    for ind in set(IND.values()):
        m = [s for s in C.columns if IND.get(s) == ind]
        if len(m) >= 3:
            cols[ind] = t21[m].mean(axis=1)
    return pd.DataFrame(cols)


def add_scores(d, IND, RS, PU):
    d = d.copy()
    d["ind"] = d.SYMBOL.map(IND)
    st = RS.stack().rename("results").reset_index(); st.columns = ["Date", "ind", "results"]
    sp = PU.stack().rename("pulse").reset_index(); sp.columns = ["Date", "ind", "pulse"]
    d = d.merge(st, on=["Date", "ind"], how="left").merge(sp, on=["Date", "ind"], how="left")
    d["results"] = d.results.fillna(d.results.median()); d["pulse"] = d.pulse.fillna(d.pulse.median())
    rr = d.groupby("Date").results.rank(pct=True); pr = d.groupby("Date").pulse.rank(pct=True)
    d["combo"] = (rr + pr) / 2 + d.r63.rank(pct=True).fillna(0) * 1e-3
    mr = d.groupby("Date").r63.rank(pct=True).fillna(0)
    d["blend"] = (mr + rr) / 2                       # 3-month strength and industry results, equal weight
    d["blend_m"] = (2 * mr + rr) / 3                 # strength-led, results as a second vote
    d["blend3"] = (mr + rr + pr) / 3                 # strength + results + pulse
    # 22 Nov 2026 (Amritpal: "Yes" to testing a results point in the Top 5 score): 3-month strength first, plus a bonus when the
    # industry's latest season is strong + accelerating (score >= 0.75 = half+ growing > 20% and half+ speeding up; P/E not available
    # point-in-time here). Bonus 0.25 / 0.5 of the percentile scale (~ +1 / +2 points on a 0-4 scale).
    good = (d.results >= 0.75).astype(float)
    d["r63_res25"] = mr + 0.25 * good
    d["r63_res50"] = mr + 0.50 * good
    return d


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    IND0 = {m["symbol"]: r["basic"] for r in G["nse"]["rows"] for m in r["members"]}
    d, _ = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:400]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"])
    IND = {s: IND0.get(s.replace(".NS", "").replace(".BO", "")) for s in d.SYMBOL.unique()}
    IND = {k: v for k, v in IND.items() if v}
    d["r63"] = d.groupby("SYMBOL").CLOSE.transform(lambda s: s / s.shift(63) - 1)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    L = LD.light_series(d)
    days = pd.DatetimeIndex(sorted(d.Date.unique()))
    IND_bare = {s.replace(".NS", ""): v for s, v in IND.items()}
    RS = industry_results(IND_bare, days); RS.columns = list(RS.columns)
    PU = industry_pulse(d, IND, nif)
    print(f"R| panel {d.SYMBOL.nunique()} stocks, with industry {len(IND)}; results-score industries {RS.shape[1]}, pulse industries {PU.shape[1]}", flush=True)
    d = add_scores(d, IND, RS, PU)
    red = set(L.index[L == "RED"])
    d.loc[d.Date.isin(red), "sig"] = False                               # adopted rule: no new buys on RED
    res = dict(method=__doc__, n921={}, ath={})
    seeds = (0,) if PILOT else (0, 1, 2)
    RANKS = os.environ.get("RANKS", "r63,random,results,pulse,combo").split(",")
    for rank in RANKS:
        reps = []
        for sd in (seeds if rank == "random" else (0,)):
            eq, T = K.run(d, 10, 0.01, rank, sd)
            reps.append(report(eq, bull) | dict(trades=len(T), avg=round(float(T.ret.mean() * 100), 2) if len(T) else None))
        m = {k: round(float(np.mean([r[k] for r in reps])), 1) for k in ("CAGR", "max DD", "1y", "2y", "3y", "5y")}
        m["years"] = reps[0]["years"]; m["bull/bear"] = reps[0]["bull/bear a year"]; m["ex-Covid"] = reps[0]["ex-Covid"]; m["avg trade"] = reps[0]["avg"]
        res["n921"][rank] = m
        print(f"R| 9/21 rank by {rank}: {m}", flush=True)
    if PILOT or os.environ.get("NO_ATH"):
        if not PILOT:
            os.makedirs("data/research", exist_ok=True)
            json.dump(res, open(os.environ.get("OUT", "data/research/rank_by_industry.json"), "w"), indent=1, default=str)
        return
    # ---- ATH (equal 10 book), same-day signals ordered by the score
    import ath_scan as A
    import ath_red_skip as AR
    u = json.load(open("data/scan/group_pulse.json"))
    tick = sorted({s if s.endswith((".NS", ".BO")) else s + ".NS" for s in d.SYMBOL.unique()})
    today = date.today(); evs = []; C = {}
    for a in range(0, len(tick), 80):
        ch = tick[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download(ch, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x.index = pd.to_datetime(x.index).tz_localize(None)
                if len(x) < 300:
                    continue
                e_, _, _ = A.analyse(t, x, today, lookback_days=0)
                got = False
                for r in e_:
                    if r["main"] and pd.Timestamp(r["date"]) >= pd.Timestamp("2016-06-01"):
                        evs.append(dict(sym=t, d=pd.Timestamp(r["date"]).normalize(), entry=float(r["entry"]), sma=r.get("sma_entry"),
                                        xd=pd.Timestamp(r["exit_date"]).normalize() if r["exit_date"] is not None else None,
                                        xp=float(r["exit_price"]) if r["exit_price"] is not None else np.nan)); got = True
                if got:
                    from adjust import fix_gaps
                    from session import drop_partial
                    xx = drop_partial(x, "NSE"); xx = xx[(xx.Close > 0) & (xx.High > 0)]
                    C[t] = pd.Series(fix_gaps(xx.Open, xx.High, xx.Low, xx.Close, xx.Volume)[3], index=xx.index).loc["2016-01-01":].to_dict()
            except Exception as ex:  # noqa: BLE001
                print("ath skip", t, str(ex)[:60], flush=True)
        time.sleep(2)
    E = pd.DataFrame(evs); E["sma"] = pd.to_numeric(E.sma, errors="coerce")
    ld = list(L.index)
    E["light"] = [LD.before(L, x) for x in E.d]
    E["d"] = [ld[min(len(ld) - 1, L.index.searchsorted(x))] for x in E.d]
    E = E[E.light != "RED"].reset_index(drop=True)
    sc = d.set_index(["SYMBOL", "Date"])[["results", "pulse", "combo", "r63"]]
    for col in ("results", "pulse", "combo", "r63"):
        E[col] = [sc[col].get((s, t), np.nan) for s, t in zip(E.sym, E.d)]
    print(f"R| ATH events (non-RED) {len(E)}", flush=True)
    for rank in ("random", "r63", "results", "pulse", "combo"):
        reps = []
        for sd in (seeds if rank == "random" else (0,)):
            EE = E.copy()
            if rank != "random":
                EE = EE.sort_values(["d", rank], ascending=[True, False])
                EE["order"] = EE.groupby("d").cumcount()
            orig = AR.sim
            if rank != "random":
                def sim_ranked(Ex, Cx, dx, sizing, block, seed):
                    rng = np.random.default_rng(seed)
                    ent = {k: g.sort_values("order") for k, g in Ex.groupby("d")}
                    cash, pos, eq = AR.CAP0, {}, {}
                    for dt in dx:
                        for k in list(pos):
                            p = pos[k]
                            if p["xd"] is not None and dt >= p["xd"]:
                                cash += p["q"] * p["xp"] * (1 - AR.COST / 2); pos.pop(k)
                        for k, p in pos.items():
                            px = Cx[p["sym"]].get(dt)
                            if px is not None and np.isfinite(px):
                                p["last"] = px
                        if dt in ent:
                            for _, r in ent[dt].iterrows():
                                if r.sym in [p["sym"] for p in pos.values()] or len(pos) >= 10:
                                    continue
                                e = cash + sum(p["q"] * p["last"] for p in pos.values()); fill = r.entry * (1 + AR.COST / 2)
                                q = min(0.10 * e / r.entry, cash / fill)
                                if q * r.entry < 0.01 * e:
                                    continue
                                cash -= q * fill
                                pos[f"{r.sym}|{dt}"] = dict(sym=r.sym, q=q, last=r.entry, xd=r.xd, xp=r.xp if np.isfinite(r.xp) else r.entry)
                        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
                    return pd.Series(eq), [], None
                eq, _, _ = sim_ranked(EE, C, ld, "eq", None, sd)
            else:
                eq, _, _ = orig(EE, C, ld, "eq", None, sd)
            reps.append(report(eq, bull))
        m = {k: round(float(np.mean([r[k] for r in reps])), 1) for k in ("CAGR", "max DD", "1y", "2y", "3y", "5y")}
        m["years"] = reps[0]["years"]; m["bull/bear"] = reps[0]["bull/bear a year"]; m["ex-Covid"] = reps[0]["ex-Covid"]
        res["ath"][rank] = m
        print(f"R| ATH (10 equal, no RED buys) rank by {rank}: {m}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rank_by_industry.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
