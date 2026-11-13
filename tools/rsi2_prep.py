"""US RSI(2) trend-pullback: nightly prep for the moomoo bot and the app (14 Nov 2026).
Rules (tested in project note connors-rsi2-us-test.md): S&P 500 stock, 50-day avg volume > 2M shares, close > SMA200 and
RSI(2) < 10 -> buy at the close; sell at the close when close > SMA5, or after 7 trading days; stop entry - 3 x ATR(14).

The bot decides ~10 minutes before the US close from a live price P, so this file stores, per stock, what is needed to
evaluate the rules for any P without the full history:
  SMA200 with today's P:  P > sum199 / 199        (sum of the last 199 closes)       -> 'above'
  SMA5   with today's P:  P > sum4 / 4            (sum of the last 4 closes)         -> 'exit_above'
  RSI(2) Wilder (EWM alpha 1/2) with today's P:  au' = (au + max(P-c,0))/2, ad' = (ad + max(c-P,0))/2,
          RSI < 10  <=>  P < c + ad - 9 au (if that is <= c), else P < c + ad/9 - au   -> 'buy_below'
Closes are split-adjusted only (not dividend-adjusted), so they match the live price. Writes data/scan/us/rsi2.json."""
import io
import json
import os
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

OUT = 'data/scan/us/rsi2.json'
req = urllib.request.Request('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'})
sp = pd.read_html(io.StringIO(urllib.request.urlopen(req, timeout=60).read().decode()))[0]
tick = sp.Symbol.str.replace('.', '-', regex=False).tolist(); names = dict(zip(tick, sp.Security)); sect = dict(zip(tick, sp['GICS Sector']))
D = yf.download(tick, period='2y', auto_adjust=False, progress=False, threads=True)
C, H, L, V = D['Close'], D['High'], D['Low'], D['Volume']
last = C.index[-1]
if C.loc[last].notna().mean() < 0.9:          # today's bar incomplete for many stocks -> use the previous day
    C, H, L, V = C.iloc[:-1], H.iloc[:-1], L.iloc[:-1], V.iloc[:-1]; last = C.index[-1]


def wilder2(c):
    d = c.diff(); up = d.clip(lower=0); dn = (-d).clip(lower=0)
    return up.ewm(alpha=0.5, adjust=False).mean(), dn.ewm(alpha=0.5, adjust=False).mean()


rows, prev_ok = [], 0
for s in tick:
    c = C[s].dropna()
    if len(c) < 210 or c.index[-1] != last:
        continue
    au, ad = wilder2(c)
    tr = pd.concat([H[s] - L[s], (H[s] - C[s].shift()).abs(), (L[s] - C[s].shift()).abs()], axis=1).max(axis=1).reindex(c.index)
    atr = float(tr.rolling(14).mean().iloc[-1]); vol50 = float(V[s].reindex(c.index).rolling(50).mean().iloc[-1])
    cl = float(c.iloc[-1]); a, b = float(au.iloc[-1]), float(ad.iloc[-1])
    rsi = 100.0 if b == 0 else 100 - 100 / (1 + a / b)
    sma200 = float(c.iloc[-200:].mean()); sma5 = float(c.iloc[-5:].mean())
    r = dict(sym=s, name=names.get(s, ''), sector=sect.get(s, ''), close=round(cl, 4), sum199=round(float(c.iloc[-199:].sum()), 4),
             sum4=round(float(c.iloc[-4:].sum()), 4), au=round(a, 6), ad=round(b, 6), atr14=round(atr, 4), vol50=round(vol50),
             rsi2=round(rsi, 1), sma200=round(sma200, 2), sma5=round(sma5, 2),
             above=round(float(c.iloc[-199:].sum()) / 199, 4), exit_above=round(float(c.iloc[-4:].sum()) / 4, 4),
             buy_below=round(cl + b - 9 * a if b - 9 * a <= 0 else cl + b / 9 - a, 4))   # price where RSI(2) = 10 (down day / up day)
    r['signal'] = bool(cl > sma200 and rsi < 10 and vol50 > 2e6)          # would have been bought at this close
    r['liquid'] = bool(vol50 > 2e6)
    rows.append(r)
sig = sorted([r for r in rows if r['signal']], key=lambda r: r['rsi2'])
# watch: liquid uptrend stocks a modest drop away from a signal (buy_below within 3% under the close)
watch = sorted([r for r in rows if r['liquid'] and not r['signal'] and r['close'] > r['sma200'] and r['buy_below'] > max(r['above'], r['close'] * 0.97)],
               key=lambda r: r['close'] / r['buy_below'])
out = dict(generated=pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC'), asof=str(last.date()), n=len(rows),
           rules='S&P 500, 50-day avg volume > 2M, close > SMA200, RSI(2) < 10; exit close > SMA5 or 7 days; stop entry - 3 ATR(14)',
           signals=[r['sym'] for r in sig], watch=[r['sym'] for r in watch[:25]], stocks={r['sym']: r for r in rows})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(out, open(OUT, 'w'), separators=(',', ':'))
print(out['asof'], len(rows), 'stocks;', len(sig), 'signals:', out['signals'][:15], '; watch', out['watch'][:10])
