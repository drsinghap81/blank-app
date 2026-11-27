"""20 SMA undercut-and-hold (28 Nov 2026, Amritpal's correction: "3 swing lows should be below the 20 SMA, but the 3rd swing low
candle closes above the 20 or just at the rising 20" - then the breakout; a short-term system).
NSE stocks (Yahoo 2015-26, today's names = survivors), liquidity >= Rs 2 cr/day, price >= 50. 0.4% cost a round trip.
Uptrend: SMA20 rising (above its value 10 sessions ago) and close > SMA50 at the trigger.
Swing low = a low lower than the 2 sessions on each side (confirmed 2 sessions later).
PATTERN at session i: the last 3 swing lows (all within the last 45 sessions) each traded BELOW that day's 20 SMA (wick under it);
  the 3rd (latest) swing-low candle CLOSED at or above its 20 SMA (>= 0.998 x SMA20 = "just at"), and the 20 SMA was rising then.
TRIGGER: after the 3rd swing low, the first close above the highest high since the 1st swing low (the base top).
ENTRY (Amritpal's usual): buy-stop next session at the trigger candle's high + 0.15% (one session; gap > 3% above = skipped).
STOP: under the 3rd swing low's low (risk > 12% skipped).
EXITS: 2R target (max 10 sessions) | 3R target (max 15) | 9/21 (daily close EMA9 < EMA21 -> next open) | hold 10 sessions.
CONTROL: same uptrend, first close above the 20-day high, same entry / stop under the 10-day low / exits.
Newest first: last 1y, 3y, 2021+ (ex-Covid), 2016+. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

COST, BUF = 0.004, 0.0015


def walk(o, h, l, c, e9, e21, j, e, stop, rule):
    n = len(c); R = e - stop
    tgt = {"2R": 2, "3R": 3}.get(rule); lim = {"2R": 10, "3R": 15, "t10": 10}.get(rule, 250)
    for k in range(j, min(n, j + lim + 1)):
        if l[k] <= stop:
            return (min(o[k], stop) if k > j else stop), k
        if tgt and h[k] >= e + tgt * R:
            return (max(o[k], e + tgt * R) if k > j else e + tgt * R), k
        if rule == "921" and k > j and e9[k] < e21[k] and k + 1 < n:
            return o[k + 1], k + 1
    k = min(n - 1, j + lim); return c[k], k


def events(x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); n = len(c)
    C = x.CLOSE
    s20 = C.rolling(20).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy()
    e9 = C.ewm(span=9, adjust=False).mean().to_numpy(); e21 = C.ewm(span=21, adjust=False).mean().to_numpy()
    val = (C * x.VOL).rolling(20).mean().to_numpy() / 1e7
    sl = [k for k in range(2, n - 2) if l[k] < l[k - 1] and l[k] < l[k - 2] and l[k] < l[k + 1] and l[k] < l[k + 2]]
    out = []; used = set(); last_ctl = -99
    for i in range(80, n - 2):
        if not (val[i] >= 2 and c[i] >= 50 and c[i] > s50[i] and s20[i] > s20[i - 10]):
            continue
        kinds = []
        # pattern: the last 3 swing lows confirmed by i-1 (swing at k is known at k+2 <= i-1)
        lows = [k for k in sl if k + 2 <= i - 1 and k >= i - 45]
        if len(lows) >= 3:
            a, b, z = lows[-3:]
            if (l[a] < s20[a] and l[b] < s20[b] and l[z] < s20[z] and c[z] >= 0.998 * s20[z] and s20[z] > s20[z - 5]
                    and z not in used):
                top = h[a:i].max()
                if c[i] > top and c[i - 1] <= top:
                    kinds.append(("pattern", l[z])); used.add(z)
        if c[i] > h[i - 20:i].max() and i - last_ctl >= 10:
            kinds.append(("control", l[i - 10:i + 1].min())); last_ctl = i
        for kind, stop in kinds:
            trig = h[i] * (1 + BUF); j = i + 1
            if h[j] < trig or o[j] > trig * 1.03:
                continue
            e = max(o[j], trig)
            if stop >= e or (e - stop) / e > 0.12:
                continue
            row = dict(d=x.index[i], kind=kind, risk=(e - stop) / e * 100)
            for rule in ("2R", "3R", "921", "t10"):
                px, k = walk(o, h, l, c, e9, e21, j, e, stop, rule)
                row[rule] = px / e - 1 - COST; row[rule + "R"] = (px / e - 1) / ((e - stop) / e)
            out.append(row)
    return out


def main():
    P = FV.load()
    D = pd.DataFrame([dict(e, s=s) for s, x in P.items() for e in events(x)])
    print(f"R| stocks {len(P)} events {len(D)}", flush=True)
    end = D.d.max()
    for kind in ("control", "pattern"):
        Z = D[D.kind == kind]
        for lab, st in (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)),
                        ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01"))):
            z = Z[Z.d >= st]
            if len(z) < 10:
                print(f"R| {kind:8s} {lab:15s} n {len(z)} (too few)", flush=True); continue
            parts = [f"{r} {z[r].mean() * 100:+5.2f}% ({z[r + 'R'].mean():+.2f}R, win {(z[r] > 0).mean() * 100:3.0f}%)" for r in ("2R", "3R", "921", "t10")]
            print(f"R| {kind:8s} {lab:15s} n {len(z):5d} risk {z.risk.median():.1f}% | " + " | ".join(parts), flush=True)
        if len(Z):
            yy = Z.groupby(Z.d.dt.year)["2RR"].mean()
            print(f"R|   {kind} years (2R exit, avg R): " + " ".join(f"{y}:{v:+.2f}" for y, v in yy.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
