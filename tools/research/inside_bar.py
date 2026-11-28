"""Inside candle breakout (28 Nov 2026, Amritpal: "does an inside candle work?").
Inside candle = high below and low above the previous (mother) candle. Daily NSE stocks (Yahoo 2015-26, survivors), >= Rs 2 cr/day,
price >= 100, 0.25% cost a round trip (delivery-style swing), and Bank Nifty / Nifty futures (repo files, 0.06%).
LONG: buy-stop 0.1% above the inside candle's high, valid the next session only (fill at the open on a gap up, skipped if the open is
> 2% above). SHORT (indices only): mirror. Stop: the inside candle's low (tight) or the mother candle's low (wide).
Trend filters: none | uptrend (close > rising 50-day and 50 > 200) | uptrend + near a 52-week high (within 10%).
Exits: 2R target or 10 sessions | 21-EMA close trail (max 60 sessions). Same bar stop & target -> stop. R net of cost.
Control: buy-stop above ANY day's high under the same filters. Newest windows first."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402


def sim(o, h, l, c, e21, j, side, e, stop, mode, cost):
    n = len(c); risk = abs(e - stop)
    for k in range(j, min(n, j + (10 if mode == "2R" else 60))):
        if (side > 0 and l[k] <= stop) or (side < 0 and h[k] >= stop):
            px = stop if k == j else (min(o[k], stop) if side > 0 else max(o[k], stop)); break
        if mode == "2R" and ((side > 0 and h[k] >= e + 2 * risk) or (side < 0 and l[k] <= e - 2 * risk)):
            px = e + side * 2 * risk if k == j else (max(o[k], e + 2 * risk) if side > 0 else min(o[k], e - 2 * risk)); break
        if mode == "ema" and k > j and ((side > 0 and c[k] < e21[k]) or (side < 0 and c[k] > e21[k])):
            px = c[k]; break
    else:
        px = c[min(n - 1, k)]
    ret = side * (px / e - 1) - cost
    return ret, ret / (risk / e)


def events(x, cost, sides=(1,), liquid=True):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); C = x.CLOSE
    e21 = C.ewm(span=21, adjust=False).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy(); s200 = C.rolling(200).mean().to_numpy()
    hi = C.rolling(250, min_periods=120).max().to_numpy()
    val = ((C * x.VOL).rolling(20).mean().to_numpy() / 1e7) if liquid else np.full(n, 99.0)
    out = []
    for t in range(201, n - 1):
        if liquid and not (val[t] >= 2 and c[t] >= 100):
            continue
        inside = h[t] < h[t - 1] and l[t] > l[t - 1]
        up = c[t] > s50[t] > s200[t] and s50[t] > s50[t - 5]
        dn = c[t] < s50[t] < s200[t] and s50[t] < s50[t - 5]
        near = c[t] >= 0.9 * hi[t]
        for side in sides:
            trend = up if side > 0 else dn
            for kind in (("inside", "ctrl") if inside else ("ctrl",)):
                if kind == "ctrl" and t % 5:      # control: a sample of ordinary days
                    continue
                trig = h[t] * 1.001 if side > 0 else l[t] * 0.999; j = t + 1
                if not ((side > 0 and h[j] >= trig) or (side < 0 and l[j] <= trig)):
                    continue
                if (side > 0 and o[j] > trig * 1.02) or (side < 0 and o[j] < trig * 0.98):
                    continue
                e = max(o[j], trig) if side > 0 else min(o[j], trig)
                for sk, stop in (("tight", l[t] if side > 0 else h[t]), ("mother", l[t - 1] if side > 0 else h[t - 1])):
                    if kind == "ctrl" and sk == "mother":
                        continue
                    if (side > 0 and stop >= e) or (side < 0 and stop <= e) or abs(e / stop - 1) > 0.12:
                        continue
                    for mode in ("2R", "ema"):
                        r, R = sim(o, h, l, c, e21, j, side, e, stop, mode, cost)
                        out.append(dict(d=x.index[t], kind=kind, side=side, stop=sk, mode=mode, up=trend, near=near, ret=r, R=R))
    return out


def rep(name, D, end):
    W = [("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)), ("2021+", pd.Timestamp("2021-01-01")),
         ("2016+", pd.Timestamp("2016-01-01"))]
    for side in sorted(D.side.unique(), reverse=True):
        for filt, m in (("no filter", D.up | ~D.up), ("uptrend" if side > 0 else "downtrend", D.up), ("trend + near 52w high", D.up & D.near)):
            if side < 0 and filt.startswith("trend +"):
                continue
            for kind, stop in (("inside", "tight"), ("inside", "mother"), ("ctrl", "tight")):
                for mode in ("2R", "ema"):
                    z = D[m & (D.kind == kind) & (D.stop == stop) & (D.mode == mode) & (D.side == side)]
                    row = []
                    for lab, st in W:
                        y = z[z.d >= st]
                        row.append(f"{lab} n{len(y):6d} {y.ret.mean() * 100:+.2f}% {y.R.mean():+.2f}R win {(y.ret > 0).mean() * 100:3.0f}%" if len(y) >= 20 else f"{lab} -")
                    lab = f"{'LONG' if side > 0 else 'SHORT'} {filt:22s} {'inside' if kind == 'inside' else 'ANY DAY (ctrl)':14s} stop {stop:6s} exit {mode:3s}"
                    print(f"R| {name:6s} {lab} | " + " | ".join(row), flush=True)


def main():
    for nm, f in (("BN", "BANKNIFTY"), ("NIFTY", "NIFTY")):
        x = pd.read_csv(os.path.join(HERE, "..", "..", "data", "futures", f + ".csv"), parse_dates=["Date"]).set_index("Date")
        x = x.rename(columns=str.upper)[["OPEN", "HIGH", "LOW", "CLOSE"]].dropna(); x["VOL"] = 1
        x = x[x.index >= "2010-01-01"]
        rep(nm, pd.DataFrame(events(x, 0.0006, sides=(1, -1), liquid=False)), x.index[-1])
    P = FV.load(); ev = []
    for s, x in P.items():
        ev += events(x, 0.0025)
    rep("STOCKS", pd.DataFrame(ev), max(x.index[-1] for x in P.values()))


if __name__ == "__main__":
    main()
