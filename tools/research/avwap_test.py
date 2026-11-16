"""Anchored VWAP from major swing lows / highs as support / resistance (16 Nov 2026). Nifty 500 stocks, 2016 - Nov 2026.

Major swing low: lowest low within +-20 days AND the lowest low of the 120 days before it (confirmed 20 days later).
Major swing high: the mirror. AVWAP from the anchor day: cumulative (typical price x volume) / cumulative volume,
followed for up to 250 days after confirmation.
Support touch (low-anchored): the 5 previous closes were all > 1% above the AVWAP, and today's low reaches it.
Resistance touch (high-anchored): the 5 previous closes were all > 1% below, and today's high reaches it.
Outcome from the touch-day close: 10- and 20-day return minus the equal-weight universe return over the same days
(excess); support "held" = no close more than 3% under the line in the next 10 days; resistance "held" = no close more
than 3% above it. Controls with the same touch rule: AVWAP anchored at random days (same count) and the 50-day SMA.
Trade (support): buy the touch close, stop line - 1.5 ATR(14), exit after 20 days; portfolio Rs 20 L, 1% risk,
max 10% a stock, max 10 open, costs 0.3%. Liquid only (median 60-day value >= Rs 5 cr, price >= 50). Current members.
Output: data/research/avwap_test.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

K, LOOK, FOLLOW, COST = 20, 120, 250, 0.003
rng = np.random.default_rng(7)


def avwap(tp, v, a, end):
    pv = np.cumsum(tp[a:end] * v[a:end]); vv = np.cumsum(v[a:end])
    return np.where(vv > 0, pv / np.maximum(vv, 1), np.nan)


def touches(c, l, h, line, start, kind, end=None):
    """line: array aligned to index; returns touch indices (one per approach, 5-day cooldown)."""
    out = []; last = -99
    for d in range(start + 5, end or len(line)):
        if d - last < 5:
            continue
        L = line[d]
        if not np.isfinite(L):
            continue
        prev = c[d - 5:d]; pl = line[d - 5:d]
        if not np.isfinite(pl).all():
            continue
        if kind == "sup":
            if (prev > pl * 1.01).all() and l[d] <= L:
                out.append(d); last = d
        else:
            if (prev < pl * 0.99).all() and h[d] >= L:
                out.append(d); last = d
    return out


def scan(sym, df, mkt):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    n = len(c); tp = (h + l + c) / 3; idx = df.index
    pc = np.r_[c[0], c[:-1]]; atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().values
    val = pd.Series(c * v).rolling(60).median().values; sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    mk = mkt.reindex(idx).values
    ev = []

    def outcome(d, line, kind, src):
        if d + 20 >= n or not (val[d] >= 5e7 and c[d] >= 50) or not np.isfinite(atr[d]):
            return
        r10 = c[d + 10] / c[d] - 1; r20 = c[d + 20] / c[d] - 1
        m10 = mk[d + 10] / mk[d] - 1 if np.isfinite(mk[d]) and np.isfinite(mk[d + 10]) else np.nan
        m20 = mk[d + 20] / mk[d] - 1 if np.isfinite(mk[d]) and np.isfinite(mk[d + 20]) else np.nan
        seg = c[d + 1:d + 11]; L = line
        held = (seg >= L * 0.97).all() if kind == "sup" else (seg <= L * 1.03).all()
        stop = L - 1.5 * atr[d]; ex = c[d + 20]; why = "time"
        if kind == "sup":
            for k in range(d + 1, d + 21):
                if l[k] <= stop:
                    ex = min(stop, o[k]); why = "stop"; break
        ev.append(dict(sym=sym, d=str(idx[d].date()), kind=kind, src=src, ex10=r10 - m10, ex20=r20 - m20, r20=r20, held=bool(held),
                       up=bool(c[d] > sma200[d]) if np.isfinite(sma200[d]) else False, entry=c[d], stop=stop, exit=ex, exit_d=str(idx[min(d + 20, n - 1)].date()), why=why))

    for kind in ("sup", "res"):
        anchors = []
        for i in range(LOOK, n - K):
            win = l[i - K:i + K + 1] if kind == "sup" else h[i - K:i + K + 1]
            if kind == "sup" and l[i] == win.min() and l[i] <= l[i - LOOK:i].min():
                anchors.append(i)
            if kind == "res" and h[i] == win.max() and h[i] >= h[i - LOOK:i].max():
                anchors.append(i)
        rand = sorted(rng.integers(LOOK, max(LOOK + 1, n - K - 30), size=len(anchors)).tolist())
        for src, A in (("swing", anchors), ("random", rand)):
            for a in A:
                end = min(a + K + FOLLOW, n); line = np.full(n, np.nan); line[a:end] = avwap(tp, v, a, end)
                line[:a + K] = np.nan                      # usable only once the swing is confirmed
                for d in touches(c, l, h, line, a + K, kind, end):
                    outcome(d, line[d], kind, src)
        for d in touches(c, l, h, sma50, 60, kind):
            outcome(d, sma50[d], kind, "sma50")
    return ev


def summ(E):
    if not len(E):
        return {}
    return dict(n=len(E), held=round(E.held.mean() * 100, 1), ex10=round(E.ex10.mean() * 100, 2), ex20=round(E.ex20.mean() * 100, 2),
                t20=round(E.ex20.mean() / (E.ex20.std() / math.sqrt(len(E))), 2), win20=round((E.r20 > 0).mean() * 100, 1))


def portfolio(T, cap=2e6):
    T = T.sort_values("d"); eq = cap; open_ = []; curve = []
    for _, x in T.iterrows():
        open_ = [e for e in open_ if e > x.d]
        if len(open_) >= 10 or x.entry <= x.stop:
            continue
        q = min(0.01 * eq / (x.entry - x.stop), 0.10 * eq / x.entry)
        eq += q * (x.exit - x.entry) - COST * q * x.entry; open_.append(x.exit_d); curve.append((x.exit_d, eq))
    s = pd.Series([e for _, e in curve], index=pd.to_datetime([d for d, _ in curve])).sort_index()
    yrs = (s.index[-1] - pd.Timestamp("2016-01-01")).days / 365.25
    return dict(cagr=round(((s.iloc[-1] / cap) ** (1 / yrs) - 1) * 100, 1), max_dd=round((s / s.cummax() - 1).min() * 100, 1), trades=len(curve))


def main():
    syms = pd.read_csv("data/universe/nifty500.csv").Symbol.tolist()
    frames = {}
    for k in range(0, len(syms), 50):
        batch = [s + ".NS" for s in syms[k:k + 50]]
        D = yf.download(batch, start="2015-01-01", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = D[s].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) >= 400:
                frames[s[:-3]] = df
        print("downloaded", len(frames), flush=True)
    rets = pd.DataFrame({s: f.Close for s, f in frames.items()}).pct_change().clip(-0.3, 0.3)
    mkt = (1 + rets.mean(axis=1).fillna(0)).cumprod()
    ev = []
    for s, f in frames.items():
        ev += scan(s, f, mkt)
    E = pd.DataFrame(ev); E = E[E.d >= "2016-01-01"].dropna(subset=["ex10", "ex20"])
    out = dict(method=__doc__, groups={})
    for kind in ("sup", "res"):
        for src in ("swing", "random", "sma50"):
            for up in (None, True):
                X = E[(E.kind == kind) & (E.src == src)]
                if up is not None:
                    X = X[X.up == (kind == "sup")]
                key = f"{'support' if kind == 'sup' else 'resistance'} | {src}{' | ' + ('uptrend' if kind == 'sup' else 'downtrend') if up else ''}"
                g = summ(X)
                if kind == "sup" and len(X):
                    g["portfolio"] = portfolio(X)
                out["groups"][key] = g
                print(key, g, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/avwap_test.json", "w"), indent=1)


if __name__ == "__main__":
    main()
