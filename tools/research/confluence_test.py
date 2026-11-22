"""Is a stock on several of our systems at once better than one on a single system? (22 Nov 2026, Amritpal: "yes do it", after the
Govt-focus shortlist started ranking stocks by how many systems they are on.)

NSE stocks (Yahoo, 2015-26, today's listed names -> survivors), daily. Five systems computed point-in-time, signal days only:
  921    9/21 cross (live rule: EMA9 crosses EMA21, Supertrend green, close > rising EMA50, RSI >= 55, Rs 1 cr/day, within 30% of 52w high)
  base   first 52-week-high breakout after a 6-month base (live rule)
  tight  tight-base breakout (10 sessions within 12%, near the 20 SMA, drying volume; close above the base high on 1.5x volume)
  month  month closed above the highest earlier month close, that high >= 12 months old (month cup close; history from 2015 only)
  flag   flag / pennant / rectangle breakout with drying flag volume, 1.5x breakout volume, flag range <= 8% (live rule without room)
Event = any system's signal day (from Jun 2016). Count = how many DIFFERENT systems signalled on that stock in the last 10 sessions
(incl. today). Forward return: buy next open, hold 21 / 63 / 126 sessions (close), minus 0.4% cost; also vs Nifty 50 over the
same days. Buckets 1 / 2 / 3+, newest first (last 1 / 2 / 3 / 5 years), each year, bull / bear (Nifty vs 200-day).
PILOT env = 150 stocks. Output data/research/confluence_test(_pilot).json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from flag_stops import signals as flag_signals  # noqa: E402
from trend_scan import supertrend, rsi, VALUE_DIV  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
SYS = ("921", "base", "tight", "month", "flag")
H = (21, 63, 126)


def sys_signals(x):
    o, h, l, c, v = x.OPEN, x.HIGH, x.LOW, x.CLOSE, x.VOL; n = len(c); out = {}
    e9, e21, e50 = (c.ewm(span=k, adjust=False).mean() for k in (9, 21, 50)); r = rsi(c)
    val = (c * v).rolling(20).mean() / VALUE_DIV; hi = c.rolling(250, min_periods=60).max()
    sd, _ = supertrend(h.values, l.values, c.values); sdS = pd.Series(sd, index=c.index)
    s = (e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (c > e50) & (e50 > e50.shift(10)) & (r >= 55) & (val >= 1) & (c >= 0.7 * hi) & (sdS == 1)
    s.iloc[:120] = False; out["921"] = s.values
    pmax = c.shift(1).rolling(240, min_periods=240).max(); newhi = (c >= c.rolling(240, min_periods=240).max()).values
    k = np.arange(n, dtype=float); last = pd.Series(np.where(newhi, k, np.nan), index=c.index).ffill().shift(1); age = pd.Series(k, index=c.index) - last
    out["base"] = ((h > pmax) & (c > c.shift(1)) & (c > 100) & (val >= 2) & (age >= 126) & (sdS == 1)).values
    s20, s50 = c.rolling(20).mean(), c.rolling(50).mean(); vs20, vs50 = v.rolling(20).mean(), v.rolling(50).mean()
    bh = h.shift(1).rolling(10).max(); bl = l.shift(1).rolling(10).min(); bv = v.shift(1).rolling(10).mean()
    near20 = (l.shift(1).rolling(10).min() <= s20.shift(1) * 1.02)
    base_ok = (bh / bl - 1 <= 0.12) & near20 & (bv < vs50.shift(1))
    trend = (c > s50) & (s20 > s50) & (r > 50) & (vs20 > 500000)
    out["tight"] = (trend & base_ok & (c > bh) & (v >= 1.5 * vs20.shift(1))).fillna(False).values
    m = c.resample("ME").last().dropna(); pm = m.shift(1).cummax()
    am = pd.Series(np.where(m >= m.cummax(), np.arange(len(m)), np.nan), index=m.index).ffill().shift(1)
    mage = pd.Series(np.arange(len(m)), index=m.index) - am
    msig = m[(m > pm) & (mage >= 12) & (np.arange(len(m)) >= 13)]
    ms = np.zeros(n, bool)
    for d in msig.index:
        i = c.index.searchsorted(d, side="right") - 1
        if 0 <= i < n:
            ms[i] = True
    out["month"] = ms
    fs = np.zeros(n, bool)
    vv = v.to_numpy(float); hh, ll, cc = h.to_numpy(float), l.to_numpy(float), c.to_numpy(float)
    v50 = pd.Series(vv).rolling(50).mean().shift(1).to_numpy()
    for e in flag_signals(x):
        t, a, b, pk, lo_i = e["t"], e["a"], e["b"], e["pk"], e["lo_i"]
        if t + 1 >= n or not np.isfinite(v50[t]):
            continue
        fv = vv[a:b].mean(); pv = vv[lo_i:pk + 1].mean(); b50 = v50[lo_i] if np.isfinite(v50[lo_i]) else v50[t]
        if fv < 0.75 * pv and fv < b50 and vv[t] >= 1.5 * v50[t] and vv[t] >= vv[a:b].max() and (hh[a:b].max() - ll[a:b].min()) / hh[pk] <= 0.08:
            fs[t] = True
    out["flag"] = fs
    return out


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    rows = []
    for sym, x in P.items():
        try:
            S = sys_signals(x)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, e); continue
        o, c = x.OPEN.to_numpy(float), x.CLOSE.to_numpy(float); D = x.index; n = len(c)
        M = np.vstack([S[k] for k in SYS]).astype(bool)                 # systems x days
        rec = np.zeros_like(M)                                          # fired in the last 10 sessions
        for j in range(M.shape[0]):
            rec[j] = pd.Series(M[j]).rolling(10, min_periods=1).max().to_numpy().astype(bool)
        anyday = np.where(M.any(axis=0))[0]
        for t in anyday:
            if D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n:
                continue
            e = o[t + 1]; r = dict(sym=sym, d=D[t], n=int(rec[:, t].sum()), fired=[k for j, k in enumerate(SYS) if M[j, t]],
                                   on=[k for j, k in enumerate(SYS) if rec[j, t]])
            ni0 = nif.asof(D[t + 1])
            for hz in H:
                j = t + 1 + hz
                r[f"r{hz}"] = c[j] / e - 1 - 0.004 if j < n else np.nan
                r[f"x{hz}"] = (r[f"r{hz}"] - (nif.asof(D[j]) / ni0 - 1)) if j < n else np.nan
            r["bull"] = bool(bull.asof(D[t])) if len(bull.loc[:D[t]]) else None
            rows.append(r)
    E = pd.DataFrame(rows); E["b"] = np.where(E.n >= 3, "3+", E.n.astype(str))
    print("R| events", len(E), "by count", E.b.value_counts().to_dict(), "by system fired", pd.Series([k for f in E.fired for k in f]).value_counts().to_dict(), flush=True)
    end = E.d.max()

    def st(T):
        o = dict(n=int(len(T)))
        for hz in H:
            v = T[f"r{hz}"].dropna(); xv = T[f"x{hz}"].dropna()
            o[f"{hz}d"] = dict(avg=round(float(v.mean()) * 100, 2) if len(v) else None, med=round(float(v.median()) * 100, 2) if len(v) else None,
                               win=round(float((v > 0).mean()) * 100) if len(v) else None, vs_nifty=round(float(xv.mean()) * 100, 2) if len(xv) else None)
        return o
    res = dict(method=__doc__, events=len(E), buckets={})
    for b in ("1", "2", "3+"):
        T = E[E.b == b]
        o = {"all": st(T)}
        for y in (1, 2, 3, 5):
            o[f"last {y}y"] = st(T[T.d > end - pd.DateOffset(years=y + 0.5)])   # +6 months so 126-day returns exist
        o["bull"] = st(T[T.bull == True]); o["bear"] = st(T[T.bull == False])  # noqa: E712
        o["ex-Covid"] = st(T[~((T.d >= "2020-02-15") & (T.d <= "2020-12-31"))])
        o["years"] = {str(y): st(T[T.d.dt.year == y]) for y in sorted(T.d.dt.year.unique(), reverse=True)}
        res["buckets"][b] = o
        print(f"R| {b} system(s) | all {o['all']} | last1y {o['last 1y']['63d'] if o['last 1y']['n'] else None} | last3y {o['last 3y']['63d'] if o['last 3y']['n'] else None} | bull {o['bull']['63d']} | bear {o['bear']['63d']}", flush=True)
        print(f"R| {b} by year 63d avg/vs Nifty: " + ", ".join(f"{y}: {v['63d']['avg']}/{v['63d']['vs_nifty']} (n {v['n']})" for y, v in o["years"].items()), flush=True)
    res["per_system"] = {}
    for k in SYS:
        T = E[E.fired.apply(lambda f: k in f)]
        a = st(T[T.n == 1]); w = st(T[T.n >= 2])
        res["per_system"][k] = {"alone": a, "with another system": w}
        print(f"R| {k} alone {a['n']}: 63d {a['63d']} | with another {w['n']}: 63d {w['63d']} 126d {w['126d']} vs alone 126d {a['126d']}", flush=True)
    pairs = {}
    for f in E[E.n == 2].on:
        pairs[" + ".join(sorted(f))] = pairs.get(" + ".join(sorted(f)), 0) + 1
    res["pairs"] = {}
    for pk_, cnt in sorted(pairs.items(), key=lambda z: -z[1])[:10]:
        T = E[(E.n == 2) & (E.on.apply(lambda f: " + ".join(sorted(f)) == pk_))]
        res["pairs"][pk_] = st(T); print(f"R| pair {pk_} | {res['pairs'][pk_]['n']} | 63d {res['pairs'][pk_]['63d']}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/confluence_test" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
