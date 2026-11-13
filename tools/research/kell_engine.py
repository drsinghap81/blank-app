"""EMA crossback (Oliver Kell style) — rules as given by the user, 14 Nov 2026.
Setup on the crossback day: C/C[20] >= 1.15, EMA10 > EMA20 > SMA50, close < EMA10 but > EMA20, market close > its 50-day SMA.
Entry: first later day (within 10) with close > EMA10 and close > open, at that close; setup cancelled if a close < EMA20 comes first.
Stop: lowest low of last 5 days. Half sold at entry + 2R (intraday touch), rest exits on a close below EMA20 (or the stop).
Portfolio: 1% of equity at risk per trade, max 10% of equity per stock, max 10 positions, same-day signals ranked by 20-day gain."""
import numpy as np, pandas as pd

def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def run(O, H, L, C, liq_ok, mkt_ok, cost=0.003, cap0=1.0, risk=0.01, cap1=0.10, maxpos=10):
    E10, E20, S50 = ema(C, 10), ema(C, 20), C.rolling(50).mean()
    mom = (C / C.shift(20) >= 1.15) & (E10 > E20) & (E20 > S50)
    cross = mom & (C < E10) & (C > E20) & liq_ok & mkt_ok.reindex(C.index).fillna(False).values[:, None]
    o, h, l, c, e10, e20 = (x.values for x in (O, H, L, C, E10, E20)); r20 = (C / C.shift(20)).values
    lo5 = L.rolling(5).min().values; X = cross.values; T, N = c.shape
    armed = np.full(N, -1)          # day index of the latest crossback still waiting for a reclaim
    cash, pos, eq, trades = cap0, {}, np.full(T, np.nan), []
    for t in range(60, T):
        # exits / partials on existing positions
        for j in list(pos):
            p = pos[j]
            if np.isnan(c[t, j]): continue
            if not p['half'] and h[t, j] >= p['tgt']:
                q = p['q'] / 2; cash += q * p['tgt'] * (1 - cost / 2); p['q'] -= q; p['half'] = True; p['real'] += q * (p['tgt'] - p['e'])
            if l[t, j] <= p['st'] or c[t, j] < e20[t, j]:
                px = min(o[t, j], p['st']) if l[t, j] <= p['st'] else c[t, j]
                cash += p['q'] * px * (1 - cost / 2); R = (p['real'] + p['q'] * (px - p['e'])) / (p['q0'] * p['risk'])
                trades.append(dict(entry=C.index[p['t']], exit=C.index[t], sym=C.columns[j], R=R, ret=(p['real'] + p['q'] * (px - p['e'])) / (p['q0'] * p['e']), half=p['half']))
                del pos[j]
        val = cash + sum(p['q'] * c[t, j] for j, p in pos.items() if np.isfinite(c[t, j]))
        eq[t] = val
        # update armed setups
        for j in np.where(X[t])[0]: armed[j] = t
        cand = []
        for j in np.where(armed >= 0)[0]:
            if t == armed[j]: continue
            if t - armed[j] > 10 or not np.isfinite(c[t, j]) or c[t, j] < e20[t, j]: armed[j] = -1; continue
            if c[t, j] > e10[t, j] and c[t, j] > o[t, j]:
                armed[j] = -1
                if j not in pos: cand.append((-r20[t, j], j))
        for _, j in sorted(cand):
            if len(pos) >= maxpos: break
            e, st = c[t, j], lo5[t, j]; rk = e - st
            if not (rk > 0): continue
            amt = min(val * risk / rk * e, val * cap1, cash)
            if amt < val * 0.01: continue
            q = amt / e; cash -= amt * (1 + cost / 2)
            pos[j] = dict(q=q, q0=q, e=e, st=st, risk=rk, tgt=e + 2 * rk, half=False, real=0.0, t=t)
    return pd.Series(eq, index=C.index).dropna(), pd.DataFrame(trades)

def report(eq, tr, label, start=None):
    if start: eq = eq[eq.index >= start]
    eq = eq / eq.iloc[0]; yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    yr = eq.resample('YE').last(); yr = yr.pct_change().fillna(yr.iloc[0] - 1)
    out = dict(system=label, cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round(((eq / eq.cummax()) - 1).min() * 100, 1),
               trades=len(tr), win=round((tr.R > 0).mean() * 100, 1), avgR=round(tr.R.mean(), 2), half_hit=round(tr.half.mean() * 100, 1),
               years={int(d.year): round(v * 100, 1) for d, v in yr.items()})
    print(out); return out
