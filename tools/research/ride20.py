"""'Ride the 20 SMA, then shoot' (27 Nov 2026, Amritpal on a Symbiotec chart: "it's slowly heading up and instead of closing below
the 20 SMA, when it gives a close above it, it shoots" -> "backtest this concept").
NSE stocks (Yahoo 2015-26, today's names - survivors), daily, liquidity >= Rs 2 cr/day (20-day), price >= 50.
Uptrend (all versions): close > SMA50, SMA20 rising (above its value 10 sessions ago).
RIDE (the concept): the last N sessions (N = 10 / 15) all CLOSED at or above the 20 SMA, at least one low came within 1.5% of it
  (price leaned on it), and the window drifted slowly: high-to-low range <= 12% (N=10) / 15% (N=15).
TRIGGER: today closes above the highest close of the window (the top of the slow drift) -> buy next open.
  + VOL variant: trigger day volume >= 1.5x its 20-day average.
CONTROL: same uptrend, close above the previous 15-day highest close, without the ride condition (any breakout).
Outcomes (0.4% cost): forward 21 / 63 sessions (close) and vs Nifty; TRADE = buy next open, exit next open after the first close
below the 20 SMA (the concept's own exit), max 120 sessions. One signal per stock per 10 sessions.
Newest first: last 1y, last 3y, 2021+ (ex-Covid), 2016+. PILOT env = 150 stocks."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.004


def events(x, nif):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL"))
    C = x.CLOSE; n = len(c)
    s20 = C.rolling(20).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy()
    v20 = x.VOL.rolling(20).mean().shift(1).to_numpy(); val = (x.CLOSE * x.VOL).rolling(20).mean().to_numpy() / 1e7
    out = []; last = {}
    for i in range(70, n - 2):
        if not (c[i] > s50[i] and s20[i] > s20[i - 10] and val[i] >= 2 and c[i] >= 50):
            continue
        kinds = []
        prev15 = c[i - 15:i].max()
        if c[i] > prev15:
            kinds.append("control")
        for N, rng in ((10, 0.12), (15, 0.15)):
            a = i - N
            w_c, w_l, w_h, w_s = c[a:i], l[a:i], h[a:i], s20[a:i]
            if np.isnan(w_s).any():
                continue
            ride = (w_c >= w_s).all() and (w_l <= w_s * 1.015).any() and (w_h.max() / w_l.min() - 1 <= rng)
            if ride and c[i] > w_c.max():
                kinds.append(f"ride{N}")
                if v[i] >= 1.5 * v20[i]:
                    kinds.append(f"ride{N}+vol")
        kinds = [k for k in kinds if i - last.get(k, -99) >= 10]        # one signal per stock per 10 sessions, per version
        if not kinds:
            continue
        for k in kinds:
            last[k] = i
        e = o[i + 1]
        if e <= 0:
            continue
        fw = {}
        for H in (21, 63):
            j = min(i + H, n - 1)
            fw[H] = c[j] / e - 1 - COST
            d0, d1 = x.index[i + 1], x.index[j]
            nn = nif[(nif.index >= d0) & (nif.index <= d1)]
            fw[f"x{H}"] = fw[H] - ((nn.iloc[-1] / nn.iloc[0] - 1) if len(nn) > 1 else 0)
        # trade: exit next open after the first close below the 20 SMA
        k = i + 1; xr = None
        while k < min(n - 1, i + 121):
            if c[k] < s20[k]:
                xr = o[k + 1] / e - 1 - COST; break
            k += 1
        if xr is None:
            xr = c[min(n - 1, i + 120)] / e - 1 - COST
        # short-term views (27 Nov 2026, "it's a short term system"): 3 / 5 / 10-session closes, and a swing trade with the stop
        # under the trigger day's low and a 2R / 3R target, max 10 sessions (stop first if both touched in a day)
        st_ = {}
        for H in (3, 5, 10):
            st_[f"r{H}"] = c[min(i + H, n - 1)] / e - 1 - COST
        risk = e - l[i]
        for T in (2, 3):
            res_ = None
            if risk > 0:
                for k2 in range(i + 1, min(n, i + 11)):
                    if l[k2] <= l[i]:
                        res_ = (min(o[k2], l[i]) if k2 > i + 1 else l[i]) / e - 1 - COST; break
                    if h[k2] >= e + T * risk:
                        res_ = (max(o[k2], e + T * risk) if k2 > i + 1 else e + T * risk) / e - 1 - COST; break
                if res_ is None:
                    res_ = c[min(n - 1, i + 10)] / e - 1 - COST
                st_[f"t{T}"] = res_; st_[f"t{T}R"] = (res_ + COST) * e / risk
            else:
                st_[f"t{T}"] = np.nan; st_[f"t{T}R"] = np.nan
        st_["riskpct"] = risk / e * 100
        out.append(dict(d=x.index[i], kinds=kinds, r21=fw[21], r63=fw[63], x21=fw["x21"], x63=fw["x63"], tr=xr, hold=k - i, **st_))
    return out


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    E = []
    for s, x in P.items():
        for e in events(x, nif):
            e["s"] = s; E.append(e)
    D = pd.DataFrame(E)
    print(f"R| stocks {len(P)} events {len(D)}", flush=True)
    end = D.d.max()
    res = {}
    for kind in ("control", "ride10", "ride10+vol", "ride15", "ride15+vol"):
        Z = D[D.kinds.apply(lambda k: kind in k)]
        res[kind] = {}
        for lab, st in (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)),
                        ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01"))):
            z = Z[Z.d >= st]
            if len(z) < 20:
                continue
            row = dict(n=len(z), r21=z.r21.mean() * 100, r63=z.r63.mean() * 100, med63=z.r63.median() * 100, win63=(z.r63 > 0).mean() * 100,
                       x63=z.x63.mean() * 100, tr=z.tr.mean() * 100, trmed=z.tr.median() * 100, trwin=(z.tr > 0).mean() * 100, hold=z.hold.median())
            row.update(r3=z.r3.mean() * 100, r5=z.r5.mean() * 100, r10=z.r10.mean() * 100, w5=(z.r5 > 0).mean() * 100,
                       t2=z.t2.mean() * 100, t2R=z.t2R.mean(), t2w=(z.t2 > 0).mean() * 100, t3=z.t3.mean() * 100, t3R=z.t3R.mean(), risk=z.riskpct.median())
            print(f"R| {kind:11s} {lab:15s} SHORT | 3d {row['r3']:+5.2f}% 5d {row['r5']:+5.2f}% (win {row['w5']:3.0f}%) 10d {row['r10']:+5.2f}% | "
                  f"stop=trigger low, 2R target <=10d: {row['t2']:+5.2f}% ({row['t2R']:+.2f}R, win {row['t2w']:3.0f}%) | 3R: {row['t3']:+5.2f}% "
                  f"({row['t3R']:+.2f}R) | risk {row['risk']:.1f}%", flush=True)
            res[kind][lab] = row
            print(f"R| {kind:11s} {lab:15s} n {row['n']:5d} | 21d {row['r21']:+5.1f}% | 63d avg {row['r63']:+5.1f}% med {row['med63']:+5.1f}% "
                  f"win {row['win63']:3.0f}% vs Nifty {row['x63']:+5.1f} | TRADE (exit close < 20 SMA) avg {row['tr']:+5.1f}% med {row['trmed']:+5.1f}% "
                  f"win {row['trwin']:3.0f}% hold {row['hold']:.0f}d", flush=True)
        if len(Z):
            yy = Z.groupby(Z.d.dt.year).r63.mean() * 100
            print(f"R|   {kind} years 63d: " + " ".join(f"{y}:{v:+.1f}" for y, v in yy.iloc[::-1].items()), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open(f"data/research/ride20{'_pilot' if PILOT else ''}.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
