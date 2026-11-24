"""Strategy scorecard + 'how many GOOD systems is this stock on' (24 Nov 2026, Amritpal: "each stock with a matrix having all
these strategies; categorise a backtest score for each; if a stock is scoring overall more I should see it - say KOTAKBANK comes in
10, 8 backtested good, 2 not good").

One uniform test for every price-pattern strategy in the app, NSE stocks (Yahoo 2015-26, today's names -> survivors), point in time:
  ath      Monthly ATH breakout: high above the high of the all-time-high closing month, base >= 24 months, close above a rising
           150-day SMA (30 weeks), >= Rs 2 cr/day   (the Momentum system's entry)
  month    month closed above the highest earlier month close (that high >= 12 months old)        (Month close list)
  wcup     weekly cup close (tools/cupclose.py: 104-week rim >= 26 weeks old, cup >= 20% deep, room >= depth)
  dcup     daily cup close  (250-day rim >= 20 days old, cup >= 15% deep, room >= depth)
  base     first 52-week-high breakout after a 6-month base
  cup921   9/21 cross within 20 sessions after a day cup close or 52-week base breakout          (Cup 9/21, approx.)
  921      9/21 cross on any stock (live rule)
  tight    tight-base breakout
  flag / pennant / rectangle   breakout with drying flag volume, 1.5x breakout volume, range <= 8% (live rule without room)
  wbot / tiltw / triple / ihs  bottom patterns, first close above the neckline (tools/pattern_scan.py rules)
  retest   after a 52-week base breakout, first close back within 3% above the breakout level (10-60 sessions later)
  emalift  first candle whose low is above a rising EMA 9 (none in the previous 10 sessions)
  stack    first day of close > SMA 20 > 50 > 100 > 200, all rising (none in the previous 20 sessions)
One event per stock per system per 20 sessions. Buy next open, hold 63 (and 126) sessions, 0.4% cost; vs Nifty 50 same days.
Baseline (24 Nov, after the first run: Yahoo survivors beat Nifty on ANY day, which flattered every strategy): a random liquid
stock-day (every 21st session per stock, Rs 1 cr/day, price >= 30), same 63-day hold vs Nifty. Edge = strategy vs Nifty - baseline.
Grade:  GOOD edge >= +2.0 points, >= 55% wins and the last 3 years' edge > 0;  FAIR edge > 0;  POOR edge <= 0.
Walk-forward confluence: grades from 2016-2021 events only, then 2022-26 events bucketed by how many GOOD systems fired on the stock
in the last 20 sessions (0 / 1 / 2 / 3+) and how many not-good ones.
Per stock: each system's own past events on that stock (n, avg 63d, win) -> data/research/strategy_scorecard_stocks.json.
PILOT env = 150 stocks."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from confluence_test import sys_signals  # noqa: E402
from flag_stops import signals as flag_signals  # noqa: E402
from candle_takeout import dcup_days  # noqa: E402
from cupclose import cupclose, WK_K, WK_MIN, WK_DEP  # noqa: E402
import bottom_filters as BF  # noqa: E402
from trend_scan import VALUE_DIV  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
SYS = ("ath", "month", "wcup", "dcup", "base", "cup921", "921", "tight", "flag", "pennant", "rectangle", "wbot", "tiltw", "triple", "ihs",
       "retest", "emalift", "stack")
NAME = dict(ath="Monthly ATH breakout", month="Month close above ATH", wcup="Weekly cup close", dcup="Daily cup close", base="52-week base breakout",
            cup921="Cup 9/21", **{"921": "9/21 any stock"}, tight="Tight base", flag="Flag", pennant="Pennant", rectangle="Rectangle",
            wbot="W bottom", tiltw="Tilted W", triple="Triple bottom", ihs="Inverse H&S", retest="Breakout retest", emalift="EMA 9 lift-off",
            stack="MA stack")
H = (63, 126); GAP = 20


def first_only(s, k=GAP):
    s = np.asarray(s, bool); out = np.zeros_like(s); last = -10 ** 9
    for t in np.where(s)[0]:
        if t - last >= k:
            out[t] = True; last = t
    return out


def signals(sym, x):
    o, h, l, c, v = x.OPEN, x.HIGH, x.LOW, x.CLOSE, x.VOL; n = len(c); D = x.index
    S0 = sys_signals(x); out = {k: S0[k] for k in ("921", "base", "tight", "month")}
    val = (c * v).rolling(20).mean() / VALUE_DIV
    # Monthly ATH breakout
    m = x.resample("ME").agg(dict(HIGH="max", CLOSE="last")).dropna(); mc = m.CLOSE.to_numpy(); mh = m.HIGH.to_numpy()
    s150 = c.rolling(150).mean(); rising = s150 > s150.shift(20)
    ath = np.zeros(n, bool); mi = D.to_period("M"); mper = m.index.to_period("M")
    for j in range(25, len(m)):
        k = int(np.argmax(mc[:j]))                      # ATH closing month among completed months before month j
        if j - k < 24:
            continue
        trig = mh[k]; per = mper[j]
        idx = np.where(mi == per)[0]
        for t in idx:
            if h.iat[t] > trig and c.iat[t] > s150.iat[t] and bool(rising.iat[t]) and val.iat[t] >= 2:
                ath[t] = True; break
    out["ath"] = ath
    out["dcup"] = dcup_days(x)
    w = x.resample("W-FRI").agg(dict(HIGH="max", CLOSE="last")).dropna(); wh, wc = w.HIGH.to_numpy(float), w.CLOSE.to_numpy(float)
    wcup = np.zeros(n, bool)
    for j in range(WK_K + 5, len(w)):
        if wc[j] <= np.nanmax(wh[j - WK_K:j]):
            continue
        if cupclose(wh[:j + 1], wc[:j + 1], WK_K, WK_MIN, WK_DEP):
            i = D.searchsorted(w.index[j], side="right") - 1
            if 0 <= i < n:
                wcup[i] = True
    out["wcup"] = wcup
    trig = pd.Series(out["dcup"] | out["base"]).rolling(20, min_periods=1).max().to_numpy().astype(bool)
    out["cup921"] = out["921"] & trig
    for k in ("flag", "pennant", "rectangle"):
        out[k] = np.zeros(n, bool)
    vv = v.to_numpy(float); hh, ll = h.to_numpy(float), l.to_numpy(float)
    v50 = pd.Series(vv).rolling(50).mean().shift(1).to_numpy()
    for e in flag_signals(x):
        t, a, b, pk, lo_i = e["t"], e["a"], e["b"], e["pk"], e["lo_i"]
        if t + 1 >= n or not np.isfinite(v50[t]):
            continue
        fv = vv[a:b].mean(); pv = vv[lo_i:pk + 1].mean(); b50 = v50[lo_i] if np.isfinite(v50[lo_i]) else v50[t]
        if fv < 0.75 * pv and fv < b50 and vv[t] >= 1.5 * v50[t] and vv[t] >= vv[a:b].max() and (hh[a:b].max() - ll[a:b].min()) / hh[pk] <= 0.08:
            out[e["shape"].lower()][t] = True
    TY = dict(DB="wbot", TW="tiltw", TB="triple", IHS="ihs")
    for k in TY.values():
        out[k] = np.zeros(n, bool)
    y = x.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})
    for e in BF.events(sym, y):
        k = TY.get(e["typ"])
        if k:
            out[k][x.index.get_loc(e["d"])] = True
    # retest of a 52-week base breakout level
    pmax = c.shift(1).rolling(240, min_periods=240).max().to_numpy(); cc = c.to_numpy(float); rt = np.zeros(n, bool)
    for t in np.where(out["base"])[0]:
        L = pmax[t]
        for j in range(t + 10, min(n, t + 61)):
            if cc[j] < L * 0.97:
                break
            if ll[j] <= L * 1.03 and cc[j] > L:
                rt[j] = True; break
    out["retest"] = rt
    e9 = c.ewm(span=9, adjust=False).mean(); up = (l > e9) & (e9 > e9.shift(3))
    prev = up.shift(1).rolling(10, min_periods=1).max().fillna(1).astype(bool)
    out["emalift"] = (up & ~prev & (val >= 1)).to_numpy()
    sm = {k: c.rolling(k).mean() for k in (20, 50, 100, 200)}
    st = (c > sm[20]) & (sm[20] > sm[50]) & (sm[50] > sm[100]) & (sm[100] > sm[200])
    for k in sm:
        st &= sm[k] > sm[k].shift(5)
    st = st & (val >= 1)
    out["stack"] = (st & ~st.shift(1).rolling(20, min_periods=1).max().fillna(1).astype(bool)).to_numpy()
    return {k: first_only(out[k]) for k in SYS}


def stat(T, hz=63):
    v = T[f"r{hz}"].dropna(); xv = T[f"x{hz}"].dropna()
    if not len(v):
        return dict(n=0)
    return dict(n=int(len(v)), avg=round(float(v.mean()) * 100, 2), med=round(float(v.median()) * 100, 2), win=round(float((v > 0).mean()) * 100),
                vs_nifty=round(float(xv.mean()) * 100, 2))


BASE = {}


def grade(a, a3, b="all", b3="last 3y"):
    if not a.get("n") or a["n"] < 30:
        return "untested"
    e = a["vs_nifty"] - (BASE.get(b, {}).get("vs_nifty") or 0); e3 = (a3.get("vs_nifty") or 0) - (BASE.get(b3, {}).get("vs_nifty") or 0)
    if e >= 2.0 and a["win"] >= 55 and e3 > 0:
        return "good"
    return "fair" if e > 0 else "poor"


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    rows = []
    for sym, x in P.items():
        try:
            S = signals(sym, x)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, e); continue
        o, c = x.OPEN.to_numpy(float), x.CLOSE.to_numpy(float); D = x.index; n = len(c)
        vl = ((x.CLOSE * x.VOL).rolling(20).mean() / VALUE_DIV).to_numpy()
        S["_base"] = np.zeros(n, bool); S["_base"][250::21] = True; S["_base"] &= (vl >= 1)
        for k in SYS + ("_base",):
            for t in np.where(S[k])[0]:
                if D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n or c[t] < 30:
                    continue
                e = o[t + 1]; r = dict(sym=sym, sys=k, d=D[t], t=int(t)); ni0 = nif.asof(D[t + 1])
                for hz in H:
                    j = t + 1 + hz
                    r[f"r{hz}"] = c[j] / e - 1 - 0.004 if j < n else np.nan
                    r[f"x{hz}"] = (r[f"r{hz}"] - (nif.asof(D[j]) / ni0 - 1)) if j < n else np.nan
                r["bull"] = bool(bull.asof(D[t])) if len(bull.loc[:D[t]]) else None
                rows.append(r)
    E = pd.DataFrame(rows); end = E.d.max()
    B = E[E.sys == "_base"]; E = E[E.sys != "_base"]
    for lab, T in [("all", B), ("last 3y", B[B.d > end - pd.DateOffset(months=39)]), ("last 1y", B[B.d > end - pd.DateOffset(months=15)]),
                   ("train", B[B.d < "2022-01-01"]), ("test", B[B.d >= "2022-01-01"])]:
        BASE[lab] = stat(T)
    print("R| baseline random stock-day", BASE, flush=True)
    print("R| events", len(E), E.sys.value_counts().to_dict(), flush=True)
    res = dict(method=__doc__, events=len(E), systems={}, baseline=BASE)
    for k in SYS:
        T = E[E.sys == k]
        o = dict(name=NAME[k], all=stat(T), all126=stat(T, 126))
        for yy in (1, 3, 5):
            o[f"last {yy}y"] = stat(T[T.d > end - pd.DateOffset(months=12 * yy + 3)])
        o["bull"] = stat(T[T.bull == True]); o["bear"] = stat(T[T.bull == False])  # noqa: E712
        o["ex-Covid"] = stat(T[~((T.d >= "2020-02-15") & (T.d <= "2020-12-31"))])
        o["train"] = stat(T[T.d < "2022-01-01"]); o["test"] = stat(T[T.d >= "2022-01-01"])
        o["grade"] = grade(o["all"], o["last 3y"]); o["grade_train"] = grade(o["train"], o["train"], "train", "train")
        o["edge"] = round(o["all"]["vs_nifty"] - BASE["all"]["vs_nifty"], 2) if o["all"].get("n") else None
        o["years"] = {str(yy): stat(T[T.d.dt.year == yy]) for yy in sorted(T.d.dt.year.unique(), reverse=True)}
        res["systems"][k] = o
        print(f"R| {k:9s} {o['grade']:8s} all {o['all']} | 126d {o['all126'].get('avg')} | last1y {o['last 1y'].get('vs_nifty')} last3y {o['last 3y'].get('vs_nifty')} | bull {o['bull'].get('vs_nifty')} bear {o['bear'].get('vs_nifty')} | train {o['grade_train']}", flush=True)
    # walk-forward confluence: GOOD set from 2016-21, count on 2022-26 events
    good = {k for k in SYS if res["systems"][k]["grade_train"] == "good"}
    res["good_train"] = sorted(good); print("R| good on 2016-21:", sorted(good), flush=True)
    E = E.sort_values(["sym", "t"]); recs = []
    for sym, G in E.groupby("sym"):
        tt = G.t.to_numpy(); ss = G.sys.to_numpy()
        for i in range(len(G)):
            if G.d.iat[i] < pd.Timestamp("2022-01-01"):
                continue
            win = (tt >= tt[i] - 19) & (tt <= tt[i])
            on = set(ss[win]); g = len(on & good); b = len(on - good)
            recs.append(dict(g=g, b=b, n=len(on), r63=G.r63.iat[i], x63=G.x63.iat[i], r126=G.r126.iat[i], x126=G.x126.iat[i]))
    C = pd.DataFrame(recs); res["confluence_test_2022_26"] = {}
    for lab, M in [("good 0", C.g == 0), ("good 1", C.g == 1), ("good 2", C.g == 2), ("good 3+", C.g >= 3),
                   ("good 2+ & no poor/fair", (C.g >= 2) & (C.b == 0)), ("good 2+ with others", (C.g >= 2) & (C.b > 0)), ("any 3+ systems", C.n >= 3)]:
        T = C[M]; o = dict(n=int(len(T)), r63=stat(T.rename(columns={}), 63), r126=stat(T, 126))
        res["confluence_test_2022_26"][lab] = o; print(f"R| {lab:24s} n {o['n']} | 63d {o['r63']} | 126d {o['r126']}", flush=True)
    # per stock: each system's own history on that stock
    PS = {}
    for (sym, k), T in E.groupby(["sym", "sys"]):
        v = T.r63.dropna()
        if len(v):
            PS.setdefault(sym, {})[k] = [int(len(v)), round(float(v.mean()) * 100, 1), round(float((v > 0).mean()) * 100)]
    os.makedirs("data/research", exist_ok=True); sfx = "_pilot" if PILOT else ""
    json.dump(res, open(f"data/research/strategy_scorecard{sfx}.json", "w"), indent=1, default=str)
    json.dump(dict(asof=str(end.date()), cols=["n", "avg63", "win"], stocks=PS), open(f"data/research/strategy_scorecard_stocks{sfx}.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
