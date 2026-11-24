"""Uptrend pullbacks measured in Fibonacci retracements of the prior up-leg (25 Nov 2026, Amritpal: "pullback mean till Fibonacci levels").
Same uptrends / pullbacks as habit_profile.py (close > rising 200-SMA, 50 > 200; 6% zigzag on closes). For each pullback:
retracement = (swing high - pullback low) / (swing high - previous swing low). (1) Where pullbacks end, by bucket, vs what an even spread
would give - do 38.2 / 50 / 61.8 attract more endings than nearby non-Fib levels? (2) Per stock: does its typical retracement repeat
(2016-21 vs 2021-26)? (3) Tradable version (no look-ahead): during a pullback, the first day the close reaches each level of the prior leg
(23.6 / 38.2 / 50 / 61.8 / 78.6 / 100% and, as controls, 30 / 45 / 70%) -> return over the next 20 / 60 sessions (0.4% cost), and how often
that level marked the low (no lower close in the next 20 sessions). Compared with an average uptrend day. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from habit_profile import zz  # noqa: E402

SPLIT = pd.Timestamp("2021-07-01")
LV = (0.236, 0.30, 0.382, 0.45, 0.50, 0.618, 0.70, 0.786, 1.0)
BK = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 9]
BN = ["<23.6", "23.6-38.2", "38.2-50", "50-61.8", "61.8-78.6", "78.6-100", ">100 (undercut)"]


def main():
    P = FV.load(); ends = []; hits = []; upd = []
    for sym, x in P.items():
        c = x.CLOSE; cv = c.to_numpy(float); D = c.index; n = len(cv)
        s200 = c.rolling(200).mean(); s50 = c.rolling(50).mean(); up = ((c > s200) & (s200 > s200.shift(20)) & (s50 > s200)).to_numpy()
        piv = zz(cv)
        for i in range(210, n - 61, 5):
            if up[i]:
                upd.append((D[i], cv[i + 20] / cv[i] - 1, cv[i + 60] / cv[i] - 1))
        for k in range(2, len(piv) - 1):
            (pl, a), (h, b), (lo, cc) = piv[k - 1], piv[k], piv[k + 1]
            if (a, b, cc) != ("L", "H", "L") or not up[h] or D[h] < pd.Timestamp("2016-01-01"):
                continue
            leg = cv[h] - cv[pl]
            if leg <= 0:
                continue
            rt = (cv[h] - cv[lo]) / leg
            ends.append(dict(sym=sym, d=D[lo], rt=rt, leg_pct=leg / cv[pl]))
            done = set()
            for i in range(h + 1, min(lo + 1, n - 61)):                     # walk the pullback day by day (low not known yet)
                r_i = (cv[h] - cv[i]) / leg
                for L in LV:
                    if L not in done and r_i >= L:
                        done.add(L)
                        fut = cv[i + 1:i + 21]
                        hits.append(dict(sym=sym, d=D[i], lvl=L, f20=cv[i + 20] / cv[i] - 1 - 0.004, f60=cv[i + 60] / cv[i] - 1 - 0.004,
                                         low=bool(fut.min() >= cv[i] * 0.995)))
    E = pd.DataFrame(ends); H = pd.DataFrame(hits); U = pd.DataFrame(upd, columns=["d", "f20", "f60"])
    E["b"] = pd.cut(E.rt, BK, labels=BN, right=False)
    print(f"R| uptrend pullbacks {len(E)} ({E.sym.nunique()} stocks) | median retracement {E.rt.median() * 100:.0f}% | mean {E.rt.clip(upper=3).mean() * 100:.0f}%", flush=True)
    for lab, X in (("all", E), ("2016-21", E[E.d < SPLIT]), ("2021-26", E[E.d >= SPLIT])):
        vc = X.b.value_counts(normalize=True).reindex(BN).fillna(0)
        print(f"R| where pullbacks end ({lab:7s}): " + " | ".join(f"{k} {v * 100:.0f}%" for k, v in vc.items()), flush=True)
    # clustering: endings within +-2.5 pts of a Fib level vs within +-2.5 pts of a non-Fib control level
    def near(levels):
        return float(np.mean([any(abs(r - L) <= 0.025 for L in levels) for r in E.rt]))
    print(f"R| endings within 2.5 pts of 38.2/50/61.8: {near((0.382, 0.5, 0.618)) * 100:.1f}% | of non-Fib 30/45/70: {near((0.30, 0.45, 0.70)) * 100:.1f}% | of 33/55/66: {near((0.33, 0.55, 0.66)) * 100:.1f}%", flush=True)
    A = E[E.d < SPLIT].groupby("sym").rt.median(); B = E[E.d >= SPLIT].groupby("sym").rt.median(); cnt = E.groupby("sym").size()
    J = pd.concat([A, B], axis=1, keys=["A", "B"]).dropna(); J = J[cnt.reindex(J.index) >= 8]
    print(f"R| per-stock typical retracement 2016-21 vs 2021-26: corr {J.A.corr(J.B):+.2f} (rank {J.A.rank().corr(J.B.rank()):+.2f}), {len(J)} stocks", flush=True)
    print(f"R| any uptrend day: 20d {U.f20.mean() * 100:+.2f}% (up {(U.f20 > 0).mean() * 100:.0f}%) 60d {U.f60.mean() * 100:+.2f}%", flush=True)
    for L in LV:
        X = H[H.lvl == L]; tag = "" if L in (0.236, 0.382, 0.5, 0.618, 0.786, 1.0) else " (control, not Fib)"
        XB = X[X.d >= SPLIT]
        print(f"R| first close at {L * 100:5.1f}%{tag:20s}: n {len(X):5d} | 20d {X.f20.mean() * 100:+.2f}% (up {(X.f20 > 0).mean() * 100:.0f}%) | 60d {X.f60.mean() * 100:+.2f}% "
              f"| was the low {X.low.mean() * 100:.0f}% | 2021-26 20d {XB.f20.mean() * 100:+.2f}% 60d {XB.f60.mean() * 100:+.2f}%", flush=True)


if __name__ == "__main__":
    main()
