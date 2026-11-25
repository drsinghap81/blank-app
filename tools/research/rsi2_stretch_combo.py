"""US bot rules + the 2.5-ATR stretch trigger as one portfolio (25 Nov 2026, Amritpal: "yes" to testing the moomoo RSI(2) bot's rule
together with the new trigger found in mean-reversion-world-markets-test: close more than 2.5 ATR below the 20-EMA, US large caps
+0.97%/trade, -11% max DD).
Universe and rules = the live bot (connors-rsi2-us-test.md): S&P 500 current members, 50-day avg volume > 2M shares, close > SMA200;
buy at the close; sell at the close when close > SMA5 or after 7 days; stop entry - 3 x ATR(14) (filled at the stop or a lower open);
10 slots x 10% of equity; 0.1% round trip. Yahoo adjusted daily, 2010-now.
Variants: bot now (RSI2 < 10) | stretch only | combined (either signal; stretch first, then lowest RSI) | combined 15 slots |
combined without the stop | combined, stretch also below 3 ATR. Newest-first years, 2022+, ex-2020, time in market, SPY / QQQ buy & hold."""
import io
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

req = urllib.request.Request("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers={"User-Agent": "Mozilla/5.0"})
tick = pd.read_html(io.StringIO(urllib.request.urlopen(req).read().decode()))[0].Symbol.str.replace(".", "-", regex=False).tolist()
D = yf.download(tick + ["SPY", "QQQ"], start="2009-01-01", auto_adjust=True, progress=False, threads=True)
stocks = [s for s in tick if s in D["Close"].columns]
O, H, L, C, V = (D[f][stocks] for f in ("Open", "High", "Low", "Close", "Volume"))


def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


R2 = rsi(C, 2); S200 = C.rolling(200).mean(); S5 = C.rolling(5).mean(); E20 = C.ewm(span=20, adjust=False).mean()
TR = np.maximum(H - L, np.maximum((H - C.shift()).abs(), (L - C.shift()).abs())); ATR = TR.rolling(14).mean()
LIQ = (V.rolling(50).mean() > 2e6) & (C > S200)
SIG_R = LIQ & (R2 < 10)
STR = (E20 - C) / ATR                      # how many ATRs below the 20-EMA
SIG_S = LIQ & (STR > 2.5)
SIG_S3 = LIQ & (STR > 3.0)
print("R| S&P 500 members with data:", len(stocks), flush=True)


def run(sigR, sigS, slots=10, stop=True, cost=0.001, tmax=7):
    o, h, l, c, s5, a, r2, st = (x.values for x in (O, H, L, C, S5, ATR, R2, STR))
    sr = sigR.values if sigR is not None else np.zeros(c.shape, bool); ss = sigS.values if sigS is not None else np.zeros(c.shape, bool)
    cash, pos, eq, tr_, expo, kinds = 1.0, {}, [], [], [], []
    for t in range(210, len(C)):
        for j in list(pos):
            p = pos[j]; px = None
            if np.isnan(c[t, j]):
                continue
            if stop and l[t, j] <= p["st"]:
                px = min(o[t, j], p["st"])
            elif c[t, j] > s5[t, j] or t - p["t"] >= tmax:
                px = c[t, j]
            if px is not None:
                cash += p["q"] * px * (1 - cost / 2); tr_.append(px / p["e"] - 1 - cost); kinds.append(p["k"]); del pos[j]
        inv = sum(p["q"] * c[t, j] for j, p in pos.items() if np.isfinite(c[t, j])); val = cash + inv
        eq.append(val); expo.append(inv / val if val > 0 else 0)
        cand = [(-st[t, j], 0, j, "S") for j in np.where(ss[t])[0] if j not in pos]          # stretch first, deepest first
        cand += [(r2[t, j], 1, j, "R") for j in np.where(sr[t] & ~ss[t])[0] if j not in pos]
        cand.sort(key=lambda x: (x[1], x[0]))
        for _, _, j, k in cand:
            if len(pos) >= slots:
                break
            amt = min(val / slots, cash)
            if amt < val / slots * 0.5:
                break
            pos[j] = dict(q=amt / c[t, j], e=c[t, j], st=c[t, j] - 3 * a[t, j], t=t, k=k); cash -= amt * (1 + cost / 2)
    e = pd.Series(eq, index=C.index[210:]); e = e[e.index >= "2010-01-01"]; e = e / e.iloc[0]; T = np.array(tr_); K = np.array(kinds)
    yrs = (e.index[-1] - e.index[0]).days / 365.25; y = e.resample("YE").last(); y = y.pct_change().fillna(y.iloc[0] - 1)
    e22 = e[e.index >= "2022-01-01"]; e22 = e22 / e22.iloc[0]; y22 = (e22.index[-1] - e22.index[0]).days / 365.25
    xc = np.prod([1 + v for d, v in y.items() if d.year != 2020]) ** (1 / (yrs - 1)) - 1
    ks = " ".join(f"{k}: {(K == k).sum()} trades avg {T[K == k].mean() * 100:+.2f}%" for k in ("R", "S") if (K == k).sum())
    return (f"CAGR {(e.iloc[-1] ** (1 / yrs) - 1) * 100:5.1f}% | maxDD {(e / e.cummax() - 1).min() * 100:6.1f}% | 2022+ {(e22.iloc[-1] ** (1 / y22) - 1) * 100:5.1f}%"
            f" | ex-2020 {xc * 100:5.1f}% | trades {len(T)} win {(T > 0).mean() * 100:.0f}% avg {T.mean() * 100:+.2f}% PF {T[T > 0].sum() / -T[T < 0].sum():.2f}"
            f" | in market {np.mean(expo) * 100:.0f}% | {ks}",
            " | ".join(f"{d.year}: {v * 100:+.1f}%" for d, v in sorted(y.items(), reverse=True)))


for name, a, b, kw in [("Bot now: RSI2<10", SIG_R, None, {}), ("Stretch only: >2.5 ATR below 20-EMA", None, SIG_S, {}),
                       ("COMBINED: RSI2<10 or stretch", SIG_R, SIG_S, {}), ("COMBINED, 15 slots", SIG_R, SIG_S, dict(slots=15)),
                       ("COMBINED, no 3-ATR stop", SIG_R, SIG_S, dict(stop=False)), ("COMBINED, stretch >3 ATR", SIG_R, SIG_S3, {}),
                       ("Stretch only, 5 slots x 20%", None, SIG_S, dict(slots=5))]:
    s, yy = run(a, b, **kw)
    print(f"R| {name:38s} {s}", flush=True)
    print(f"R| {name:38s} by year: {yy}", flush=True)
for bnch in ("SPY", "QQQ"):
    s = D["Close"][bnch]; s = s[s.index >= "2010-01-01"]; yrs = (s.index[-1] - s.index[0]).days / 365.25
    y = s.resample("YE").last().pct_change().dropna()
    print(f"R| {bnch} buy & hold: CAGR {((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100:.1f}% maxDD {(s / s.cummax() - 1).min() * 100:.1f}% | "
          + " | ".join(f"{d.year}: {v * 100:+.1f}%" for d, v in sorted(y.items(), reverse=True)[:6]), flush=True)
