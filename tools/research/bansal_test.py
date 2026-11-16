"""Book strategies (Bansal; rules summarised privately in the project) tested on Nifty 500 stocks, 2016 - Nov 2026 (17 Nov 2026).
Liquid only (median 60-day traded value >= Rs 5 cr, price >= 50). Swing points: lowest low / highest high with 5 days each
side, used only once confirmed (5 days later). Costs 0.3% round trip. Current Nifty 500 members (survivorship bias).

1  DIV  Bottom buy on positive divergence: in a downtrend (last 2 swing lows AND last 2 swing highs falling), price makes a
        lower low but RSI(14) [or MACD line] at that low is higher than at the previous low. Buy on the first close above the
        lower top between the two lows (within 40 days, before a new low). Stop: 0.5% under the new low. Exit: trail the
        stop to each new confirmed higher swing low (book: hold until a lower low). Control "NODIV": same setup, no divergence.
2a TLC  Uptrend correction break: uptrend (close > 200-day, 50-day > 200-day at the correction high), the correction fell
        >= 8% from a 60-day high; a falling line through the 2 latest swing highs of the correction (no candle above it);
        buy the first close above that line. Stop 5% under the entry. Target +17% (book 17-20%), else trail as in 1, max
        120 days. Also "trail only" (no target).
2b SHK  Shakeout: rising support line through the 2 latest swing lows (no candle cuts, app rule); a close below it, then a
        close back above it within 5 days -> buy at that close. Stop 0.5% under the low made below the line. Target +17%,
        else trail; max 120 days.
3  DB / TB / IHS with the book's stops: after a fall (250-day high >= 20% above the first low). DB: 2 swing lows within
        3%, >= 15 days apart, the peak between >= 10% above them. TB: 3 lows within 4%. IHS: middle low >= 3% under both
        shoulders, shoulders within 6%. Neckline = highest high between the first and last low. Buy the first CLOSE above
        the neckline within 40 days of the last low. Stop: 4% under the neckline (IHS 6%). Target: neckline + (neckline -
        lowest low). Max 250 days. Variant "+vol": breakout volume >= 1.5 x its 50-day average (book: skip low volume).
Control for every strategy: a random liquid stock on the same day with the same % stop, % target, max hold and (where used)
the same trailing rule on its own swing lows.
Output: data/research/bansal_test.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

K, COST = 5, 0.003
rng = np.random.default_rng(17)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).values


def run(o, h, l, c, e, entry, stop, target, hold, trail_lows=None):
    """Walk from bar e (entry at `entry` on bar e's close or open). Stop/target on daily lows/highs (stop first).
    trail_lows: list of (confirm_bar, low) - stop rises to each confirmed higher swing low after entry."""
    n = len(c); st = stop; ti = 0
    tl = sorted(trail_lows or [])
    for k in range(e + 1, min(e + hold + 1, n)):
        while ti < len(tl) and tl[ti][0] <= k - 1:
            if tl[ti][1] > st and tl[ti][0] > e:
                st = tl[ti][1] * 0.995
            ti += 1
        if l[k] <= st:
            return k, min(st, o[k]), "stop"
        if target and h[k] >= target:
            return k, max(target, o[k]), "target"
    k = min(e + hold, n - 1)
    return k, c[k], "time"


def scan(sym, df):
    o, h, l, c, v = (df[x].values.astype(float) for x in ("Open", "High", "Low", "Close", "Volume"))
    n = len(c); ds = [str(x.date()) for x in df.index]
    val = pd.Series(c * v).rolling(60).median().values; v50 = pd.Series(v).rolling(50).mean().values
    s50 = pd.Series(c).rolling(50).mean().values; s200 = pd.Series(c).rolling(200).mean().values
    R = rsi(c); ema = lambda x, s: pd.Series(x).ewm(span=s, adjust=False).mean().values  # noqa: E731
    macd = ema(c, 12) - ema(c, 26)
    pl = [i for i in range(K, n - K) if l[i] == l[i - K:i + K + 1].min()]
    ph = [i for i in range(K, n - K) if h[i] == h[i - K:i + K + 1].max()]
    trail = [(i + K, l[i]) for i in pl]                 # swing low known K bars later
    liq = lambda i: val[i] >= 5e7 and c[i] >= 50        # noqa: E731
    out = []

    def add(kind, e, entry, stop, target, hold, use_trail):
        if e + 1 >= n or not liq(e) or entry <= stop or ds[e] < "2016-01-01":
            return
        x, px, why = run(o, h, l, c, e, entry, stop, target, hold, trail if use_trail else None)
        out.append(dict(sym=sym, kind=kind, d=ds[e], exit_d=ds[x], ret=px / entry - 1 - COST, why=why, risk=1 - stop / entry,
                        tgt=(target / entry - 1) if target else np.nan, days=x - e, hold=hold, trail=bool(use_trail)))

    # ---------- 1 divergence bottom buy
    for j in range(1, len(pl)):
        a, b = pl[j - 1], pl[j]
        if l[b] >= l[a]:
            continue
        hs = [p for p in ph if a < p < b]
        prev_h = [p for p in ph if p < a]
        if not hs or not prev_h:
            continue
        top = max(hs, key=lambda p: h[p])
        if h[top] >= h[prev_h[-1]]:                    # need lower tops too (downtrend)
            continue
        divR = R[b] > R[a]; divM = macd[b] > macd[a]
        for k in range(b + K, min(b + 40, n)):          # pattern known K bars after the low
            if l[k] < l[b]:
                break
            if c[k] > h[top]:
                stop = l[b] * 0.995
                for kind, ok in (("DIV rsi", divR), ("DIV macd", divM), ("NODIV", True)):
                    if ok:
                        add(kind, k, c[k], stop, None, 250, True)
                break
    # ---------- 2a uptrend correction: falling line through 2 swing highs, break up
    for j in range(1, len(ph)):
        a, b = ph[j - 1], ph[j]
        if h[b] >= h[a] or a < 200 or not (c[a] > s200[a] and s50[a] > s200[a]) or h[a] < h[max(0, a - 60):a + 1].max():
            continue
        low_c = l[a:b + K + 1].min()
        if low_c > h[a] * 0.92:
            continue
        s = (h[b] - h[a]) / (b - a)
        if (h[a + 1:b] > h[a] + s * (np.arange(a + 1, b) - a) + 1e-9).any():
            continue
        for k in range(b + K, min(b + 60, n)):
            line = h[b] + s * (k - b)
            if c[k] > line:
                add("TLC +17%", k, c[k], c[k] * 0.95, c[k] * 1.17, 120, True)
                add("TLC trail", k, c[k], c[k] * 0.95, None, 250, True)
                break
            if j + 1 < len(ph) and k >= ph[j + 1] + K:   # a newer swing high redraws the line
                break
    # ---------- 2b shakeout of a rising support line (latest 2 swing lows, no candle cuts)
    for j in range(1, len(pl)):
        a, b = pl[j - 1], pl[j]
        if l[b] <= l[a] or b - a < 5:
            continue
        s = (l[b] - l[a]) / (b - a)
        if (l[a + 1:b] < (l[a] + s * (np.arange(a + 1, b) - a)) * 0.999).any():
            continue
        nxt = pl[j + 1] + K if j + 1 < len(pl) else n
        k = b + K
        while k < min(nxt, b + 250, n - 1):
            if c[k] < l[b] + s * (k - b):              # close below the line
                lo = l[k]
                for m in range(k + 1, min(k + 6, n)):
                    lo = min(lo, l[m])
                    if c[m] > l[b] + s * (m - b):
                        add("SHK +17%", m, c[m], lo * 0.995, c[m] * 1.17, 120, True)
                        add("SHK trail", m, c[m], lo * 0.995, None, 250, True)
                        break
                break
            k += 1
    # ---------- 3 bottom patterns with the book's fixed % stops
    used = -1
    for j in range(1, len(pl)):
        cands = []
        a, b = pl[j - 1], pl[j]
        if abs(l[b] / l[a] - 1) <= 0.03 and b - a >= 15:
            cands.append(("DB", [a, b], 0.96))
        if j >= 2:
            x, y, z = pl[j - 2], pl[j - 1], pl[j]
            lows = [l[x], l[y], l[z]]
            if max(lows) / min(lows) - 1 <= 0.04:
                cands.append(("TB", [x, y, z], 0.96))
            if l[y] <= min(l[x], l[z]) * 0.97 and abs(l[z] / l[x] - 1) <= 0.06:
                cands.append(("IHS", [x, y, z], 0.94))
        for kind, pts, sf in cands:
            f, last = pts[0], pts[-1]
            if f < 250 or last <= used:
                continue
            lowest = min(l[p] for p in pts)
            if h[f - 250:f].max() < lowest * 1.20:
                continue
            neck = h[f:last + 1].max()
            if kind == "DB" and neck < lowest * 1.10:
                continue
            for k in range(last + K, min(last + 40, n)):
                if l[k] < lowest:
                    break
                if c[k] > neck:
                    tgt = neck + (neck - lowest)
                    add(kind, k, c[k], neck * sf, tgt, 250, False)
                    if np.isfinite(v50[k - 1]) and v[k] >= 1.5 * v50[k - 1]:
                        add(kind + " +vol", k, c[k], neck * sf, tgt, 250, False)
                    used = last
                    break
    return out


def control(T, frames, keys):
    """Random liquid stock, same day, same % stop / % target / max hold (fixed stop, no trail)."""
    res = []
    for x in T.itertuples():
        for _ in range(3):
            s = keys[rng.integers(len(keys))]; idx, arr, tr = frames[s]
            if x.d not in idx:
                continue
            e = idx[x.d]; o, h, l, c = arr
            if c[e] < 50:
                continue
            P = c[e]; tgt = P * (1 + x.tgt) if np.isfinite(x.tgt) else None
            k, px, why = run(o, h, l, c, e, P, P * (1 - x.risk), tgt, int(x.hold), tr if x.trail else None)
            res.append(dict(kind=x.kind, ret=px / P - 1 - COST, why=why)); break
    return pd.DataFrame(res)


def stats(X):
    if not len(X):
        return {}
    r = X.ret
    return dict(n=len(X), per_yr=round(len(X) / 10.9, 1), win=round((r > 0).mean() * 100, 1), avg=round(r.mean() * 100, 2), med=round(r.median() * 100, 2),
                t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2) if len(r) > 2 else None, target_hit=round((X.why == "target").mean() * 100, 1),
                stop_hit=round((X.why == "stop").mean() * 100, 1), avg_days=round(X.days.mean()) if "days" in X else None,
                avg_R=round((r / X.risk).mean(), 2) if "risk" in X else None,
                pos_years=f"{int((X.groupby(X.d.str[:4]).ret.sum() > 0).sum())}/{X.d.str[:4].nunique()}" if "d" in X else None)


def portfolio(T, cap=2e6):
    T = T.sort_values("d"); eq = cap; open_ = []; curve = []
    for x in T.itertuples():
        open_ = [e for e in open_ if e > x.d]
        if len(open_) >= 10 or x.risk <= 0:
            continue
        frac = min(0.01 / x.risk, 0.10)
        eq += eq * frac * x.ret; open_.append(x.exit_d); curve.append((x.exit_d, eq))
    if not curve:
        return {}
    s = pd.Series([e for _, e in curve], index=pd.to_datetime([d for d, _ in curve])).sort_index()
    yrs = (s.index[-1] - pd.Timestamp("2016-01-01")).days / 365.25
    return dict(cagr=round(((s.iloc[-1] / cap) ** (1 / yrs) - 1) * 100, 1), max_dd=round((s / s.cummax() - 1).min() * 100, 1), trades=len(curve))


def main():
    syms = pd.read_csv("data/universe/nifty500.csv").Symbol.tolist()
    frames, ev = {}, []
    for k in range(0, len(syms), 50):
        batch = [s + ".NS" for s in syms[k:k + 50]]
        D = yf.download(batch, start="2014-06-01", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = D[s].dropna(subset=["Close", "Low", "High", "Open"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) < 500:
                continue
            ev += scan(s[:-3], df)
            lw = df.Low.values.astype(float)
            tr = [(i + K, lw[i]) for i in range(K, len(lw) - K) if lw[i] == lw[i - K:i + K + 1].min()]
            frames[s[:-3]] = ({str(x.date()): i for i, x in enumerate(df.index)}, tuple(df[x].values.astype(float) for x in ("Open", "High", "Low", "Close")), tr)
        print("done", k + 50, len(ev), flush=True)
    T = pd.DataFrame(ev); keys = list(frames)
    C = control(T, frames, keys)
    out = dict(method=__doc__, groups={})
    for kind in sorted(T.kind.unique()):
        X = T[T.kind == kind]; g = dict(trades=stats(X), portfolio=portfolio(X), random_same_stop_target=stats(C[C.kind == kind]))
        out["groups"][kind] = g; print(kind, g, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/bansal_test.json", "w"), indent=1, default=float)
    T.to_csv("data/research/bansal_trades.csv.gz", index=False)


if __name__ == "__main__":
    main()
