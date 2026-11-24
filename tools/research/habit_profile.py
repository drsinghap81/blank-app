"""How does each stock behave while it trends up - and does that habit repeat? (25 Nov 2026, Amritpal: "when a stock is in uptrend can we
first analyse what patterns it makes generally while trending up or which SMA it takes support, for individual stocks - pilot first").
Earlier work: claude/stock-habits.md (Titan / SBI, 69 large caps), claude/ma-fitting.md (fitted MA didn't persist). This pilot widens it.
Per stock, inside uptrends (close > rising 200-day SMA and 50 > 200), every pullback (zigzag 6% on closes: swing high -> swing low):
  depth %, length (sessions), which average the low held at (within 2%: EMA10, EMA20, SMA50, SMA100, SMA200; else below all / none),
  whether it undercut the previous swing low, Fibonacci retracement of the prior up-leg, RSI(14) at the low.
Halves: A = 2016-01 .. 2021-06 (habit learned), B = 2021-07 .. 2026-11 (habit tested). Persistence: correlation across stocks of each
metric between halves; does the favourite average of A stay favourite in B (vs chance); and does buying in B when a pullback low
touches the A-favourite average beat touches of the other averages and an average uptrend day (20 / 60 sessions, 0.4% cost)?
PILOT env = 150 stocks. Writes data/research/habit_profile(_pilot).json with each stock's habit card."""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from trend_scan import rsi  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
MAS = ("EMA10", "EMA20", "SMA50", "SMA100", "SMA200")
SPLIT = pd.Timestamp("2021-07-01")


def zz(c, thr=0.06):
    piv = []; d = 0; hi = lo = 0
    for i in range(1, len(c)):
        if c[i] > c[hi]: hi = i
        if c[i] < c[lo]: lo = i
        if d >= 0 and c[i] <= c[hi] * (1 - thr):
            piv.append((hi, "H")); d = -1; lo = i
        elif d <= 0 and c[i] >= c[lo] * (1 + thr):
            piv.append((lo, "L")); d = 1; hi = i
    return piv


def profile(x):
    c = x.CLOSE; l = x.LOW; n = len(c)
    M = {"EMA10": c.ewm(span=10, adjust=False).mean(), "EMA20": c.ewm(span=20, adjust=False).mean(), "SMA50": c.rolling(50).mean(),
         "SMA100": c.rolling(100).mean(), "SMA200": c.rolling(200).mean()}
    up = (c > M["SMA200"]) & (M["SMA200"] > M["SMA200"].shift(20)) & (M["SMA50"] > M["SMA200"])
    R = rsi(c); cv = c.to_numpy(float); lv = l.to_numpy(float); D = c.index
    piv = zz(cv); pulls = []
    for k in range(1, len(piv) - 1):
        (h, th), (lo, tl) = piv[k], piv[k + 1]
        if th != "H" or tl != "L" or not bool(up.iloc[h]) or D[h] < pd.Timestamp("2016-01-01"):
            continue
        prevlow = [p for p in piv[:k] if p[1] == "L"]; pl = prevlow[-1][0] if prevlow else None
        lowv = lv[lo]; near = "none"
        dists = {m: abs(lowv / M[m].iloc[lo] - 1) for m in MAS if np.isfinite(M[m].iloc[lo])}
        held = {m: d for m, d in dists.items() if d <= 0.02 and cv[lo] >= M[m].iloc[lo] * 0.98}
        if held:
            near = min(held, key=held.get)
        elif all(cv[lo] < M[m].iloc[lo] for m in dists):
            near = "below all"
        leg = cv[h] - (cv[pl] if pl is not None else cv[h])
        fib = (cv[h] - cv[lo]) / leg if pl is not None and leg > 0 else np.nan
        f20 = cv[lo + 20] / cv[lo] - 1 if lo + 20 < n else np.nan
        pulls.append(dict(d=D[lo], depth=cv[lo] / cv[h] - 1, bars=lo - h, near=near, under=bool(pl is not None and cv[lo] < cv[pl]),
                          fib=fib, rsi=float(R.iloc[lo]), f20=f20))
    # touches (any day, not only swing lows): first touch of each MA after 10 sessions clear, in an uptrend
    tch = []
    for m in MAS:
        mv = M[m].to_numpy(float); last = -99
        for i in range(210, n - 61):
            if not up.iloc[i] or not np.isfinite(mv[i]):
                continue
            if lv[i] <= mv[i] * 1.005 and cv[i] >= mv[i] * 0.99 and i - last > 10:
                tch.append(dict(d=D[i], ma=m, f20=cv[i + 20] / cv[i] - 1 - 0.004, f60=cv[i + 60] / cv[i] - 1 - 0.004))
            if lv[i] <= mv[i] * 1.005:
                last = i
    upd = [dict(d=D[i], f20=cv[i + 20] / cv[i] - 1, f60=cv[i + 60] / cv[i] - 1) for i in range(210, n - 61, 5) if up.iloc[i]]
    return pd.DataFrame(pulls), pd.DataFrame(tch), pd.DataFrame(upd)


def card(P):
    if len(P) < 4:
        return None
    vc = P.near.value_counts(normalize=True)
    fav = next((m for m in vc.index if m in MAS), None)
    return dict(n=int(len(P)), depth_med=round(float(P.depth.median()) * 100, 1), bars_med=float(P.bars.median()),
                undercut=round(float(P.under.mean()) * 100), rsi_med=round(float(P.rsi.median()), 1), fib_med=round(float(P.fib.median()) * 100) if P.fib.notna().any() else None,
                fav=fav, fav_share=round(float(vc.get(fav, 0)) * 100) if fav else 0, near=vc.round(2).to_dict())


def main():
    Pall = FV.load(); cards = {}; A_, B_ = [], []; T_ = []; U_ = []
    for sym, x in Pall.items():
        try:
            P, T, U = profile(x)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, e); continue
        if len(P):
            P["sym"] = sym; A = card(P[P.d < SPLIT]); B = card(P[P.d >= SPLIT]); cards[sym] = dict(all=card(P), A=A, B=B)
            if A and B:
                A_.append(dict(sym=sym, **{k: A[k] for k in ("depth_med", "bars_med", "undercut", "rsi_med", "fav", "fav_share")}))
                B_.append(dict(sym=sym, **{k: B[k] for k in ("depth_med", "bars_med", "undercut", "rsi_med", "fav", "fav_share")}, Bnear=B["near"]))
        if len(T):
            T["sym"] = sym; T_.append(T)
        if len(U):
            U["sym"] = sym; U_.append(U)
    A = pd.DataFrame(A_).set_index("sym"); B = pd.DataFrame(B_).set_index("sym"); J = A.join(B, lsuffix="_A", rsuffix="_B")
    print(f"R| stocks with >=4 uptrend pullbacks in both halves: {len(J)}", flush=True)
    for k in ("depth_med", "bars_med", "undercut", "rsi_med"):
        print(f"R| persistence {k:10s}: corr A->B {J[k + '_A'].corr(J[k + '_B']):+.2f} (rank {J[k + '_A'].rank().corr(J[k + '_B'].rank()):+.2f}) | median A {J[k + '_A'].median()} B {J[k + '_B'].median()}", flush=True)
    same = (J.fav_A == J.fav_B).mean()
    allB = pd.Series([m for v in J.Bnear for m, s in v.items() for _ in range(int(round(s * 100)))]).value_counts(normalize=True)
    chance = sum(allB.get(m, 0) * (J.fav_A == m).mean() for m in MAS)
    sh = [J.Bnear.iloc[i].get(J.fav_A.iloc[i], 0) for i in range(len(J)) if J.fav_A.iloc[i]]
    print(f"R| favourite average of A is also favourite in B: {same * 100:.0f}% of stocks | B pullbacks ending at the A-favourite: {np.mean(sh) * 100:.0f}% vs that average's overall share in B", flush=True)
    print("R| where uptrend pullbacks end, all stocks (A / B): " + " | ".join(f"{m} {pd.concat([pd.Series(c_['A']['near']) for c_ in cards.values() if c_['A']]).groupby(level=0).mean().get(m, 0) * 100:.0f}%" for m in MAS + ("below all", "none")), flush=True)
    T = pd.concat(T_); U = pd.concat(U_); favA = J.fav_A.to_dict()
    TB = T[T.d >= SPLIT].copy(); TB["isfav"] = TB.apply(lambda r: favA.get(r.sym) == r.ma, axis=1); UB = U[U.d >= SPLIT]
    print(f"R| B-half (2021-26) any uptrend day: 20d {UB.f20.mean() * 100:+.2f}% 60d {UB.f60.mean() * 100:+.2f}% (n {len(UB)})", flush=True)
    for lab, X in (("touch of the stock's A-favourite average", TB[TB.isfav & TB.sym.isin(J.index)]), ("touch of its other averages", TB[~TB.isfav & TB.sym.isin(J.index)])):
        print(f"R| B-half {lab:42s}: n {len(X):5d} | 20d {X.f20.mean() * 100:+.2f}% (up {(X.f20 > 0).mean() * 100:.0f}%) | 60d {X.f60.mean() * 100:+.2f}%", flush=True)
    for m in MAS:
        X = TB[TB.ma == m]; Xf = X[X.isfav]
        print(f"R| B-half touches {m:6s}: all n {len(X):5d} 20d {X.f20.mean() * 100:+.2f}% 60d {X.f60.mean() * 100:+.2f}% | where it was the A-favourite n {len(Xf):4d} 20d {Xf.f20.mean() * 100 if len(Xf) else float('nan'):+.2f}% 60d {Xf.f60.mean() * 100 if len(Xf) else float('nan'):+.2f}%", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(cards, open("data/research/habit_profile" + ("_pilot" if PILOT else "") + ".json", "w"), default=str)


if __name__ == "__main__":
    main()
