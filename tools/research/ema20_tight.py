"""Clean 20 EMA bounce + TIGHT range before the breakout (28 Nov 2026, Amritpal: "after 2 swing lows, price was trading in a tight
range above the last swing low and close to the 20 EMA when the breakout happens").
Base = tools/research/ema20_bounce.py v3 'swingvol' (clean rising chart, touch of the rising 20 EMA, a breakout candle closing above
the previous swing high on >= 1.5x the 20-day volume, entry above the breakout candle's high + 0.15% for 3 sessions, stop under the
touch low, risk 1-12%, 0.4% cost, 2R target / 10 sessions and other exits). The breakout may come up to 20 sessions after the touch here.
TIGHTNESS, measured on the N = 5 sessions just before the breakout candle:
  rng  = (highest high - lowest low) / last close      -> tight if <= 5% (also tested <= 8%)
  near = largest |close / 20 EMA - 1| in those sessions -> close to the EMA if <= 3%
  held = none of those sessions' lows under the touch (swing) low
Newest first: last 1y, 3y, 2021+ (ex-Covid), 2016+. PILOT env = 150 stocks."""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from ema20_bounce import walk  # noqa: E402

COST, BUF, N = 0.004, 0.0015, 5


def events(x):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); C = x.CLOSE
    vv = x.VOL.to_numpy(float); v20 = x.VOL.rolling(20).mean().shift(1).to_numpy()
    m = C.ewm(span=20, adjust=False).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy()
    e9 = C.ewm(span=9, adjust=False).mean().to_numpy(); e21 = C.ewm(span=21, adjust=False).mean().to_numpy()
    val = (C * x.VOL).rolling(20).mean().to_numpy() / 1e7
    out = []; last = -99
    for t in range(70, n - 6):
        if not (val[t] >= 2 and c[t] >= 50 and c[t] > s50[t] and m[t] > m[t - 5] and l[t] <= m[t] * 1.005 and c[t] >= m[t]):
            continue
        if t - last < 5:
            continue
        last = t; w0 = t - 60
        clean = bool(m[t] > m[w0] and all(m[k] > m[k - 10] for k in range(w0 + 10, t + 1, 10)) and (c[w0:t] >= m[w0:t] * 0.99).all()
                     and sum(1 for k in range(w0, t - 2) if l[k] <= m[k] * 1.005 and c[k] >= m[k] and l[k] < l[k - 1] and l[k] <= l[k + 1]) >= 2)
        shs = [k for k in range(max(2, t - 40), t - 1) if h[k] >= h[k - 1] and h[k] >= h[k - 2] and h[k] >= h[k + 1] and h[k] >= h[k + 2]]
        if not shs:
            continue
        sh = h[shs[-1]]; bk = None
        for k in range(t + 1, min(n - 1, t + 21)):
            if l[k] < l[t]:
                break
            if c[k] > sh and v20[k] and vv[k] >= 1.5 * v20[k]:
                bk = k; break
        if bk is None:
            continue
        a = bk - N
        rng = (h[a:bk].max() - l[a:bk].min()) / c[bk - 1]
        near = max(abs(c[k] / m[k] - 1) for k in range(a, bk))
        held = bool(l[a:bk].min() >= l[t])
        trig = h[bk] * (1 + BUF); stop = l[t]; j = None
        for k in range(bk + 1, min(n, bk + 4)):
            if h[k] >= trig:
                if o[k] > trig * 1.03:
                    break
                j = k; break
            if l[k] < stop:
                break
        if j is None:
            continue
        e = max(o[j], trig)
        if stop >= e or not 0.01 <= (e - stop) / e <= 0.12:
            continue
        R = e - stop
        row = dict(d=x.index[bk], clean=clean, gap=bk - t, rng=rng * 100, near=near * 100, held=held, risk=R / e * 100)
        for rule in ("2R", "3R", "921", "t10"):
            px, _ = walk(o, h, l, c, e9, e21, j, e, stop, rule)
            row[rule + "R"] = (px / e - 1 - COST) / (R / e)
        out.append(row)
    return out


def main():
    P = FV.load()
    D = pd.DataFrame([dict(e, s=s_) for s_, x in P.items() for e in events(x)])
    print(f"R| stocks {len(P)} breakout entries {len(D)} (median 5-day range {D.rng.median():.1f}%, near-EMA {D.near.median():.1f}%)", flush=True)
    end = D.d.max(); g10 = D.gap <= 10
    T5 = (D.rng <= 5) & D.held; T8 = (D.rng <= 8) & D.held; NE = D.near <= 3
    groups = (("clean, as live (<=10 sessions)", D.clean & g10),
              ("clean + tight <=5%", D.clean & g10 & T5),
              ("clean + tight <=8%", D.clean & g10 & T8),
              ("clean + near EMA <=3%", D.clean & g10 & NE),
              ("clean + tight5 + near EMA", D.clean & g10 & T5 & NE),
              ("clean + tight5 + near, <=20 sess", D.clean & T5 & NE),
              ("clean, NOT tight (>8%)", D.clean & g10 & ~T8),
              ("any chart + tight5 + near EMA", g10 & T5 & NE),
              ("any chart, all", g10))
    for nm, msk in groups:
        Z = D[msk]
        for lab, st in (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)),
                        ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01"))):
            z = Z[Z.d >= st]
            if len(z) < 15:
                print(f"R| {nm:34s} {lab:15s} n {len(z)} (too few)", flush=True); continue
            parts = [f"{r} {z[r + 'R'].mean():+.2f}R (win {(z[r + 'R'] > 0).mean() * 100:3.0f}%)" for r in ("2R", "3R", "921", "t10")]
            print(f"R| {nm:34s} {lab:15s} n {len(z):5d} risk {z.risk.median():.1f}% | " + " | ".join(parts), flush=True)


if __name__ == "__main__":
    main()
