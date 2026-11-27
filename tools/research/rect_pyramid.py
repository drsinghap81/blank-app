"""Rectangle breakout + pyramid on RSI 60 near the 30 EMA (28 Nov 2026, Amritpal on Laurus Labs: "after a rectangle breakout, when RSI
crosses 60 and the candle closes above the 30 EMA, no 2 candles after that closed below the 30 EMA" -> "green arrow was pyramiding when
price is near 30 EMA").
NSE stocks (Yahoo 2015-26, survivors), >= Rs 2 cr/day, price >= 50, 0.4% cost a round trip per unit.
RECTANGLE: the previous 80 sessions' high-low range <= 25% (top / bottom); BREAKOUT = first close above the box top.
ENTRY: next session's open (1 unit).
ADD (pyramid, max 4): RSI(14) crosses up through 60 with the close above the 30 EMA, and price came NEAR the 30 EMA (some low of the last
  5 sessions <= 30 EMA x 1.03) -> 1 more unit at the next open. Variant 'any' = same without the near-EMA condition.
EXIT (all units): the second close in a row below the 30 EMA -> next open.
Portfolio: each unit 5% of equity, at most 20 units open; newest windows first, ex-Covid, vs Nifty 50. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

COST = 0.004


def units(sym, x):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index; n = len(c); C = x.CLOSE
    ema = C.ewm(span=30, adjust=False).mean().to_numpy()
    dl = C.diff(); up = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn)).to_numpy()
    val = (C * x.VOL).rolling(20).mean().to_numpy() / 1e7
    out = []; i = 130
    while i < n - 2:
        top = h[i - 80:i].max(); bot = l[i - 80:i].min()
        if not (val[i] >= 2 and c[i] >= 50 and top / bot - 1 <= 0.25 and c[i] > top and c[i - 1] <= top):
            i += 1; continue
        j = i + 1; U = [("entry", j, True)]; below = 0; xk = None; adds = {"near": 0, "any": 0}
        for k in range(j, n - 1):
            below = below + 1 if c[k] < ema[k] else 0
            if below >= 2:
                xk = k + 1; break
            if k > i and rsi[k] >= 60 and rsi[k - 1] < 60 and c[k] > ema[k]:
                near = bool(l[max(0, k - 4):k + 1].min() <= ema[k] * 1.03)
                if adds["any"] < 4:
                    adds["any"] += 1; U.append(("add_any", k + 1, near))
                if near and adds["near"] < 4:
                    adds["near"] += 1; U.append(("add_near", k + 1, near))
        px = o[xk] if xk is not None else c[-1]; xd = D[xk] if xk is not None else D[-1]
        for kind, k, near in U:
            out.append(dict(sym=sym, kind=kind, entry=D[k], exit=xd, e=o[k], ret=px / o[k] - 1 - COST, days=(xk or n - 1) - k,
                            open=xk is None, bo=D[i]))
        i = (xk or n) + 1
    return out


def portfolio(T, C, days, unit=0.05, maxu=20, cap0=1_000_000):
    T = T.sort_values("entry"); byday = {d: g for d, g in T.groupby("entry")}
    cash, pos, eq = cap0, [], {}
    for d in days:
        for p in [p for p in pos if p["exit"] <= d and not p["open"]]:
            cash += p["q"] * p["e"] * (1 + p["ret"]); pos.remove(p)
        if d in byday:
            for r in byday[d].itertuples():
                if len(pos) >= maxu:
                    break
                E = cash + sum(p["q"] * p["last"] for p in pos); q = min(unit * E, cash) / r.e
                if q * r.e < 0.01 * E:
                    continue
                cash -= q * r.e; pos.append(dict(sym=r.sym, q=q, e=r.e, ret=r.ret, exit=r.exit, open=r.open, last=r.e))
        for p in pos:
            v = C.get(p["sym"], {}).get(d)
            if v is not None and np.isfinite(v):
                p["last"] = v
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos)
    return pd.Series(eq)


def stats(eq):
    eq = eq.dropna(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.3)) * 100 - 100, (eq / eq.cummax() - 1).min() * 100


def main():
    P = FV.load()
    T = pd.DataFrame([u for s, x in P.items() for u in units(s, x)])
    C = {s: x.CLOSE.to_dict() for s, x in P.items()}
    days = sorted(set().union(*[set(x.index) for x in P.values()])); days = [d for d in days if d >= pd.Timestamp("2016-01-01")]
    T = T[T.entry >= days[0]]
    try:
        b = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna(); b.index = pd.to_datetime(b.index).tz_localize(None)
    except Exception:  # noqa: BLE001
        b = None
    print(f"R| stocks {len(P)} breakouts {int((T.kind == 'entry').sum())} adds near-EMA {int((T.kind == 'add_near').sum())} adds any {int((T.kind == 'add_any').sum())}", flush=True)
    for kind in ("entry", "add_near", "add_any"):
        for lab, st in (("2021+ ex-Covid", "2021-01-01"), ("2016+", "2016-01-01")):
            z = T[(T.kind == kind) & (T.entry >= st)]
            print(f"R| units {kind:8s} {lab:15s} n {len(z):5d} avg {z.ret.mean() * 100:+6.2f}% median {z.ret.median() * 100:+6.2f}% "
                  f"win {(z.ret > 0).mean() * 100:3.0f}% hold {z.days.median():.0f}d", flush=True)
    E = T[T.kind == "entry"]; E21 = E[E.entry >= "2021-01-01"]
    print("R| breakout trades 2021+: share with >=1 near-EMA add " +
          f"{E21.set_index(['sym', 'bo']).index.isin(T[T.kind == 'add_near'].set_index(['sym', 'bo']).index).mean() * 100:.0f}%", flush=True)
    for nm, kinds in (("breakout only", ("entry",)), ("+ adds near 30 EMA", ("entry", "add_near")), ("+ adds any RSI-60 cross", ("entry", "add_any"))):
        Z = T[T.kind.isin(kinds)]
        for lab, st in (("last 1y", days[-1] - pd.DateOffset(years=1)), ("last 3y", days[-1] - pd.DateOffset(years=3)),
                        ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01"))):
            dd = [d for d in days if d >= st]; eq = portfolio(Z[Z.entry >= st], C, dd); cg, md = stats(eq)
            bs = f" | Nifty {stats(b[b.index >= st])[0]:+6.1f}%/yr ({stats(b[b.index >= st])[1]:.0f}%)" if b is not None else ""
            print(f"R| {nm:24s} {lab:15s} {cg:+6.1f}%/yr worst fall {md:6.1f}%{bs}", flush=True)
        eq = portfolio(Z, C, days); yr = eq.resample("YE").last().pct_change().dropna() * 100
        print(f"R|   {nm} years: " + " ".join(f"{d.year}:{v:+.0f}" for d, v in yr.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
