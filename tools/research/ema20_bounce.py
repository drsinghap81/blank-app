"""Rising 20 EMA bounce on 'clean' charts (28 Nov 2026, Amritpal on TFCILTD: "every swing low that touches a rising 20 EMA, there
is a price jump. I need such clean charts and we can play entry above the high of that swing low candle for 3-4 days").
NSE stocks (Yahoo 2015-26, survivors), >= Rs 2 cr/day, price >= 50, 0.4% cost.
TOUCH candle (day t): uptrend (20 EMA above its value 5 sessions ago, close > SMA50), its low <= 20 EMA x 1.005 (touched or
  dipped under) and it CLOSES >= the 20 EMA; one touch per stock per 5 sessions.
ENTRY: buy-stop at the touch candle's high + 0.15% for the next 4 sessions (cancelled if a session breaks the touch low first;
  a candle touching both = filled then stopped). Gap > 3% above = skipped. STOP: under the touch candle's low (risk <= 12%).
EXITS: 2R target (<= 10 sessions) | 3R (<= 15) | 9/21 close exit | hold 10 sessions.
CLEAN chart (point in time, Amritpal's "every touch jumps"): of this stock's previous touches in the last 250 sessions, the share
  that 'worked' = rose >= 2R above their entry within 10 sessions before hitting their stop. Buckets: no history / 0-33% /
  34-66% / >= 67% worked (with at least 3 earlier touches), and "last 3 all worked".
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


def events(x, mode="touch"):
    """mode touch = buy above the touch candle's high (4 sessions); swing = buy above the previous swing high before the touch
    (valid 10 sessions; cancelled if the touch low breaks first). 28 Nov 2026 v2 (Amritpal: "if only such a clean rising chart I
    enter on breakout of previous swing high")."""
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); C = x.CLOSE
    vv = x.VOL.to_numpy(float); v20 = x.VOL.rolling(20).mean().shift(1).to_numpy()
    m = C.ewm(span=20, adjust=False).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy()
    e9 = C.ewm(span=9, adjust=False).mean().to_numpy(); e21 = C.ewm(span=21, adjust=False).mean().to_numpy()
    val = (C * x.VOL).rolling(20).mean().to_numpy() / 1e7
    out = []; hist = []; last = -99            # hist: (touch day, worked?, resolved-by day)
    for t in range(60, n - 6):
        if not (val[t] >= 2 and c[t] >= 50 and c[t] > s50[t] and m[t] > m[t - 5] and l[t] <= m[t] * 1.005 and c[t] >= m[t]):
            continue
        if t - last < 5:
            continue
        last = t
        # structural clean chart: 20 EMA rising over the last 60 sessions, no close > 1% below it, >= 2 earlier held touches
        w0 = max(0, t - 60)
        clean = bool(t >= 70 and m[t] > m[w0] and all(m[k] > m[k - 10] for k in range(w0 + 10, t + 1, 10))
                     and (c[w0:t] >= m[w0:t] * 0.99).all()
                     and sum(1 for k in range(w0, t - 2) if l[k] <= m[k] * 1.005 and c[k] >= m[k] and l[k] < l[k - 1] and l[k] <= l[k + 1]) >= 2)
        shs = [k for k in range(max(2, t - 40), t - 1) if h[k] >= h[k - 1] and h[k] >= h[k - 2] and h[k] >= h[k + 1] and h[k] >= h[k + 2]]
        t0 = t                                                   # the trigger search starts after this bar
        if mode == "swing":
            if not shs:
                continue
            trig = h[shs[-1]] * (1 + BUF); win = 11
        elif mode == "swingvol":
            # 28 Nov 2026 (Amritpal): a BREAKOUT CANDLE that closes above the previous swing high on >= 1.5x volume (within 10
            # sessions of the touch, touch low not broken first); entry above that candle's high (3 sessions); SL below the swing low
            if not shs:
                continue
            sh = h[shs[-1]]; bk = None
            for k in range(t + 1, min(n - 1, t + 11)):
                if l[k] < l[t]:
                    break
                if c[k] > sh and v20[k] and vv[k] >= 1.5 * v20[k]:
                    bk = k; break
            if bk is None:
                continue
            trig = h[bk] * (1 + BUF); win = 4; t0 = bk
        else:
            trig = h[t] * (1 + BUF); win = 5
        stop = l[t]; j = None
        for k in range(t0 + 1, min(n, t0 + win)):
            hit = h[k] >= trig; brk = l[k] < stop
            if brk and not hit:
                break
            if hit:
                if o[k] > trig * 1.03:
                    break
                j = k; break
        # clean-chart score from EARLIER touches already resolved by day t (point in time)
        prev = [w for (d0, w, rd) in hist if t - 250 <= d0 and rd <= t]
        if j is None:
            hist.append((t, False, t + 4)); continue
        e = max(o[j], trig)
        if stop >= e or (e - stop) / e > 0.12 or (e - stop) / e < 0.01:      # v2: stops under 1% gave absurd R values
            hist.append((t, False, j)); continue
        R = e - stop; worked = False; rd = min(n - 1, j + 10)
        for k in range(j, min(n, j + 11)):
            if l[k] <= stop:
                rd = k; break
            if h[k] >= e + 2 * R:
                worked = True; rd = k; break
        hist.append((t, worked, rd))
        row = dict(d=x.index[t], clean=clean, nprev=len(prev), share=(sum(prev) / len(prev)) if prev else None,
                   last3=bool(len(prev) >= 3 and all(prev[-3:])), risk=R / e * 100)
        for rule in ("2R", "3R", "921", "t10"):
            px, _ = walk(o, h, l, c, e9, e21, j, e, stop, rule)
            row[rule + "R"] = (px / e - 1 - COST) / (R / e)
        out.append(row)
    return out


def main():
    P = FV.load()
    for mode in ("swingvol", "swing", "touch"):
        D = pd.DataFrame([dict(e, s=s_) for s_, x in P.items() for e in events(x, mode)])
        print(f"R| ===== entry: {dict(swingvol='above the high of a HIGH-VOLUME candle that closed above the previous swing high', swing='above the previous swing high', touch='above the touch candle high')[mode]}: entries {len(D)}", flush=True)
        end = D.d.max()
        for nm, msk in (("all touches", D.index == D.index), ("CLEAN rising chart", D.clean), ("not clean", ~D.clean)):
            Z = D[msk]
            for lab, st in (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)),
                            ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01"))):
                z = Z[Z.d >= st]
                if len(z) < 15:
                    print(f"R| {mode:8s} {nm:20s} {lab:15s} n {len(z)} (too few)", flush=True); continue
                parts = [f"{r} {z[r + 'R'].mean():+.2f}R (win {(z[r + 'R'] > 0).mean() * 100:3.0f}%)" for r in ("2R", "3R", "921", "t10")]
                print(f"R| {mode:8s} {nm:20s} {lab:15s} n {len(z):6d} risk {z.risk.median():.1f}% | " + " | ".join(parts), flush=True)


if __name__ == "__main__":
    main()
