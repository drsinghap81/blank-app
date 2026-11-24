"""Pullbacks to RISING averages (25 Nov 2026, Amritpal: "did you check pullbacks when averages were rising").
The earlier pilots required only a rising 200-SMA (and 50 > 200). Here the TOUCHED average itself must be rising, tested three ways:
  rising   = average above its value 10 sessions earlier
  steep    = rising more than 2% over 20 sessions (strong slope)
  stack    = 10-EMA > 20-EMA > 50 > 100 > 200 and all five rising (every average rising, fully stacked)
Touch = low within 0.5% of (or below) the average while the close holds within 1% above/below, first touch after 10 clear sessions,
in an uptrend (close > rising 200-SMA). Next 20 / 60 sessions, 0.4% cost; vs any uptrend day; newest half 2021-26 separately.
Also the Fibonacci-level buys from fib_pullback.py, limited to pullbacks where the 50-SMA and 20-EMA were still rising at that day.
PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from habit_profile import zz  # noqa: E402

SPLIT = pd.Timestamp("2021-07-01"); MAS = ("EMA10", "EMA20", "SMA50", "SMA100", "SMA200")
LV = (0.236, 0.382, 0.45, 0.5, 0.618, 0.70, 0.786, 1.0)


def main():
    U_ = os.environ.get("UNIV", "")                      # 25 Nov 2026: "large" = today's Nifty 50 + Next 50, "n200" = + Midcap 150 top
    if U_:
        L = []
        for f in (["nifty50", "niftynext50"] if U_ == "large" else ["nifty50", "niftynext50", "niftymidcap150"]):
            L += pd.read_csv(f"data/universe/{f}.csv").Symbol.str.strip().tolist()
        FV.symbols = lambda mk: pd.DataFrame({"ticker": sorted(set(s_ + ".NS" for s_ in L))})
        FV.PILOT = False
        print(f"R| universe {U_}: {len(set(L))} stocks (today's members - survivorship)", flush=True)
    P = FV.load(); T = []; U = []; F = []
    for sym, x in P.items():
        c = x.CLOSE; l = x.LOW; cv = c.to_numpy(float); lv = l.to_numpy(float); D = c.index; n = len(cv)
        M = {"EMA10": c.ewm(span=10, adjust=False).mean(), "EMA20": c.ewm(span=20, adjust=False).mean(), "SMA50": c.rolling(50).mean(),
             "SMA100": c.rolling(100).mean(), "SMA200": c.rolling(200).mean()}
        up = ((c > M["SMA200"]) & (M["SMA200"] > M["SMA200"].shift(20))).to_numpy()
        rising = {m: (M[m] > M[m].shift(10)).to_numpy() for m in MAS}; steep = {m: (M[m] > M[m].shift(20) * 1.02).to_numpy() for m in MAS}
        stack = ((M["EMA10"] > M["EMA20"]) & (M["EMA20"] > M["SMA50"]) & (M["SMA50"] > M["SMA100"]) & (M["SMA100"] > M["SMA200"])).to_numpy() & np.all([rising[m] for m in MAS], axis=0)
        for i in range(210, n - 61, 5):
            if up[i]:
                U.append((D[i], cv[i + 20] / cv[i] - 1, cv[i + 60] / cv[i] - 1))
        for m in MAS:
            mv = M[m].to_numpy(float); last = -99
            for i in range(210, n - 61):
                if lv[i] <= mv[i] * 1.005:
                    if up[i] and cv[i] >= mv[i] * 0.99 and i - last > 10:
                        T.append(dict(sym=sym, d=D[i], ma=m, f120=cv[i + 120] / cv[i] - 1 - 0.004 if i + 120 < n else np.nan, dd60=float(lv[i + 1:i + 61].min() / cv[i] - 1), rising=bool(rising[m][i]), steep=bool(steep[m][i]), stack=bool(stack[i]),
                                      f20=cv[i + 20] / cv[i] - 1 - 0.004, f60=cv[i + 60] / cv[i] - 1 - 0.004))
                    last = i
        piv = zz(cv); r50 = rising["SMA50"]; r20 = rising["EMA20"]
        for k in range(2, len(piv) - 1):
            (pl, a), (h, b), (lo, cc) = piv[k - 1], piv[k], piv[k + 1]
            if (a, b, cc) != ("L", "H", "L") or not up[h] or D[h] < pd.Timestamp("2016-01-01") or cv[h] <= cv[pl]:
                continue
            leg = cv[h] - cv[pl]; done = set()
            for i in range(h + 1, min(lo + 1, n - 61)):
                r_i = (cv[h] - cv[i]) / leg
                for L in LV:
                    if L not in done and r_i >= L:
                        done.add(L)
                        F.append(dict(d=D[i], lvl=L, r50=bool(r50[i]), r20=bool(r20[i]), f20=cv[i + 20] / cv[i] - 1 - 0.004, f60=cv[i + 60] / cv[i] - 1 - 0.004))
    T = pd.DataFrame(T); U = pd.DataFrame(U, columns=["d", "f20", "f60"]); F = pd.DataFrame(F)
    def s(X):
        if len(X) < 20:
            return f"n {len(X)}"
        XB = X[X.d >= SPLIT]
        return f"n {len(X):5d} | 20d {X.f20.mean() * 100:+.2f}% (up {(X.f20 > 0).mean() * 100:.0f}%) | 60d {X.f60.mean() * 100:+.2f}% | 2021-26: 20d {XB.f20.mean() * 100:+.2f}% 60d {XB.f60.mean() * 100:+.2f}%"
    print(f"R| any uptrend day                 | {s(U)}", flush=True)
    for m in MAS:
        X = T[T.ma == m]
        print(f"R| {m:6s} touch, average falling/flat | {s(X[~X.rising])}", flush=True)
        print(f"R| {m:6s} touch, average rising      | {s(X[X.rising])}", flush=True)
        print(f"R| {m:6s} touch, rising steeply >2%/20d | {s(X[X.steep])}", flush=True)
        print(f"R| {m:6s} touch, all averages stacked+rising | {s(X[X["stack"]])}", flush=True)
    # the standout: touch of a rising 100-SMA with every average stacked and rising - detail
    for m in ("SMA100", "SMA50"):
        X = T[(T.ma == m) & T["stack"]].copy(); U2 = U.copy()
        if len(X) < 10:
            continue
        print(f"R| DETAIL {m} stacked touches: n {len(X)} in {X.sym.nunique()} stocks | median 60d {X.f60.median() * 100:+.1f}% | 120d avg {X.f120.mean() * 100:+.1f}% | worst dip in next 60d (median) {X.dd60.median() * 100:.1f}% | "
              f"60d up {(X.f60 > 0).mean() * 100:.0f}% | top-5% removed 60d avg {X.f60[X.f60 < X.f60.quantile(0.95)].mean() * 100:+.1f}%", flush=True)
        yr = X.groupby(X.d.dt.year).agg(n=("f60", "size"), f60=("f60", "mean")); uy = U2.groupby(U2.d.dt.year).f60.mean()
        print(f"R| DETAIL {m} by year (n, 60d vs any uptrend day): " + " | ".join(f"{y}: {int(r.n)} {r.f60 * 100:+.1f}% vs {uy.get(y, float('nan')) * 100:+.1f}%" for y, r in yr.sort_index(ascending=False).iterrows()), flush=True)
        end = X.d.max()
        for k in (1, 3, 5):
            Z = X[X.d > end - pd.DateOffset(years=k)]; UZ = U2[U2.d > end - pd.DateOffset(years=k)]
            print(f"R| DETAIL {m} last {k}y: n {len(Z)} 60d {Z.f60.mean() * 100:+.1f}% vs any uptrend day {UZ.f60.mean() * 100:+.1f}%", flush=True)
        xc = X[~((X.d >= "2020-02-15") & (X.d <= "2020-12-31"))]
        print(f"R| DETAIL {m} ex-Covid: n {len(xc)} 60d {xc.f60.mean() * 100:+.1f}%", flush=True)
    for L in LV:
        X = F[F.lvl == L]
        print(f"R| Fib {L * 100:5.1f}%: all {s(X)}", flush=True)
        print(f"R| Fib {L * 100:5.1f}%: 50-SMA & 20-EMA still rising {s(X[X.r50 & X.r20])}", flush=True)
        print(f"R| Fib {L * 100:5.1f}%: 50-SMA rising, 20-EMA turned down {s(X[X.r50 & ~X.r20])}", flush=True)


if __name__ == "__main__":
    main()
