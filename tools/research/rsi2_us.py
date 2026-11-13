"""Connors RSI(2) trend pullback, rules as given by the user (14 Nov 2026). US, 2010-now, Yahoo adjusted daily.
Stocks: S&P 500 current members (survivorship bias flatters), 50-day avg volume > 2M shares; ETFs: SPY, QQQ, IWM.
Entry at the close when close > SMA200 and RSI(2) < 10 (or < 5). Exit at the close when close > SMA5; hard stop entry - 3*ATR(14)
(intraday touch, filled at the stop or the open if it gaps below); time exit after 7 days. Stocks: 10 slots x 10% of equity,
lowest RSI first. ETFs: 3 slots x 33%. Costs 0.1% round trip (0.05% ETFs). Writes data/research/rsi2_us.json."""
import io, json, os, urllib.request
import numpy as np, pandas as pd, yfinance as yf
req = urllib.request.Request('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'})
tick = pd.read_html(io.StringIO(urllib.request.urlopen(req).read().decode()))[0].Symbol.str.replace('.', '-', regex=False).tolist()
ETF = ['SPY', 'QQQ', 'IWM']
D = yf.download(tick + ETF, start='2009-01-01', auto_adjust=True, progress=False, threads=True)
def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)
def run(cols, slots, thr, cost, liq=True, stop=True, tmax=7):
    O, H, L, C, V = (D[f][cols] for f in ('Open', 'High', 'Low', 'Close', 'Volume'))
    R2 = rsi(C, 2); S200 = C.rolling(200).mean(); S5 = C.rolling(5).mean()
    tr = pd.concat([H - L, (H - C.shift()).abs(), (L - C.shift()).abs()]).groupby(level=0).max().reindex(C.index)[cols]
    ATR = tr.rolling(14).mean()
    sig = (C > S200) & (R2 < thr) & ((V.rolling(50).mean() > 2e6) if liq else True)
    o, h, l, c, s5, a, r2, sg = (x.values for x in (O, H, L, C, S5, ATR, R2, sig))
    cash, pos, eq, tr_ = 1.0, {}, [], []
    for t in range(210, len(C)):
        for j in list(pos):
            p = pos[j]; px = None
            if np.isnan(c[t, j]): continue
            if stop and l[t, j] <= p['st']: px = min(o[t, j], p['st'])
            elif c[t, j] > s5[t, j] or t - p['t'] >= tmax: px = c[t, j]
            if px is not None:
                cash += p['q'] * px * (1 - cost / 2); tr_.append(px / p['e'] - 1 - cost); del pos[j]
        val = cash + sum(p['q'] * c[t, j] for j, p in pos.items() if np.isfinite(c[t, j]))
        eq.append(val)
        cand = sorted((r2[t, j], j) for j in np.where(sg[t])[0] if j not in pos)
        for _, j in cand:
            if len(pos) >= slots: break
            amt = min(val / slots, cash)
            if amt < val / slots * 0.5: break
            pos[j] = dict(q=amt / c[t, j], e=c[t, j], st=c[t, j] - 3 * a[t, j], t=t); cash -= amt * (1 + cost / 2)
    e = pd.Series(eq, index=C.index[210:]); e = e[e.index >= '2010-01-01']; e = e / e.iloc[0]; T = np.array(tr_)
    yrs = (e.index[-1] - e.index[0]).days / 365.25; y = e.resample('YE').last(); y = y.pct_change().fillna(y.iloc[0] - 1)
    e22 = e[e.index >= '2022-01-01']; e22 = e22 / e22.iloc[0]; y22 = (e22.index[-1] - e22.index[0]).days / 365.25
    return dict(cagr=round((e.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round((e / e.cummax() - 1).min() * 100, 1),
                cagr22=round((e22.iloc[-1] ** (1 / y22) - 1) * 100, 1), trades=len(T), win=round((T > 0).mean() * 100, 1),
                avg=round(T.mean() * 100, 2), pf=round(T[T > 0].sum() / -T[T < 0].sum(), 2), years={int(d.year): round(v * 100, 1) for d, v in y.items()})
stocks = [s for s in tick if s in D['Close'].columns]
out = {}
for name, cols, slots, thr, cost, liq, stop in [
        ('S&P 500 stocks, RSI2<10', stocks, 10, 10, 0.001, True, True), ('S&P 500 stocks, RSI2<5', stocks, 10, 5, 0.001, True, True),
        ('S&P 500 stocks, RSI2<10, no stop', stocks, 10, 10, 0.001, True, False),
        ('ETFs SPY/QQQ/IWM, RSI2<10', ETF, 3, 10, 0.0005, False, True), ('ETFs SPY/QQQ/IWM, RSI2<5', ETF, 3, 5, 0.0005, False, True)]:
    out[name] = run(cols, slots, thr, cost, liq, stop); print(name, out[name], flush=True)
for b in ETF:
    s = D['Close'][b]; s = s[s.index >= '2010-01-01']; yrs = (s.index[-1] - s.index[0]).days / 365.25
    out[f'{b} buy & hold'] = dict(cagr=round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), maxdd=round((s / s.cummax() - 1).min() * 100, 1)); print(b, out[f'{b} buy & hold'])
os.makedirs('data/research', exist_ok=True)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC'), results=out), open('data/research/rsi2_us.json', 'w'), indent=1)
