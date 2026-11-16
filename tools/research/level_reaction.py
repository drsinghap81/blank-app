"""Do prices reverse or pause at the app's lines and levels? (17 Nov 2026) F&O stocks (current list), 2016 - Nov 2026.

Lines and levels exactly as tools/trendline_scan.py, rebuilt each day from data known that day:
  support line    = latest pair of swing lows (3 bars each side) that no candle cuts, rising
  resistance line = latest pair of swing highs that no candle cuts, any slope
  low level / high level = latest PROMINENT swing (5 bars each side, price moved 3 x ATR away), unbroken by a close
Touch (same as the alert): 5 closes > 1% away, then today's low (support) / high (resistance) within 1% of the line.
Outcomes from the touch-day close (where an option trade would start):
  rev5/rev10  = return in the reversal direction (down from resistance, up from support), %
  held5       = no close beyond the line in the next 5 days, %
  calm5       = |5-day move| < 1 x the expected 5-day move (20-day realised vol x sqrt 5), %  (a "pause")
  straddle    = short 5-day ATM straddle P&L as % of premium, premium = 0.8 x sigma x sqrt(5) (IV assumed = 20-day realised;
                real stock IV is usually higher, so this understates every seller equally - compare with the control)
  spread_ok   = for resistance: close 5 days later still below the line; support: still above (a credit spread at the line wins)
Control: every 3rd day of the same stocks with a pretend line 1% away (same distance as a touch).
Breaks (17 Nov 2026, 2nd run): brk5/10/20 = % of touches with a close beyond the line (above resistance, below support)
within 5/10/20 days; split by trend: uptrend = close > 200-day and 50-day > 200-day, downtrend = both below, else sideways.
Output: data/research/level_reaction.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

rng = np.random.default_rng(3)


def best_line(l, c, m, K=3, tol=0.001, rising=False):
    piv = [i for i in range(K, m - K) if l[i] == l[i - K:i + K + 1].min()]
    for j in range(len(piv) - 1, -1, -1):
        b = piv[j]
        if b < m - 250:
            break
        for k in range(j - 1, -1, -1):
            a = piv[k]
            if b - a < 5:
                continue
            if b - a > 250:
                break
            if rising and l[a] >= l[b]:
                continue
            s = (l[b] - l[a]) / (b - a)
            if (l[a + 1:b] < (l[a] + s * (np.arange(a + 1, b) - a)) * (1 - tol)).any():
                continue
            if b + 1 < m and (c[b + 1:m] < l[b] + s * (np.arange(b + 1, m) - b)).any():
                continue
            return a, b, s
    return None


def outcomes(d, L, side, c, h, l, sig, Lf=None, tr=0):
    if d + 20 >= len(c) or not np.isfinite(sig[d]) or sig[d] <= 0:
        return None
    Lf = np.full(20, L) if Lf is None else np.asarray(Lf)          # line value on days d+1..d+20
    cr = (c[d + 1:d + 21] > Lf) if side == "res" else (c[d + 1:d + 21] < Lf)
    first = int(np.argmax(cr)) + 1 if cr.any() else 99
    sgn = -1 if side == "res" else 1
    r5 = (c[d + 5] / c[d] - 1) * sgn; r10 = (c[d + 10] / c[d] - 1) * sgn
    fut = c[d + 1:d + 6]
    held = (fut <= L).all() if side == "res" else (fut >= L).all()
    exp5 = sig[d] * math.sqrt(5); mv = abs(c[d + 5] / c[d] - 1)
    prem = 0.8 * exp5
    ok = c[d + 5] < L if side == "res" else c[d + 5] > L
    return dict(L=float(L), close=float(c[d]), trend=tr, brk5=first <= 5, brk10=first <= 10, brk20=first <= 20, rev5=r5 * 100, rev10=r10 * 100, held5=bool(held), calm5=bool(mv < exp5), straddle=(prem - mv) / prem * 100, spread_ok=bool(ok))


def scan(sym, df):
    o, h, l, c = (df[k].values.astype(float) for k in ("Open", "High", "Low", "Close"))
    n = len(c); ds = [str(x.date()) for x in df.index]
    lr = np.r_[np.nan, np.diff(np.log(c))]; sig = pd.Series(lr).rolling(20).std().values
    pc = np.r_[c[0], c[:-1]]; atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().values
    s50 = pd.Series(c).rolling(50).mean().values; s200 = pd.Series(c).rolling(200).mean().values
    trend = np.where((c > s200) & (s50 > s200), 1, np.where((c < s200) & (s50 < s200), -1, 0))
    ev = []
    # ---- lines (support on lows, resistance on highs via mirror), recomputed when a pivot confirms or the line breaks
    for side, X, C in (("sup", l, c), ("res", -h, -c)):
        cur = None; K = 3; cnt = {}
        for d in range(260, n):
            m = d + 1
            newpiv = X[d - K] == X[d - 2 * K:d + 1].min()
            if cur is not None:
                a, b, s = cur
                if C[d] < X[b] + s * (d - b):
                    cur = None
            if cur is None or newpiv:
                cur = best_line(X, C, m, rising=side == "sup")
            if cur is None:
                continue
            a, b, s = cur
            if side == "sup" and s <= 0:
                continue
            Lm = lambda i: X[b] + s * (i - b)  # noqa: E731
            if d - b < 6:
                continue
            Ld = Lm(d); L = Ld if side == "sup" else -Ld
            armed = all((c[k] > Lm(k) * 1.01) if side == "sup" else (c[k] < -Lm(k) * 0.99) for k in range(d - 5, d))
            hit = l[d] <= L * 1.01 if side == "sup" else h[d] >= L * 0.99
            if armed and hit:
                cnt[(a, b)] = cnt.get((a, b), 0) + 1        # 1st return to the line after its 2 swing points = the 3rd touch
                Lf = [(Lm(i) if side == "sup" else -Lm(i)) for i in range(d + 1, d + 21)]
                x = outcomes(d, L, side, c, h, l, sig, Lf, trend[d])
                if x:
                    ev.append(dict(sym=sym, d=ds[d], kind="line", side=side, nth=cnt[(a, b)] + 2, **x))
    # ---- prominent horizontal levels
    K = 5
    for side in ("res", "sup"):
        x = h if side == "res" else l
        piv = [i for i in range(K, n - K) if (x[i] == x[i - K:i + K + 1].max() if side == "res" else x[i] == x[i - K:i + K + 1].min())]
        act = np.full(n, np.nan)                       # level active on each day (latest pivot wins)
        for p in piv:
            if not np.isfinite(atr[p]):
                continue
            v = x[p]; after = np.arange(p + 1, n)
            br = np.where(c[p + 1:] > v)[0] if side == "res" else np.where(c[p + 1:] < v)[0]
            pr = np.where(l[p + 1:] <= v - 3 * atr[p])[0] if side == "res" else np.where(h[p + 1:] >= v + 3 * atr[p])[0]
            if not len(pr):
                continue
            start = max(p + K, p + 1 + pr[0] + 1); end = min(p + 1 + br[0] if len(br) else n, p + 250)
            if start < end:
                act[start:end] = v                     # later pivots overwrite earlier ones: latest prominent swing
        for d in range(260, n - 20):
            v = act[d]
            if not np.isfinite(v) or not (act[d - 5:d] == v).all():
                continue
            armed = (c[d - 5:d] < v * 0.99).all() if side == "res" else (c[d - 5:d] > v * 1.01).all()
            hit = h[d] >= v * 0.99 if side == "res" else l[d] <= v * 1.01
            if armed and hit:
                y = outcomes(d, v, side, c, h, l, sig, None, trend[d])
                if y:
                    ev.append(dict(sym=sym, d=ds[d], kind="level", side=side, **y))
    # ---- control: pretend line 1% away every 3rd day
    for d in range(260, n - 20, 3):
        for side in ("res", "sup"):
            L = c[d] * (1.01 if side == "res" else 0.99)
            y = outcomes(d, L, side, c, h, l, sig, None, trend[d])
            if y:
                ev.append(dict(sym=sym, d=ds[d], kind="control", side=side, **y))
    return ev


def summ(E):
    if not len(E):
        return {}
    t = lambda s: round(s.mean() / (s.std() / math.sqrt(len(s))), 2)  # noqa: E731
    return dict(n=len(E), rev5=round(E.rev5.mean(), 2), rev10=round(E.rev10.mean(), 2), t_rev10=t(E.rev10), held5=round(E.held5.mean() * 100, 1),
                calm5=round(E.calm5.mean() * 100, 1), straddle=round(E.straddle.mean(), 1), straddle_med=round(E.straddle.median(), 1),
                spread_ok=round(E.spread_ok.mean() * 100, 1), brk5=round(E.brk5.mean() * 100, 1), brk10=round(E.brk10.mean() * 100, 1),
                brk20=round(E.brk20.mean() * 100, 1))


def main():
    syms = pd.read_csv("data/universe/fno_stocks.csv").Symbol.tolist()
    ev = []
    for k in range(0, len(syms), 50):
        batch = [s + ".NS" for s in syms[k:k + 50]]
        D = yf.download(batch, start="2015-01-01", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = D[s].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) >= 400:
                ev += scan(s[:-3], df)
        print("done", k + 50, len(ev), flush=True)
    E = pd.DataFrame(ev); E = E[E.d >= "2016-01-01"]
    out = dict(method=__doc__, groups={})
    for kind in ("line", "level", "control"):
        for side in ("res", "sup"):
            g = summ(E[(E.kind == kind) & (E.side == side)])
            key = f"{kind} {'resistance' if side == 'res' else 'support'}"
            out["groups"][key] = g; print(key, g, flush=True)
    for kind in ("line", "level", "control"):
        for side in ("res", "sup"):
            for tr, tn in ((1, "uptrend"), (-1, "downtrend"), (0, "sideways")):
                g = summ(E[(E.kind == kind) & (E.side == side) & (E.trend == tr)])
                key = f"{kind} {'resistance' if side == 'res' else 'support'} | {tn}"
                out["groups"][key] = {k: g.get(k) for k in ("n", "brk5", "brk10", "brk20", "rev10", "held5")}; print(key, out["groups"][key], flush=True)
    for kind in ("line", "level"):
        X = E[E.kind == kind]; yr = X.groupby(X.d.str[:4]).straddle.mean().round(1).to_dict()
        out["groups"][f"{kind} straddle by year"] = yr; print(kind, "straddle by year", yr)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/level_reaction.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
