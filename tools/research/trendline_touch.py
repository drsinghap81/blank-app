"""Trend line through the 2 latest swing lows: does the 3rd touch work as a buy, and the break as a sell? (17 Nov 2026)
Nifty 500 stocks (current members), 2016 - Nov 2026, liquid only (median 60-day value >= Rs 5 cr, price >= 50).

Swing low: lowest low with 5 days each side (known 5 days later). Line through the 2 latest swing lows, only when rising.
It is live from the day the 2nd low is confirmed until the next swing low is confirmed (then the line is redrawn).
Touch: the 5 previous closes were all > 1% above the line and today's low reaches line x 1.005 (same rule as the app alert).
The first touch on a line = the "3rd touch"; later ones = 4th+.
Outcome from the line price: 10/20-day return minus the equal-weight universe; "held" = no close > 3% under the line in
the next 10 days. Controls: touches of the 50-day average with the same rule, and every day in an uptrend.
Trades (buy at the line, or the open if it gaps below):
  T20  stop line - 1.5 ATR(14), exit after 20 days.
  RIDE stop line - 1.5 ATR, then exit on a close below the current rising line (redrawn as new swing lows form), max 120 days.
Portfolio Rs 20 L, 1% risk a trade, max 10% a stock, max 10 open, costs 0.3% round trip.
Break: first close below a rising line -> next 20 days vs the universe (a sell signal if negative).
Output: data/research/trendline_touch.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

K, COST = 5, 0.003


def scan(sym, df, mk):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    n = len(c); idx = df.index; ds = [str(x.date()) for x in idx]
    pc = np.r_[c[0], c[:-1]]; atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().values
    val = pd.Series(c * v).rolling(60).median().values
    sma50 = pd.Series(c).rolling(50).mean().values; sma200 = pd.Series(c).rolling(200).mean().values
    piv = [i for i in range(K, n - K) if l[i] == l[i - K:i + K + 1].min()]
    # active line on each day: from the pair (a, b) confirmed at b + K until the next pivot confirms
    act = np.full(n, -1); pairs = []
    for j in range(1, len(piv)):
        a, b = piv[j - 1], piv[j]; start = b + K; end = piv[j + 1] + K if j + 1 < len(piv) else n
        pairs.append((a, b)); act[start:min(end, n)] = len(pairs) - 1
    def L(p, i):
        a, b = pairs[p]; return l[b] + (l[b] - l[a]) / (b - a) * (i - b)
    def rising(p):
        a, b = pairs[p]; return l[b] > l[a]
    ev, br = [], []
    count = {}; last_t = -99; broke = set()
    def outcome(d, line, src, nth=0):
        if d + 20 >= n or not (val[d] >= 5e7 and c[d] >= 50) or not np.isfinite(atr[d]) or not np.isfinite(mk[d + 20]):
            return
        e = o[d] if o[d] < line else line                    # limit order at the line
        r10 = c[d + 10] / e - 1; r20 = c[d + 20] / e - 1
        m10 = mk[d + 10] / mk[d - 1] - 1; m20 = mk[d + 20] / mk[d - 1] - 1
        held = bool((c[d:d + 11] >= line * 0.97).all())
        stop = line - 1.5 * atr[d - 1]; up = bool(np.isfinite(sma200[d]) and c[d - 1] > sma200[d])
        # T20
        x20, d20 = c[d + 20], d + 20
        for k in range(d, d + 21):
            if l[k] <= stop:
                x20, d20 = (min(stop, o[k]) if k > d else stop), k; break
        # RIDE
        xr, dr = None, None
        for k in range(d, min(d + 121, n)):
            if l[k] <= stop:
                xr, dr = (min(stop, o[k]) if k > d else stop), k; break
            p = act[k]
            if k > d and p >= 0 and rising(p) and c[k] < L(p, k) and k + 1 < n:
                xr, dr = o[k + 1], k + 1; break
        if xr is None:
            dr = min(d + 120, n - 1); xr = c[dr]
        ev.append(dict(sym=sym, d=ds[d], src=src, nth=nth, up=up, ex10=r10 - m10, ex20=r20 - m20, r20=r20, held=held, entry=e, stop=stop,
                       x20=x20, d20=ds[d20], xr=xr, dr=ds[dr]))
    for d in range(6, n):
        p = act[d]
        if p >= 0 and rising(p):
            line = L(p, d); prev = np.array([L(p, k) for k in range(d - 5, d)])
            if (act[d - 5:d] == p).all() and (c[d - 5:d] > prev * 1.01).all() and l[d] <= line * 1.005 and d - last_t >= 5:
                count[p] = count.get(p, 0) + 1; last_t = d
                outcome(d, line, "line", count[p] + 2)
            if c[d] < line and p not in broke and (act[d - 1] == p) and c[d - 1] >= L(p, d - 1):
                broke.add(p)
                if d + 20 < n and val[d] >= 5e7 and c[d] >= 50 and np.isfinite(mk[d + 20]):
                    br.append(dict(sym=sym, d=ds[d], ex20=c[d + 20] / c[d] - 1 - (mk[d + 20] / mk[d] - 1), r20=c[d + 20] / c[d] - 1))
        if np.isfinite(sma50[d]) and np.isfinite(sma50[d - 5]):
            if (c[d - 5:d] > sma50[d - 5:d] * 1.01).all() and l[d] <= sma50[d] * 1.005:
                outcome(d, sma50[d], "sma50")
    return ev, br


def summ(E):
    if not len(E):
        return {}
    return dict(n=len(E), held=round(E.held.mean() * 100, 1), ex10=round(E.ex10.mean() * 100, 2), ex20=round(E.ex20.mean() * 100, 2),
                t20=round(E.ex20.mean() / (E.ex20.std() / math.sqrt(len(E))), 2), win20=round((E.r20 > 0).mean() * 100, 1))


def portfolio(T, xcol, dcol, cap=2e6):
    T = T.sort_values("d"); eq = cap; open_ = []; curve = []; rs = []
    for _, x in T.iterrows():
        open_ = [e for e in open_ if e > x.d]
        if len(open_) >= 10 or x.entry <= x.stop:
            continue
        q = min(0.01 * eq / (x.entry - x.stop), 0.10 * eq / x.entry)
        pnl = q * (x[xcol] - x.entry) - COST * q * x.entry; eq += pnl; open_.append(x[dcol]); curve.append((x[dcol], eq))
        rs.append(x[xcol] / x.entry - 1 - COST)
    if not curve:
        return {}
    s = pd.Series([e for _, e in curve], index=pd.to_datetime([d for d, _ in curve])).sort_index()
    yrs = (s.index[-1] - pd.Timestamp("2016-01-01")).days / 365.25; rs = np.array(rs)
    yr = s.groupby(s.index.year).last(); yr = yr / yr.shift(1, fill_value=cap) - 1
    return dict(cagr=round(((s.iloc[-1] / cap) ** (1 / yrs) - 1) * 100, 1), max_dd=round((s / s.cummax() - 1).min() * 100, 1), trades=len(curve),
                win=round((rs > 0).mean() * 100, 1), avg=round(rs.mean() * 100, 2), pos_years=f"{int((yr > 0).sum())}/{len(yr)}")


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
    ev, br = [], []
    for s, f in frames.items():
        a, b = scan(s, f, mkt.reindex(f.index).values); ev += a; br += b
    E = pd.DataFrame(ev); E = E[E.d >= "2016-01-01"].dropna(subset=["ex10", "ex20"]); B = pd.DataFrame(br); B = B[B.d >= "2016-01-01"]
    nifty = yf.download("^NSEI", start="2016-01-01", auto_adjust=False, progress=False)
    if hasattr(nifty.columns, "levels"):
        nifty.columns = nifty.columns.get_level_values(0)
    nc = nifty.Close.dropna(); yrs = (nc.index[-1] - nc.index[0]).days / 365.25
    out = dict(method=__doc__, nifty=dict(cagr=round(((nc.iloc[-1] / nc.iloc[0]) ** (1 / yrs) - 1) * 100, 1), max_dd=round((nc / nc.cummax() - 1).min() * 100, 1)), groups={})
    G = {"3rd touch": E[(E.src == "line") & (E.nth == 3)], "3rd touch, uptrend (above 200-day)": E[(E.src == "line") & (E.nth == 3) & E.up],
         "4th+ touch": E[(E.src == "line") & (E.nth >= 4)], "50-day avg touch (control)": E[E.src == "sma50"],
         "50-day avg touch, uptrend (control)": E[(E.src == "sma50") & E.up]}
    for k, X in G.items():
        g = summ(X); g["T20"] = portfolio(X, "x20", "d20"); g["RIDE"] = portfolio(X, "xr", "dr"); out["groups"][k] = g
        print(k, g, flush=True)
    out["break"] = dict(n=len(B), ex20=round(B.ex20.mean() * 100, 2), t=round(B.ex20.mean() / (B.ex20.std() / math.sqrt(len(B))), 2),
                        win20=round((B.r20 > 0).mean() * 100, 1))
    print("break", out["break"], "nifty", out["nifty"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/trendline_touch.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
