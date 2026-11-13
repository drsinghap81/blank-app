"""RSI(2) + US momentum blend test (14 Nov 2026). Based on rsi2_us.py. Connors RSI(2) trend pullback, rules as given by the user (14 Nov 2026). US, 2010-now, Yahoo adjusted daily.
Stocks: S&P 500 current members (survivorship bias flatters), 50-day avg volume > 2M shares; ETFs: SPY, QQQ, IWM.
Entry at the close when close > SMA200 and RSI(2) < 10 (or < 5). Exit at the close when close > SMA5; hard stop entry - 3*ATR(14)
(intraday touch, filled at the stop or the open if it gaps below); time exit after 7 days. Stocks: 10 slots x 10% of equity,
lowest RSI first. ETFs: 3 slots x 33%. Costs 0.1% round trip (0.05% ETFs). Writes data/research/rsi2_combo.json."""
import io, json, os, urllib.request
import numpy as np, pandas as pd, yfinance as yf
req = urllib.request.Request('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'})
tick = pd.read_html(io.StringIO(urllib.request.urlopen(req).read().decode()))[0].Symbol.str.replace('.', '-', regex=False).tolist()
ETF = ['SPY', 'QQQ', 'IWM', 'MTUM']
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
    return e
    yrs = (e.index[-1] - e.index[0]).days / 365.25; y = e.resample('YE').last(); y = y.pct_change().fillna(y.iloc[0] - 1)
    e22 = e[e.index >= '2022-01-01']; e22 = e22 / e22.iloc[0]; y22 = (e22.index[-1] - e22.index[0]).days / 365.25
    return dict(cagr=round((e.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round((e / e.cummax() - 1).min() * 100, 1),
                cagr22=round((e22.iloc[-1] ** (1 / y22) - 1) * 100, 1), trades=len(T), win=round((T > 0).mean() * 100, 1),
                avg=round(T.mean() * 100, 2), pf=round(T[T > 0].sum() / -T[T < 0].sum(), 2), years={int(d.year): round(v * 100, 1) for d, v in y.items()})

stocks = [s for s in tick if s in D['Close'].columns]
rsi_eq = run(stocks, 10, 10, 0.001, True, True)
rsi_ns = run(stocks, 10, 10, 0.001, True, False)
Cl = D['Close']; M = Cl.resample('ME').last(); MR = M.pct_change()
# Momentum 20: 12-1 month momentum, top 20 equal weight, monthly, cash when SPY < 10-month SMA, 0.15% per unit traded
m121 = M.shift(1) / M.shift(12) - 1; spy_up = M['SPY'] > M['SPY'].rolling(10).mean()
w_prev = pd.Series(0.0, index=stocks); mom = []
for i in range(13, len(M) - 1):
    d = M.index[i]
    if spy_up.iloc[i]:
        sc = m121.loc[d, stocks].dropna().nlargest(20); w = pd.Series(0.0, index=stocks); w[sc.index] = 1 / len(sc)
    else: w = pd.Series(0.0, index=stocks)
    turn = (w - w_prev).abs().sum(); r = (w * MR.iloc[i + 1][stocks].fillna(0)).sum() - turn * 0.0015
    mom.append((M.index[i + 1], r)); w_prev = w
mom = pd.Series(dict(mom))
def mret(e): return e.resample('ME').last().pct_change()
S = pd.DataFrame({'RSI2': mret(rsi_eq), 'RSI2 no stop': mret(rsi_ns), 'Momentum20+filter': mom,
                  'MTUM': MR['MTUM'], 'SPY': MR['SPY'], 'QQQ': MR['QQQ']}).loc['2010-02-28':].dropna()
def st(r):
    eq = (1 + r).cumprod(); y = len(r) / 12; yr = (1 + r).groupby(r.index.year).prod() - 1
    return dict(cagr=round((eq.iloc[-1] ** (1 / y) - 1) * 100, 1), maxdd=round((eq / eq.cummax() - 1).min() * 100, 1),
                worst_year=round(yr.min() * 100, 1), c22=round(((1 + r.loc['2022':]).prod() ** (12 / len(r.loc['2022':])) - 1) * 100, 1))
out = {'corr': S.corr().round(2).to_dict()}
rows = {}
for k in S.columns: rows[k] = st(S[k])
for mname in ('MTUM', 'Momentum20+filter', 'SPY'):
    for w in (0.3, 0.5):
        rows[f'{int((1-w)*100)}% {mname} + {int(w*100)}% RSI2'] = st((1 - w) * S[mname] + w * S['RSI2'])
out['results'] = rows
for k, v in rows.items(): print(f'{k:38s}', v)
print(S.corr().round(2).to_string())
os.makedirs('data/research', exist_ok=True)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC'), **out), open('data/research/rsi2_combo.json', 'w'), indent=1)
