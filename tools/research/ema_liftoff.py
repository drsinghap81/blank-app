"""'Candle leaves the EMA' trend start (19 Nov 2026, Amritpal: "first candle whose whole OHLC is above (or below) EMA 5 or 9
starts a trend in that direction").
Data: continuous near-month futures, daily OHLC 2007 -> Nov 2026 (data/futures/*.csv): BANKNIFTY, NIFTY + 53 F&O stocks.
Signal at the close of day t (EMA of closes):
  LONG  : low > EMA today, and no candle in the previous 10 sessions had its low above the EMA (a FRESH lift-off)
  SHORT : high < EMA today, and none of the previous 10 had its high below the EMA
Entry next open. Exits tested:
  hold 5 / 10 / 20 sessions (close)
  trail : first close back below (long) / above (short) the same EMA -> out next open
  flip  : first candle fully on the other side of the EMA -> out next open
Costs: indices 0.05%, stocks 0.10% round trip. Roll days / splits: daily moves > 20% are dropped from stocks.
Baseline: buying (or shorting) on any day with the same holds. For timing, the 9/21 EMA cross on the same data."""
import glob
import json
import os

import numpy as np
import pandas as pd


def load(f):
    x = pd.read_csv(f, parse_dates=["Date"]).set_index("Date").sort_index()[["Open", "High", "Low", "Close"]].dropna()
    return x[(x > 0).all(axis=1)]


def trades(x, n, side, exit_rule, cost, K=10):
    o, h, l, c = x.Open.values, x.High.values, x.Low.values, x.Close.values
    e = x.Close.ewm(span=n, adjust=False).mean().values
    m = len(c)
    out_side = (l > e) if side == 1 else (h < e)          # candle fully on the trade side
    T = []
    i = 60
    while i < m - 2:
        if out_side[i] and not out_side[i - K:i].any():
            j0 = i + 1; ent = o[j0]
            if exit_rule.startswith("hold"):
                k = min(m - 1, j0 + int(exit_rule[4:]) - 1); px = c[k]
            else:
                k = None
                for j in range(j0, m - 1):
                    if exit_rule == "trail" and ((side == 1 and c[j] < e[j]) or (side == -1 and c[j] > e[j])):
                        k = j + 1; break
                    if exit_rule == "flip" and ((side == 1 and h[j] < e[j]) or (side == -1 and l[j] > e[j])):
                        k = j + 1; break
                if k is None:
                    k = m - 1
                px = o[k] if k < m - 1 or exit_rule != "hold" else c[k]
            r = side * (px / ent - 1) - cost
            T.append((x.index[i], r, k - j0 + 1))
            i = max(i + 1, k) if not exit_rule.startswith("hold") else i + 1
        else:
            i += 1
    return T


def base(x, hold, side, cost):
    o, c = x.Open.values, x.Close.values
    r = [side * (c[min(len(c) - 1, j + hold - 1)] / o[j] - 1) - cost for j in range(61, len(c) - hold)]
    return np.array(r)


def S(T):
    if not len(T):
        return dict(n=0)
    r = np.array([t[1] for t in T]); d = np.array([t[2] for t in T])
    w = r[r > 0].sum(); ls = -r[r < 0].sum()
    yrs = (T[-1][0] - T[0][0]).days / 365.25 if len(T) > 1 else 1
    return dict(n=len(r), win=round(float((r > 0).mean() * 100)), avg=round(float(r.mean() * 100), 2), median=round(float(np.median(r) * 100), 2),
                pf=round(float(w / ls), 2) if ls else None, days=round(float(d.mean()), 1), per_year=round(float(len(r) / max(yrs, 1)), 1))


def main():
    files = sorted(glob.glob("data/futures/*.csv"))
    D = {os.path.basename(f)[:-4]: load(f) for f in files}
    for k, x in D.items():
        if k not in ("NIFTY", "BANKNIFTY"):
            ch = x.Close.pct_change().abs()
            D[k] = x[(ch < 0.2) | ch.isna()]
    res = {"method": __doc__}
    groups = {"BANKNIFTY": ["BANKNIFTY"], "NIFTY": ["NIFTY"], "STOCKS": [k for k in D if k not in ("NIFTY", "BANKNIFTY")]}
    for g, names in groups.items():
        cost = 0.0005 if g != "STOCKS" else 0.001
        res[g] = {}
        for side, sn in ((1, "LONG"), (-1, "SHORT")):
            for hold in (5, 10, 20):
                b = np.concatenate([base(D[k], hold, side, cost) for k in names])
                res[g][f"{sn} any day, hold {hold}"] = dict(n=len(b), win=round(float((b > 0).mean() * 100)), avg=round(float(b.mean() * 100), 2),
                                                             median=round(float(np.median(b) * 100), 2))
            for n in (5, 9):
                for ex in ("hold5", "hold10", "hold20", "trail", "flip"):
                    T = sorted([t for k in names for t in trades(D[k], n, side, ex, cost)], key=lambda t: t[0])
                    res[g][f"{sn} EMA{n} lift-off, {ex}"] = S(T)
                    if g != "STOCKS" and ex == "flip":
                        res[g][f"{sn} EMA{n} lift-off, {ex}"]["recent"] = [(str(t[0].date()), round(t[1] * 100, 1)) for t in T[-6:]]
        for k, v in res[g].items():
            print("R|", g, k, {a: b for a, b in v.items() if a != "recent"}, flush=True)
        for k, v in res[g].items():
            if "recent" in v:
                print("T|", g, k, v["recent"])
    # split halves for the best candidates
    for g in ("BANKNIFTY", "NIFTY", "STOCKS"):
        names = groups[g]; cost = 0.0005 if g != "STOCKS" else 0.001
        for n in (5, 9):
            for ex in ("trail", "flip", "hold10"):
                T = [t for k in names for t in trades(D[k], n, 1, ex, cost)]
                a = S(sorted([t for t in T if t[0] < pd.Timestamp("2017-01-01")])); b = S(sorted([t for t in T if t[0] >= pd.Timestamp("2017-01-01")]))
                print("H|", g, f"LONG EMA{n} {ex}", "2007-16", a, "| 2017-26", b)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/ema_liftoff.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
