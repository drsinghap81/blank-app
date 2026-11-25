"""Portfolio check before going live (25 Nov 2026, Amritpal: "Yes, before that check how that portfolio would have performed against
this"): the live Cup 9/21 + Momentum book now vs the recommended changes.
  A  now          : Cup 9/21 (wick close) + Momentum (close confirm), all signals
  B  lanes        : same, skipping industries in the Weak / Fading / Turning(bouncing) Pulse lanes
  C  lanes + FII  : B plus Bank Nifty futures (1 slot) when FIIs return after heavy selling and Bank Nifty's 9/21 is up
                    (tools/research/fii_return_test.py rule R5 + 9/21 up; exit 9/21 cross down; from 2015, FII data start)
  D  now + FII    : A plus the Bank Nifty trade
One 10-slot pool, 10% of equity per trade, first come first served by entry date. Equity marked at exits (as AC.port).
NSE 2007-26 (FII sleeve from mid-2015), 0.4% stock cost, 0.1% futures cost. Yearly returns newest first, 2021-26, last 2 years."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import pulse_filter_test as PF  # noqa: E402


def bn_trades():
    F = pd.read_csv("data/research/fii_daily.csv", index_col=0, parse_dates=True).iloc[:, 0]
    X = pd.read_csv("data/futures/BANKNIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "Close"]].astype(float)
    X = X[X.index >= "2015-06-01"]
    f = F.reindex(X.index.union(F.index)).fillna(0).groupby(level=0).sum().shift(1).reindex(X.index).fillna(0)
    s20, s5 = f.rolling(20).sum(), f.rolling(5).sum()
    heavy = s20 <= s20.rolling(250, min_periods=120).quantile(0.2); recent = heavy.rolling(30).max().astype(bool)
    o, c = X.Open.to_numpy(), X.Close.to_numpy(); D = X.index; n = len(c)
    e9 = X.Close.ewm(span=9, adjust=False).mean().to_numpy(); e21 = X.Close.ewm(span=21, adjust=False).mean().to_numpy()
    S = (recent & (s5 > 0) & (s5.shift(1) <= 0)).to_numpy() & (e9 > e21)
    out = []; last = -1
    for j in range(30, n - 2):
        if S[j] and j > last:
            e = j + 1; k = next((q + 1 for q in range(e, n - 1) if e9[q] < e21[q]), None)
            if k is None:
                break
            out.append(dict(sym="BANKNIFTY", sys="idx", d=D[e], dx=D[k], ret=o[k] / o[e] - 1 - 0.001, lane="idx")); last = k
    return pd.DataFrame(out)


def curve(X):
    """AC.port logic, returning the equity series marked at exits"""
    X = X.sort_values(["d", "sym"]); eq = 1.0; op = []; pts = []
    for r in X.itertuples():
        for p in sorted([p for p in op if p[0] <= r.d]):
            eq += p[1]; pts.append((p[0], eq))
        op = [p for p in op if p[0] > r.d]
        if len(op) < 10:
            op.append((r.dx, 0.1 * eq * r.ret))
    for p in sorted(op):
        eq += p[1]; pts.append((p[0], eq))
    return pd.Series([v for _, v in pts], index=[d for d, _ in pts]).groupby(level=0).last()


def main():
    T = PF.build(); B = bn_trades()
    print(f"R| Bank Nifty FII trades: {len(B)}, avg {B.ret.mean() * 100:+.2f}%, newest: " + ", ".join(f"{r.d.date()} {r.ret * 100:+.1f}%" for r in B.iloc[::-1].head(8).itertuples()), flush=True)
    base = T[["sym", "sys", "d", "dx", "ret", "lane"]]
    keep = ~base.lane.isin(["weak", "fade", "bounce"])
    V = {"A now (all Cup + Momentum)": base, "B lanes (skip Weak/Fading/Turning)": base[keep],
         "C lanes + Bank Nifty FII trade": pd.concat([base[keep], B]), "D now + Bank Nifty FII trade": pd.concat([base, B])}
    for nm, X in V.items():
        e = curve(X); e = e[e.index >= "2008-01-01"]
        yrs = (e.index[-1] - e.index[0]).days / 365.25; dd = (e / e.cummax() - 1).min() * 100
        y = e.resample("YE").last().ffill(); y = y.pct_change().dropna() * 100
        def since(t):
            z = e[e.index >= t]; p = e[e.index < t]
            if p.empty or z.empty:
                return float("nan")
            yy = max((z.index[-1] - pd.Timestamp(t)).days / 365.25, 0.5)
            return ((z.iloc[-1] / p.iloc[-1]) ** (1 / yy) - 1) * 100
        print(f"R| {nm:36s} trades {len(X):4d} | CAGR {((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100:5.1f}% | maxDD {dd:6.1f}% | "
              f"2021-26 {since('2021-07-01'):5.1f}%/yr | last 2 yrs {since('2024-11-25'):5.1f}%/yr", flush=True)
        print(f"R|    by year: " + " | ".join(f"{d.year}: {v:+.1f}%" for d, v in sorted(y.items(), reverse=True)[:10]), flush=True)


if __name__ == "__main__":
    main()
