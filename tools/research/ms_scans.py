"""Market Strength (getmarketstrength.com) scans and backtested strategies, rebuilt from their published rules and tested on our
NSE data (28 Nov 2026, Amritpal: "check this website thoroughly, adopt good features and scans but with backtest").
Their published rules (methodology page, scan guides, backtests page) are coded here independently; no data of theirs is used.
Universe: our NSE list (Yahoo 2015-26, today's names = survivors, as theirs), liquid = 20-day traded value >= Rs 10 cr, price >= 100.
RS rating 1-99: rank of 0.4 x 3m + 0.2 x 6m + 0.2 x 9m + 0.2 x 12m return across liquid stocks each day (their formula).
Fills: signal on day t's close, buy at the NEXT close (as their backtests); exits also at the next close, stops intraday.
Market gate: new trades only while Nifty 50 closes above its 50-day average (their backtests).
Portfolio: 10 slots, 10% of equity each, highest RS first, 0.5% round-trip cost (their default).
STRATEGIES (their 4 backtests) and SCANS (their 8 + 4 guide screens), each with its own exit:
  ema21  : close below the 21-day EMA after 3 days -> next close, or an 8% stop
  chand  : close below (highest close since entry - 3 x ATR14) -> next close, or 40 sessions
  ema10  : close below the 10-day EMA -> next close, stop under the box low
Newest windows first; '2020+' = their test window. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

COST = 0.005


def ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().to_numpy()


def sma(a, n):
    return pd.Series(a).rolling(n).mean().to_numpy()


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def rolling_max(a, n):
    return pd.Series(a).rolling(n, min_periods=n).max().to_numpy()


def exit_walk(o, h, l, c, A, e10, e21, j, kind, stop=None):
    """entry at close of day j; returns (exit index, exit price)."""
    n = len(c); e = c[j]
    if kind == "ema21":
        st = e * 0.92 if stop is None else stop
        for k in range(j + 1, n):
            if l[k] <= st:
                return k, min(o[k], st)
            if k - j >= 3 and c[k] < e21[k] and k + 1 < n:
                return k + 1, c[k + 1]
        return n - 1, c[-1]
    if kind == "ema10":
        for k in range(j + 1, n):
            if stop is not None and l[k] <= stop:
                return k, min(o[k], stop)
            if c[k] < e10[k] and k + 1 < n:
                return k + 1, c[k + 1]
        return n - 1, c[-1]
    hc = e                                                   # chandelier 3 x ATR or 40 sessions
    for k in range(j + 1, n):
        if stop is not None and l[k] <= stop:
            return k, min(o[k], stop)
        hc = max(hc, c[k])
        if c[k] < hc - 3 * A[k] and k + 1 < n:
            return k + 1, c[k + 1]
        if k - j >= 40:
            return k, c[k]
    return n - 1, c[-1]


def signals(sym, x, rs, nif, n50ok):
    """all strategy / scan signals for one stock: list of (name, signal index, exit kind, stop)."""
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); n = len(c)
    R = rs.reindex(x.index).to_numpy(); NI = nif.reindex(x.index).ffill().to_numpy(); G = n50ok.reindex(x.index).fillna(False).to_numpy()
    s50, s150, s200 = sma(c, 50), sma(c, 150), sma(c, 200); e10, e21, e50 = ema(c, 10), ema(c, 21), ema(c, 50)
    v50 = sma(v, 50); A = atr(h, l, c); val = sma(c * v, 20) / 1e7
    hc252 = rolling_max(c, 252); lo252 = -rolling_max(-c, 252); hh252 = rolling_max(h, 252)
    rsl = c / NI; rslmax = rolling_max(rsl, 252)
    # trend template (their 8 checks)
    tt = (((c > s150) & (c > s200)).astype(int) + (s150 > s200) + (s200 > np.r_[np.full(21, np.nan), s200[:-21]])
          + ((s50 > s150) & (s50 > s200)) + (c > s50) + (c >= lo252 * 1.3) + (c >= hc252 * 0.75) + (R >= 70))
    tt7 = tt - (R >= 70)
    # Weinstein stage 2 (150-day average rising > 1% over 20 sessions; price above it or < 5% below)
    s150_20 = np.r_[np.full(20, np.nan), s150[:-20]]
    st2raw = (s150 > s150_20 * 1.01) & (c >= s150 * 0.95)
    out = []
    ok = lambda t: val[t] >= 10 and c[t] >= 100 and np.isfinite(R[t]) and G[t]  # noqa: E731
    run2 = 0
    # Darvas state machine
    top_i = None; top = bot = None; bot_i = None; state = 0
    for t in range(260, n - 1):
        up50_200 = c[t] > s50[t] and c[t] > s200[t] and s50[t] > s50[t - 5] and s200[t] > s200[t - 5]
        # -------- Darvas box (top: high within 5% of the 52-week high not exceeded for 3 sessions; bottom: low that holds 3)
        if state == 0 and h[t - 3] >= hh252[t - 3] * 0.95 and h[t - 3] >= h[t - 2:t + 1].max() and (t - 4 < 0 or h[t - 3] >= h[t - 4]):
            state, top, top_i, bot, bot_i = 1, h[t - 3], t - 3, None, None
        elif state >= 1:
            if h[t] > top and state == 1:
                state = 0
            elif state == 1:
                lo_i = top_i + 1 + int(np.argmin(l[top_i + 1:t + 1]))
                if t - lo_i >= 3 and l[lo_i + 1:t + 1].min() >= l[lo_i]:
                    state, bot, bot_i = 2, l[lo_i], lo_i
            elif state == 2:
                if c[t] < bot:
                    state = 0
                elif c[t] > top:
                    if (top / bot - 1) <= 0.15 and ok(t) and R[t] >= 70:
                        out.append(("Darvas box breakout", t, "chand", bot))
                    state = 0
        if not ok(t):
            run2 = run2 + 1 if st2raw[t] else 0
            continue
        r = R[t]; dch = c[t] / c[t - 1] - 1
        # -------- their 4 backtested strategies
        if r >= 70 and up50_200 and c[t] >= hc252[t] * 0.85 and (l[t - 3:t] <= e21[t - 3:t] * 1.01).any() \
                and c[t] > e21[t] and c[t] > h[t - 1] and c[t] > c[t - 1]:
            out.append(("S1 RS leader pullback to 21 EMA", t, "ema21", None))
        hN = h[t - 20:t].max(); lN = l[t - 20:t].min()
        if r >= 70 and up50_200 and c[t] >= hc252[t] * 0.85 and hN / lN - 1 <= 0.15 and c[t] > hN and v[t] >= 1.5 * v50[t] and dch <= 0.12:
            out.append(("S2 Tight-base breakout on volume", t, "chand", None))
        if rsl[t] >= rslmax[t - 1] and rsl[t - 1] < rslmax[t - 1] and c[t] < hc252[t - 1] and c[t] >= hc252[t - 1] * 0.90 and c[t] > s50[t] and c[t] > s200[t]:
            out.append(("S3 RS-line new high before breakout", t, "ema21", None))
        if r >= 70 and c[t] > hc252[t - 1] and c[t - 1] <= hc252[t - 1] and v[t] >= 1.5 * v50[t] and dch <= 0.10:
            out.append(("S4 52-week high momentum", t, "chand", None))
        # -------- scans
        if r >= 70 and c[t] > c[t - 1] and c[t] > s50[t] and c[t] >= hh252[t] * 0.85:
            dv = [v[k] for k in range(t - 10, t) if c[k] < c[k - 1]]
            if dv and v[t] > max(dv):
                out.append(("Pocket pivot", t, "chand", None))
        if r >= 70 and rsl[t] >= rslmax[t - 1] and rsl[t - 1] < rslmax[t - 1]:
            out.append(("RS line new high", t, "chand", None))
        if r >= 80 and tt[t] == 8 and tt[t - 1] < 8:
            out.append(("Trend template 8/8 leader", t, "chand", None))
        run2 = run2 + 1 if st2raw[t] else 0
        if r >= 50 and run2 == 5:
            out.append(("Just entered Stage 2", t, "chand", None))
        if r >= 70 and c[t] > s200[t] and tt[t] >= 5 and abs(c[t] / s50[t] - 1) <= 0.03 and c[t] > h[t - 1] and c[t] > s50[t]:
            out.append(("Pullback to 50 DMA (bounce)", t, "chand", None))
        # multi-year: close above the ~3-year high that held >= 1 year
        if t >= 760 and c[t] > hh252[t - 1]:
            w = h[t - 756:t]; p = int(np.argmax(w))
            if c[t] > w[p] and c[t - 1] <= w[p] and (756 - p) >= 252:
                out.append(("Multi-year breakout", t, "chand", None))
        # flag: pole >= 25% into a high 4-20 sessions ago, pullback <= 12%, breakout above the pole high
        if r >= 60:
            p = t - 20 + int(np.argmax(h[t - 20:t]))
            if 4 <= t - p <= 20 and p >= 31:
                H = h[p]; pole = H / l[p - 30:p + 1].min() - 1
                if pole >= 0.25 and l[p:t].min() >= H * 0.88 and c[t] > H and c[t - 1] <= H:
                    out.append(("Flag breakout", t, "chand", l[p:t].min()))
        # episodic pivot: up >= 5% in a day on >= 3x the 50-day volume (any RS; RS >= 60 variant), buy next close
        if dch >= 0.05 and v[t] >= 3 * v50[t]:
            out.append(("Episodic pivot (5% day, 3x vol)", t, "chand", l[t]))
            if r >= 70:
                out.append(("Episodic pivot, RS >= 70", t, "chand", l[t]))
        # volume breakout: close above the prior 50-day high on >= 2x volume, within 15% of the 52-week high, RS >= 70
        if r >= 70 and c[t] > h[t - 50:t].max() and c[t - 1] <= h[t - 51:t - 1].max() and v[t] >= 2 * v50[t] and c[t] >= hh252[t] * 0.85:
            out.append(("Volume breakout (50-day high, 2x vol)", t, "chand", None))
        # tight weeks: 3+ weekly closes within 1.5% (here: closes 5, 10, 15 sessions apart), above the 50-day; buy on a close
        # above the tight area's high, RS >= 70
        if r >= 70 and t >= 20 and c[t] > s50[t]:
            wk = [c[t - 1], c[t - 6], c[t - 11]]
            if max(wk) / min(wk) - 1 <= 0.015 and c[t] > h[t - 15:t].max() and c[t - 1] <= h[t - 16:t - 1].max():
                out.append(("Tight weeks breakout", t, "chand", l[t - 15:t].min()))
        # 10 EMA box: 4-15 closes at/above the 10 EMA, range <= 10%, uptrend at box start, breakout close above the box high
        k = t - 1; m = 0
        while k > 0 and c[k] >= e10[k] and m < 15:
            m += 1; k -= 1
        if m >= 4:
            b0 = t - m; bh = h[b0:t].max(); bl = l[b0:t].min()
            if bh / bl - 1 <= 0.10 and e10[b0] > e21[b0] > e50[b0] and c[b0 - 1] >= c[b0 - 31:b0 - 1].min() * 1.10 and c[t] > bh and c[t - 1] <= bh:
                out.append(("10 EMA box breakout", t, "ema10", bl))
        # cup with handle (cup 12-40% deep, >= 35 sessions, right side within 10% of the left high; handle 3-25 sessions,
        # <= 12% deep, in the upper half; breakout close above the handle high), RS >= 60
        if r >= 60 and t >= 300:
            p = t - 25 + int(np.argmax(h[t - 25:t]))
            if t - p >= 3:
                H = h[p]; hl = l[p:t].min()
                if c[t] > H and c[t - 1] <= H and hl >= H * 0.88:
                    q = p - 260 + int(np.argmax(h[p - 260:p - 34]))
                    HL = h[q]; cl = l[q:p].min()
                    if 0.12 <= 1 - cl / HL <= 0.40 and H >= HL * 0.90 and hl >= cl + 0.5 * (HL - cl):
                        out.append(("Cup with handle", t, "chand", hl))
        # VCP: 7 trend-template price checks; swings since the 6-month high: 2-5 pullbacks, each no deeper than the one before,
        # first 8-40% and >= 1.5x the last, last <= 8%; rising lows; pivot (latest swing high) within 10% of the base high;
        # 10-day volume <= 50-day; breakout = close above the pivot. RS >= 70
        if r >= 70 and tt7[t - 1] == 7 and c[t] > h[t - 5:t].max():
            b = t - 126 + int(np.argmax(h[t - 126:t]))
            sw = []; k = b; hi = h[b]; hi_i = b
            for z in range(b + 1, t):
                if h[z] > hi:
                    hi, hi_i = h[z], z
                if 2 <= z < t - 2 and l[z] <= l[z - 2:z + 3].min() and z > hi_i:
                    sw.append((hi, l[z], z)); hi = h[z]; hi_i = z
            if 2 <= len(sw) <= 5:
                d = [1 - lo / hi for hi, lo, _ in sw]
                lows = [lo for _, lo, _ in sw]
                piv = h[sw[-1][2]:t].max()
                if 0.08 <= d[0] <= 0.40 and d[-1] <= 0.08 and d[0] >= 1.5 * d[-1] and all(d[i + 1] <= d[i] for i in range(len(d) - 1)) \
                        and all(lows[i + 1] > lows[i] for i in range(len(lows) - 1)) and piv >= h[b] * 0.90 \
                        and v[t - 10:t].mean() <= v50[t - 1] and c[t] > piv and c[t - 1] <= piv:
                    out.append(("VCP breakout", t, "chand", lows[-1]))
    return out, (o, h, l, c, A, e10, e21)


def portfolio(T, C, days, slots=10, cap0=1_000_000):
    T = T.sort_values(["entry", "rs"], ascending=[True, False]); byday = {d: g for d, g in T.groupby("entry")}
    cash, pos, eq = cap0, [], {}
    for d in days:
        for p in [p for p in pos if p["exit"] <= d and not p["open"]]:
            cash += p["q"] * p["e"] * (1 + p["ret"]); pos.remove(p)
        if d in byday:
            for r in byday[d].itertuples():
                if len(pos) >= slots or any(p["sym"] == r.sym for p in pos):
                    continue
                E = cash + sum(p["q"] * p["last"] for p in pos); amt = min(E / slots, cash)
                if amt < 0.02 * E:
                    continue
                cash -= amt; pos.append(dict(sym=r.sym, q=amt / r.e, e=r.e, ret=r.ret, exit=r.exit, open=r.open, last=r.e))
        for p in pos:
            px = C.get(p["sym"], {}).get(d)
            if px is not None and np.isfinite(px):
                p["last"] = px
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos)
    return pd.Series(eq)


def stats(eq):
    eq = eq.dropna(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.3)) * 100 - 100, (eq / eq.cummax() - 1).min() * 100


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); n50ok = nif > nif.rolling(50).mean()
    # RS rating panel
    W = {}; L = {}
    for s, x in P.items():
        c = x.CLOSE
        r3, r6, r9, r12 = (c / c.shift(k) - 1 for k in (63, 126, 189, 252))
        r9 = r9.fillna(r6); r12 = r12.fillna(r6)
        W[s] = 0.4 * r3 + 0.2 * r6 + 0.2 * r9 + 0.2 * r12; L[s] = (c * x.VOL).rolling(20).mean() >= 1e8
    W = pd.DataFrame(W); L = pd.DataFrame(L).reindex(W.index).fillna(False)
    RS = (W.where(L).rank(axis=1, pct=True) * 98 + 1).round()
    print(f"R| stocks {len(P)}, liquid (>= Rs 10 cr/day) today {int(L.iloc[-1].sum())}", flush=True)
    rows = []
    for s, x in P.items():
        sig, arr = signals(s, x, RS[s], nif, n50ok)
        o, h, l, c, A, e10, e21 = arr; D = x.index; n = len(c)
        for name, t, kind, stop in sig:
            j = t + 1
            if j >= n:
                continue
            k, px = exit_walk(o, h, l, c, A, e10, e21, j, kind, stop)
            rows.append(dict(name=name, sym=s, sig=D[t], entry=D[j], exit=D[k], e=c[j], ret=px / c[j] - 1 - COST, days=k - j,
                             open=(k == n - 1 and px == c[-1]), rs=RS[s].get(D[t], 0)))
    T = pd.DataFrame(rows)
    C = {s: x.CLOSE.to_dict() for s, x in P.items()}
    days = sorted(set().union(*[set(x.index) for x in P.values()])); days = [d for d in days if d >= pd.Timestamp("2016-07-01")]
    end = days[-1]
    wins = (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)), ("2021+ ex-Covid", pd.Timestamp("2021-01-01")),
            ("2020+ (their window)", pd.Timestamp("2020-01-01")), ("2016+", pd.Timestamp("2016-07-01")))
    for lab, st in wins:
        b = nif[nif.index >= st]; cg, md = stats(b); print(f"R| Nifty 50 {lab:22s} {cg:+6.1f}%/yr worst fall {md:6.1f}%", flush=True)
    for name in sorted(T.name.unique()):
        Z = T[T.name == name]; z = Z[Z.entry >= "2021-01-01"]
        pf = z.ret[z.ret > 0].sum() / max(1e-9, -z.ret[z.ret < 0].sum())
        print(f"R| ===== {name}: signals {len(Z)} ({len(Z) / 10:.0f}/yr) | 2021+ trades {len(z)} win {(z.ret > 0).mean() * 100:.0f}% "
              f"avg {z.ret.mean() * 100:+.2f}% PF {pf:.2f} hold {z.days.median():.0f}d", flush=True)
        for lab, st in wins:
            dd = [d for d in days if d >= st]; eq = portfolio(Z[Z.entry >= st], C, dd); cg, md = stats(eq)
            print(f"R|   {lab:22s} {cg:+6.1f}%/yr worst fall {md:6.1f}%", flush=True)
        eq = portfolio(Z, C, days); yr = eq.resample("YE").last().pct_change().dropna() * 100
        print("R|   years: " + " ".join(f"{d.year}:{v:+.0f}" for d, v in yr.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
