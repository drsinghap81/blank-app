"""Does the Elliott wave position at a system buy change the result? (25 Nov 2026, Amritpal: "yes do a pilot test").
Signals: tools/research/strategy_scorecard.py signals (point in time) for the systems the app trades or lists:
ath (Monthly ATH), month (month close above ATH), dcup / wcup (cup closes), 921, cup921, tight, flag, rectangle, retest.
At each signal, the wave position is counted with tools/research/wave_now.count() on WEEKLY bars up to the signal week only
(3 years back): wave 1 / 2 / 3 / 4 / 5, 5 waves done, corrective (overlap), none. Forward: buy next open, 63 and 126 sessions,
0.4% cost, vs Nifty and vs the same system's average. Newest-first windows, bull/bear (Nifty vs 200-day). PILOT = 150 stocks."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
import strategy_scorecard as SC  # noqa: E402
from wave_now import count  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
USE = ("ath", "month", "dcup", "wcup", "921", "cup921", "tight", "flag", "rectangle", "retest")


def bucket(lab):
    if lab.startswith("Corrective"):
        return "corrective"
    if lab.startswith("5 waves") or lab.startswith("Beyond"):
        return "5 done+"
    for k in ("1", "2", "3", "4", "5"):
        if f"wave {k}" in lab:
            return f"wave {k}" + (" ext" if "extending" in lab else "")
    return "none"


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    rows = []
    for sym, x in P.items():
        try:
            S = SC.signals(sym, x)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, e); continue
        o, c = x.OPEN.to_numpy(float), x.CLOSE.to_numpy(float); D = x.index; n = len(c)
        W = x.rename(columns={"HIGH": "High", "LOW": "Low", "CLOSE": "Close"})[["High", "Low", "Close"]].resample("W-FRI").agg(dict(High="max", Low="min", Close="last")).dropna()
        for k in USE:
            for t in np.where(S[k])[0]:
                if D[t] < pd.Timestamp("2017-01-01") or t + 1 >= n or c[t] < 30:
                    continue
                w = W[W.index <= D[t]].iloc[-156:]
                if len(w) < 60:
                    continue
                try:
                    lab, _ = count(w)
                except Exception:  # noqa: BLE001
                    lab = "none"
                e = o[t + 1]; r = dict(sym=sym, sys=k, d=D[t], wave=bucket(lab)); ni0 = nif.asof(D[t + 1])
                for hz in (63, 126):
                    j = t + 1 + hz
                    r[f"r{hz}"] = c[j] / e - 1 - 0.004 if j < n else np.nan
                    r[f"x{hz}"] = (r[f"r{hz}"] - (nif.asof(D[j]) / ni0 - 1)) if j < n else np.nan
                r["bull"] = bool(bull.asof(D[t])) if len(bull.loc[:D[t]]) else None
                rows.append(r)
    E = pd.DataFrame(rows); end = E.d.max()
    sysavg = E.groupby("sys").x63.mean(); E["edge"] = E.x63 - E.sys.map(sysavg)
    print("R| events", len(E), E.wave.value_counts().to_dict(), flush=True)

    def st(T):
        v = T.r63.dropna(); x = T.x63.dropna(); v6 = T.r126.dropna()
        if len(v) < 15:
            return f"n {len(v)}"
        return (f"n {len(v):5d} | 63d avg {v.mean() * 100:+5.1f}% med {v.median() * 100:+5.1f}% win {(v > 0).mean() * 100:3.0f}% vs Nifty {x.mean() * 100:+5.1f} "
                f"| vs own system {T.edge.dropna().mean() * 100:+5.1f} | 126d {v6.mean() * 100:+5.1f}%")
    order = ["wave 1", "wave 1 ext", "wave 2", "wave 3", "wave 3 ext", "wave 4", "wave 5", "5 done+", "corrective", "none"]
    for lab, T0 in [("ALL", E), ("last 1y", E[E.d > end - pd.DateOffset(months=15)]), ("last 3y", E[E.d > end - pd.DateOffset(months=39)]),
                    ("bull", E[E.bull == True]), ("bear", E[E.bull == False]), ("ex-Covid", E[~((E.d >= "2020-02-15") & (E.d <= "2020-12-31"))])]:  # noqa: E712
        print(f"R| ===== {lab} =====", flush=True)
        for wv in order:
            T = T0[T0.wave == wv]
            if len(T):
                print(f"R| {lab:8s} {wv:11s} | {st(T)}", flush=True)
    for k in ("ath", "921", "flag", "dcup", "month", "tight"):
        print(f"R| ===== system {k} =====", flush=True)
        for wv in order:
            T = E[(E.sys == k) & (E.wave == wv)]
            if len(T) >= 15:
                print(f"R| {k:6s} {wv:11s} | {st(T)}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    E.to_csv("data/research/wave_bt" + ("_pilot" if PILOT else "") + ".csv.gz", index=False)


if __name__ == "__main__":
    main()
