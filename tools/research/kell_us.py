"""Kell EMA crossback on S&P 500 stocks (current members -> survivorship bias flatters results), 2010-now, rules as given:
Close > $15, 20-day avg volume > 1.5M shares, SPY > 50-day SMA. Writes data/research/kell_us.json."""
import io, json, os, sys, urllib.request
import pandas as pd, yfinance as yf
sys.path.insert(0, os.path.dirname(__file__)); import kell_engine as K
req = urllib.request.Request('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'})
tick = pd.read_html(io.StringIO(urllib.request.urlopen(req).read().decode()))[0].Symbol.str.replace('.', '-', regex=False).tolist()
D = yf.download(tick + ['SPY'], start='2009-01-01', auto_adjust=True, progress=False, threads=True)
O, H, L, C, V = (D[f].drop(columns='SPY') for f in ('Open', 'High', 'Low', 'Close', 'Volume'))
spy = D['Close']['SPY']; mkt = spy > spy.rolling(50).mean()
liq = (C > 15) & (V.rolling(20).mean() > 1.5e6)
eq, tr = K.run(O, H, L, C, liq.values, mkt, cost=0.001)
spy_eq = spy[spy.index >= '2010-01-01']; yrs = (spy_eq.index[-1] - spy_eq.index[0]).days / 365.25
out = dict(generated=pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC'), stocks=int(C.shape[1]),
           all=K.report(eq, tr, 'Kell crossback S&P 500', '2010-01-01'),
           recent=K.report(eq, tr[tr.entry >= '2022-01-01'], 'Kell crossback S&P 500 (2022+)', '2022-01-01'),
           spy=dict(cagr=round(((spy_eq.iloc[-1] / spy_eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1), maxdd=round(((spy_eq / spy_eq.cummax()) - 1).min() * 100, 1)))
os.makedirs('data/research', exist_ok=True); json.dump(out, open('data/research/kell_us.json', 'w'), indent=1, default=str); print(out['spy'])
