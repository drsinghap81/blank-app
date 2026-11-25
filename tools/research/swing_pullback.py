"""Daily swing system from pullbacks to averages, long AND short (25 Nov 2026, Amritpal: "derive a swing trading strategy on daily
time frame whether it's playing the pullback as mean reversion for a short or a long when it takes support at the averages").

LONG  = uptrend (close > rising 200-SMA, 50 > 200), the touched average rising; low dips to the average, close holds near it.
SHORT = mirror: downtrend (close < falling 200-SMA, 50 < 200), the average falling; high rallies up to it, close stays near it.
Entry  "trig" = buy-stop above the touch-day high within 3 sessions (short: sell-stop below its low); cancelled if the stop is hit first.
       "close" = enter at the touch-day close (no confirmation), for comparison.
Stop   = touch-day low (short: high), minimum 1% away, skipped if more than 12%.
Exits  2R  = target 2x risk, else time exit after 15 sessions
       trail = close below 10-EMA (short: above)
       swing = target the high before the pullback (short: the low before the rally), else 15 sessions
Also the classic RSI(2) mean-reversion (buy RSI2 < 10 above 200-SMA, sell first close above 5-SMA; short mirror), stop 2xATR, 10 sessions max.
Baseline = random trend day, same entry/stop/2R logic, stop at the 10-day low (short: high).
Cost 0.4% round trip. Portfolio: 1% risk per trade, max 10 open, max 20% per position, realised equity.
Splits newest-first, bull/bear (breadth: >50% of stocks above 200-SMA), ex-Covid; large caps (today's Nifty 100) and F&O stocks
(only these can actually be shorted overnight, via futures). PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

MKT = os.environ.get("UNIV", "").upper()          # 25 Nov 2026: "" = NSE, or US / ASX / UK
COST = {"US": 0.001, "ASX": 0.002, "UK": 0.006}.get(MKT, 0.004); COVID = (pd.Timestamp("2020-02-15"), pd.Timestamp("2020-12-31"))


def sim(o, h, l, c, i, trig, stop, mode, ex, tgt=None, wait=3, hold=15):
    """Long-side simulator; shorts pass negated, high/low-swapped arrays. Returns (entry bar, exit bar, entry, exit, stop) or None."""
    n = len(c); j0 = None
    if trig is None:
        j0, e = i, c[i]
    else:
        for j in range(i + 1, min(i + 1 + wait, n)):
            if h[j] > trig:
                j0, e = j, max(o[j], trig); break
            if l[j] < stop:
                return None
    if j0 is None:
        return None
    stop = min(stop, e * 0.99) if e > 0 else min(stop, e - abs(e) * 0.01)
    if (e - stop) / abs(e) > 0.12:
        return None
    if tgt is None and mode in ("2R", "rsi"):
        tgt = e + 2 * (e - stop) if mode == "2R" else None
    if j0 > i and l[j0] <= stop:                     # same bar entered and stopped - conservative
        return j0, j0, e, stop, stop
    armed = False                                    # trail: only after a close back above the 10-EMA
    for k in range(j0 + 1, min(j0 + 1 + hold, n)):
        if o[k] <= stop:
            return j0, k, e, o[k], stop
        if l[k] <= stop:
            return j0, k, e, stop, stop
        if tgt is not None and o[k] >= tgt:
            return j0, k, e, o[k], stop
        if tgt is not None and h[k] >= tgt:
            return j0, k, e, tgt, stop
        if ex is not None:
            if mode == "trail":
                if not ex[k]:
                    armed = True
                elif armed:
                    return j0, k, e, c[k], stop
            elif ex[k]:
                return j0, k, e, c[k], stop
    k = min(j0 + hold, n - 1)
    return (j0, k, e, c[k], stop) if k > j0 else None


def rsi(c, p=2):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    if MKT:
        from connors_mr import load_mkt
        P = load_mkt(MKT); tv = pd.Series({k: v.attrs["tv"] for k, v in P.items()}).sort_values(ascending=False)
        big = set(tv.index[:500 if MKT == "US" else 100]); fno = set(tv.index[:1000 if MKT == "US" else 200])
        print(f"R| market {MKT}: large caps = top {len(big)} by turnover, 'F&O' line = top {len(fno)}; cost {COST * 100:.1f}%", flush=True)
    else:
        big = set(); fno = set(pd.read_csv("data/universe/fno_stocks.csv").Symbol.str.strip())
        for f in ("nifty50", "niftynext50"):
            big |= set(pd.read_csv(f"data/universe/{f}.csv").Symbol.str.strip())
        P = FV.load()
    br = pd.concat({s: (x.CLOSE > x.CLOSE.rolling(200).mean()).astype(float).where(x.CLOSE.rolling(200).mean().notna()) for s, x in P.items()}, axis=1).mean(axis=1)
    print(f"R| {len(P)} stocks loaded; bull = more than half of stocks above their 200-SMA", flush=True)
    T = []; rng = np.random.default_rng(7)
    for sym, x in P.items():
        o0, h0, l0, c0 = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index; n = len(c0); c = x.CLOSE
        M = {"EMA20": c.ewm(span=20, adjust=False).mean(), "SMA50": c.rolling(50).mean(), "SMA100": c.rolling(100).mean()}
        e10 = c.ewm(span=10, adjust=False).mean().to_numpy(float); s5 = c.rolling(5).mean().to_numpy(float)
        s200 = c.rolling(200).mean(); s50 = M["SMA50"]
        UP = ((c > s200) & (s200 > s200.shift(20)) & (s50 > s200)).to_numpy()
        DN = ((c < s200) & (s200 < s200.shift(20)) & (s50 < s200)).to_numpy()
        stack = ((c.ewm(span=10, adjust=False).mean() > M["EMA20"]) & (M["EMA20"] > s50) & (s50 > M["SMA100"]) & (M["SMA100"] > s200)).to_numpy()
        r2 = rsi(c).to_numpy(float)
        tr = pd.concat([x.HIGH - x.LOW, (x.HIGH - c.shift()).abs(), (x.LOW - c.shift()).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy(float)
        hh20 = x.HIGH.rolling(20).max().to_numpy(float); ll20 = x.LOW.rolling(20).min().to_numpy(float)
        ll10 = x.LOW.rolling(10).min().to_numpy(float); hh10 = x.HIGH.rolling(10).max().to_numpy(float)
        for side in ("L", "S"):
            if side == "L":
                o, h, l, cc = o0, h0, l0, c0; TR = UP; sg = 1
            else:
                o, h, l, cc = -o0, -l0, -h0, -c0; TR = DN; sg = -1
            ex_tr = (cc < sg * e10); ex_s5 = (cc > sg * s5)          # trail exit / RSI2 exit (both in transformed space)
            def add(i, name, r, extra=None):
                if r is None:
                    return
                j0, k, e, xp, st = r
                T.append(dict(sym=sym, side=side, v=name, d=D[i], dx=D[k], hold=k - j0, R=(xp - e) / (e - st) - COST / ((e - st) / abs(e)),
                              pct=(xp - e) / abs(e) - COST, risk=(e - st) / abs(e), bull=bool(br.get(D[i], np.nan) > 0.5),
                              big=sym in big, fno=sym in fno, stack=bool(stack[i]) if side == "L" else False, **(extra or {})))
            for m in ("EMA20", "SMA50", "SMA100"):
                mv = sg * M[m].to_numpy(float); mv10 = sg * M[m].shift(10).to_numpy(float); last = -99
                for i in range(220, n - 2):
                    if l[i] <= mv[i] * (1.005 if sg > 0 else 0.995):      # touch (in transformed space, "low" reaches the average)
                        if TR[i] and mv[i] > mv10[i] and cc[i] >= mv[i] - abs(mv[i]) * 0.01 and i - last > 10:
                            st = l[i]; sw = sg * (hh20[i] if sg > 0 else ll20[i])
                            add(i, f"{m} trig 2R", sim(o, h, l, cc, i, h[i], st, "2R", None))
                            add(i, f"{m} trig trail", sim(o, h, l, cc, i, h[i], st, "trail", ex_tr, hold=40))
                            add(i, f"{m} trig swing", sim(o, h, l, cc, i, h[i], st, "swing", None, tgt=sw))
                            add(i, f"{m} close 2R", sim(o, h, l, cc, i, None, st, "2R", None))
                        last = i
            last = -99
            for i in range(220, n - 2):                                   # RSI(2) mean reversion
                if TR[i] and (r2[i] < 10 if sg > 0 else r2[i] > 90) and i - last > 5 and tr[i] > 0:
                    add(i, "RSI2 close", sim(o, h, l, cc, i, None, cc[i] - 2 * tr[i], "rsi", ex_s5, hold=10)); last = i
            for i in range(220, n - 2):                                   # random trend day baseline
                if TR[i] and rng.random() < 0.04:
                    st = sg * (ll10[i] if sg > 0 else hh10[i])
                    add(i, "RANDOM trig 2R", sim(o, h, l, cc, i, h[i], st, "2R", None))
    T = pd.DataFrame(T)
    T.to_csv("/tmp/swing_trades.csv", index=False)

    def port(X):
        X = X.sort_values(["d", "sym"]); eq = 1.0; openp = []; curve = []; peak = 1.0; mdd = 0.0
        for r in X.itertuples():
            done = [p for p in openp if p[0] <= r.d]
            for p in sorted(done):
                eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
            openp = [p for p in openp if p[0] > r.d]
            if len(openp) >= 10:
                continue
            val = min(0.01 / max(r.risk, 1e-3), 0.2) * eq; openp.append((r.dx, val * r.pct))
        for p in sorted(openp):
            eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        yrs = max((X.dx.max() - X.d.min()).days / 365.25, 1)
        return (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100, mdd * 100

    def s(X):
        if len(X) < 30:
            return f"n {len(X)}"
        g = X.R[X.R > 0].sum(); b = -X.R[X.R < 0].sum(); xc = X[~X.d.between(*COVID)]
        return (f"n {len(X):6d} | win {(X.R > 0).mean() * 100:3.0f}% | avg {X.R.mean():+.2f}R ({X.pct.mean() * 100:+.2f}%) | PF {g / max(b, 1e-9):.2f} | hold {X.hold.mean():4.1f}d"
                f" | bull {X[X.bull].R.mean():+.2f}R bear {X[~X.bull].R.mean():+.2f}R | ex-Covid {xc.R.mean():+.2f}R")
    for side, nm in (("L", "LONG (buy the dip in an uptrend)"), ("S", "SHORT (sell the rally in a downtrend)")):
        print(f"R| ===== {nm} =====", flush=True)
        for v in sorted(T[T.side == side].v.unique(), key=lambda z: (z.startswith("RANDOM"), z)):
            X = T[(T.side == side) & (T.v == v)]
            cg, dd = port(X)
            print(f"R| {v:18s} {s(X)} | portfolio CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        best = T[(T.side == side) & ~T.v.str.startswith("RANDOM")].groupby("v").R.mean().sort_values(ascending=False).index[:4]
        for v in best:
            X = T[(T.side == side) & (T.v == v)]
            yr = X.groupby(X.d.dt.year).R.agg(["size", "mean"]).sort_index(ascending=False)
            print(f"R| {v} by year (n, avg R): " + " | ".join(f"{y}: {int(r['size'])} {r['mean']:+.2f}" for y, r in yr.iterrows()), flush=True)
            for lab, Z in (("large caps", X[X.big]), ("F&O stocks", X[X.fno]), ("stacked averages", X[X["stack"]]) if side == "L" else ("", X.iloc[:0])):
                if lab:
                    cg, dd = port(Z)
                    print(f"R| {v} | {lab:16s} {s(Z)} | CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)


if __name__ == "__main__":
    main()
