"""Weekly / daily cup closes in the US and Australia (28 Nov 2026, Amritpal: "have you checked weekly, monthly, daily cup closes and
trade above the breakout high in US and AUS" -> "Yes"). Same rules as the NSE test (claude/weekly-daily-cup-closes.md):
WEEKLY cup: rim = highest weekly high of the previous 104 weeks, >= 26 weeks old, lowest weekly close since <= 20% below the rim; room
  to the next older peak (weeks 105-260) >= the cup depth, or none (all-time high). Signal = the FIRST weekly close above the rim.
  Entry = buy-stop at that week's high + 0.15% on any day of the next week (gap more than 3% above = skipped; fills at the open if it
  gaps above). Stop = the signal week's low - 0.5 x weekly ATR(14) (more than 25% away = skipped). Exit = next open after a weekly
  close below the weekly 30-SMA (the stop applies throughout).                      [NSE: 15.6%/yr, -28%]
DAILY cup: rim = highest high of the previous 250 sessions, >= 20 sessions old, lowest close since <= 15% below; same room rule
  (sessions 251-750). Signal = first daily close above the rim. Buy-stop at that day's high + 0.15%, valid 5 sessions. Stop = day low
  - 1 x ATR(14), at most 12% away. Exit = Supertrend(10,3) turns red -> next open.  [NSE: 10.9%/yr, -35%]
Liquidity as the live scans: US >= $5 m/day and price >= $10; ASX >= A$1 m/day and price >= A$1. Costs 0.1% (US) / 0.2% (ASX).
Portfolio: 1% risk a trade, max 20% a stock, 10 open, longer cup first on the same day. Survivor lists (today's names) - flattered.
UNIV env = US or ASX; PILOT = 150 stocks. Newest windows first, ex-Covid, vs the index."""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
from global_universe import symbols  # noqa: E402
from trend_scan import supertrend  # noqa: E402

MKT = (os.environ.get("UNIV") or "US").upper()
MINV, MINP, COST, BENCH = {"US": (5e6, 10.0, 0.001, "^GSPC"), "ASX": (1e6, 1.0, 0.002, "^AXJO")}[MKT]
BUF = 0.0015


def load():
    tick = list(symbols(MKT).ticker)
    if os.environ.get("PILOT"):
        tick = sorted(tick)[:150]
    out = {}
    for i in range(0, len(tick), 150):
        ch = tick[i:i + 150]; d = None
        for _ in range(3):
            try:
                d = yf.download(ch, start="2009-01-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({"O": d["Open"][t], "H": d["High"][t], "L": d["Low"][t], "C": d["Close"][t], "V": d["Volume"][t]}).dropna()
            except Exception:  # noqa: BLE001
                continue
            x = x[(x.C > 0) & (x.O > 0) & (x.H >= x.L)]
            if len(x) < 600:
                continue
            x.index = pd.to_datetime(x.index).tz_localize(None); out[t] = x
        print("R| loaded", i + len(ch), len(out), flush=True)
    return out


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def cup(hh, cc, i, K, B, D, OLD):
    """cup at bar i (signal bar i excluded from the rim window): (rim, depth, age) or None"""
    if i < OLD:
        return None
    w = hh[i - K:i]; r = int(np.argmax(w)); rim = w[r]; age = K - r
    if age < B:
        return None
    low = cc[i - K + r:i].min(); dep = low / rim - 1
    if dep > -D:
        return None
    older = hh[max(0, i - OLD):i - K]
    if len(older) and older.max() > rim and older.max() / rim - 1 < -dep:
        return None                                                      # not enough room to the older peak
    return rim, -dep, age


def trades_daily(sym, x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in "OHLCV"); D = x.index; n = len(c)
    val = pd.Series(c * v).rolling(20).mean().to_numpy(); A = atr(h, l, c)
    sd, _ = supertrend(h, l, c); out = []; busy = -1
    for i in range(260, n - 2):
        if i <= busy or not (val[i] >= MINV and c[i] >= MINP):
            continue
        cp = cup(h, c, i, 250, 20, 0.15, 750)
        if not cp or c[i] <= cp[0] or c[i - 1] > cp[0]:
            continue
        trig = h[i] * (1 + BUF); stop = l[i] - A[i]
        if not np.isfinite(stop) or (trig - stop) / trig > 0.12:
            continue
        j = None
        for k in range(i + 1, min(n, i + 6)):
            if h[k] >= trig:
                if o[k] > trig * 1.03:
                    break
                j, e = k, max(o[k], trig); break
        if j is None:
            continue
        xk, px = n - 1, c[-1]
        for k in range(j, n - 1):
            if l[k] <= stop:
                xk, px = k, (min(o[k], stop) if k > j else stop); break
            if k > j and sd[k] < 0:
                xk, px = k + 1, o[k + 1]; break
        out.append(dict(sym=sym, side=1, sig=D[i], entry=D[j], exit=D[xk], e=e, risk=(e - stop) / e, ret=px / e - 1 - COST,
                        adx=cp[2], days=xk - j, open=xk == n - 1))
        busy = xk
    return out


def trades_weekly(sym, x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in "OHLCV"); D = x.index; n = len(c)
    W = x.resample("W-FRI").agg({"O": "first", "H": "max", "L": "min", "C": "last", "V": "sum"}).dropna()
    wh, wl, wc = W.H.to_numpy(float), W.L.to_numpy(float), W.C.to_numpy(float); m = len(wc)
    wA = atr(wh, wl, wc); s30 = pd.Series(wc).rolling(30).mean().to_numpy()
    val = pd.Series(c * v).rolling(20).mean()
    # daily index of each week's last day
    wend = np.searchsorted(D.values, W.index.values, side="right") - 1
    wk_of = np.searchsorted(W.index.values, D.values, side="left")              # week index each day belongs to
    out = []; busy_d = -1
    for i in range(110, m - 1):
        di = wend[i]
        if di <= busy_d or di < 0 or not (val.iloc[di] >= MINV and wc[i] >= MINP):
            continue
        cp = cup(wh, wc, i, 104, 26, 0.20, 260)
        if not cp or wc[i] <= cp[0] or wc[i - 1] > cp[0]:
            continue
        trig = wh[i] * (1 + BUF); stop = wl[i] - 0.5 * wA[i]
        if not np.isfinite(stop) or (trig - stop) / trig > 0.25:
            continue
        j = None; nxt_end = wend[i + 1]
        for k in range(di + 1, min(n, nxt_end + 1)):
            if h[k] >= trig:
                if o[k] > trig * 1.03:
                    break
                j, e = k, max(o[k], trig); break
        if j is None:
            continue
        xk, px = n - 1, c[-1]
        for k in range(j, n - 1):
            if l[k] <= stop:
                xk, px = k, (min(o[k], stop) if k > j else stop); break
            wi = wk_of[k]
            if wi < m and wend[wi] == k and k > j and np.isfinite(s30[wi]) and wc[wi] < s30[wi]:
                xk, px = k + 1, o[k + 1]; break
        out.append(dict(sym=sym, side=1, sig=W.index[i], entry=D[j], exit=D[xk], e=e, risk=(e - stop) / e, ret=px / e - 1 - COST,
                        adx=cp[2], days=xk - j, open=xk == n - 1))
        busy_d = xk
    return out


def portfolio(T, C, days, maxpos=10, risk=0.01, cap0=1_000_000):
    T = T.sort_values(["entry", "adx"], ascending=[True, False])
    byday = {d: g for d, g in T.groupby("entry")}
    cash, pos, eq = cap0, [], {}
    for d in days:
        for p in [p for p in pos if p["exit"] <= d]:
            cash += p["q"] * p["e"] * (1 + p["ret"]); pos.remove(p)
        if d in byday:
            for r in byday[d].itertuples():
                if len(pos) >= maxpos or any(p["sym"] == r.sym for p in pos):
                    continue
                E = cash + sum(p["q"] * p["last"] for p in pos)
                q = min(risk * E / (r.e * r.risk), 0.20 * E / r.e, cash / r.e)
                if q * r.e < 0.01 * E:
                    continue
                cash -= q * r.e; pos.append(dict(sym=r.sym, q=q, e=r.e, ret=r.ret, exit=r.exit, last=r.e))
        for p in pos:
            px = C.get(p["sym"], {}).get(d)
            if px is not None and np.isfinite(px):
                p["last"] = px
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos)
    return pd.Series(eq)


def stats(eq):
    eq = eq.dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.3)) * 100 - 100, (eq / eq.cummax() - 1).min() * 100


def main():
    P = load()
    b = yf.download(BENCH, start="2009-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    b.index = pd.to_datetime(b.index).tz_localize(None)
    C = {s: x.C.to_dict() for s, x in P.items()}
    days = sorted(set().union(*[set(x.index) for x in P.values()])); days = [d for d in days if d >= pd.Timestamp("2012-01-01")]
    print(f"R| {MKT}: {len(P)} stocks, {days[0].date()} -> {days[-1].date()}", flush=True)
    for nm, fn in (("WEEKLY cup close", trades_weekly), ("DAILY cup close", trades_daily)):
        T = pd.DataFrame([t for s, x in P.items() for t in fn(s, x)])
        if not len(T):
            print(f"R| {nm}: no trades", flush=True); continue
        T = T[T.entry >= pd.Timestamp("2012-01-01")]
        z = T[T.entry >= "2021-01-01"]
        print(f"R| {nm}: trades {len(T)} | 2021+ {len(z)}: win {(z.ret > 0).mean() * 100:.0f}% avg {z.ret.mean() * 100:+.2f}% "
              f"median {z.ret.median() * 100:+.2f}% hold {z.days.median():.0f}d risk {z.risk.median() * 100:.1f}%", flush=True)
        for lab, st in (("last 1y", days[-1] - pd.DateOffset(years=1)), ("last 3y", days[-1] - pd.DateOffset(years=3)),
                        ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2012+", pd.Timestamp("2012-01-01"))):
            dd = [d for d in days if d >= st]
            eq = portfolio(T[T.entry >= st], C, dd)
            cg, md = stats(eq); bb = b[b.index >= st]; bc, bm = stats(bb)
            print(f"R|   {nm[:6]} {lab:15s} portfolio {cg:+6.1f}%/yr worst fall {md:6.1f}% | index {bc:+6.1f}%/yr ({bm:.0f}%)", flush=True)
        eq = portfolio(T, C, days); yr = eq.resample("YE").last().pct_change().dropna() * 100
        print(f"R|   {nm[:6]} years: " + " ".join(f"{d.year}:{v:+.0f}" for d, v in yr.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
