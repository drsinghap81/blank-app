"""Research (12 Nov 2026): do commodity / bond ETFs improve the Trading 212 AU pies? Monthly, 2008-01 to the last full month,
auto-adjusted ETF prices (dividends in), 0.15% per unit of turnover (T212 AU FX), cash = BIL. Writes data/research/pie_commod.json."""
import json, os
import numpy as np, pandas as pd
import yfinance as yf

T = ["SPY", "QQQ", "MDY", "IWM", "GLD", "SLV", "DBC", "USO", "TLT", "IEF", "BIL", "AUDUSD=X"]
COST = 0.0015
px = yf.download(T, start="2006-01-01", auto_adjust=True, progress=False)["Close"]
M = px.resample("ME").last(); M = M[M.index <= pd.Timestamp.today().normalize() - pd.offsets.MonthEnd(0)]
M = M.loc["2007-01-31":]
R = M.pct_change()
EQ = ["SPY", "QQQ", "MDY", "IWM"]


def run(weights_fn, start="2008-01-31"):
    idx = M.loc[start:].index; prev = {}; out = []
    for i in range(len(idx) - 1):
        d, n = idx[i], idx[i + 1]
        w = weights_fn(d)
        turn = sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev))
        r = sum(v * (R.loc[n, k] if pd.notna(R.loc[n, k]) else 0) for k, v in w.items()) - turn * COST
        out.append((n, r))
        # drift within the month for fixed mixes is handled by re-weighting each month (monthly rebalance)
        prev = {k: v * (1 + (R.loc[n, k] if pd.notna(R.loc[n, k]) else 0)) for k, v in w.items()}
        s = sum(prev.values()) or 1; prev = {k: v / s for k, v in prev.items()}
    return pd.Series(dict(out))


def stats(s):
    eq = (1 + s).cumprod(); yrs = len(s) / 12
    dd = (eq / eq.cummax() - 1).min()
    a = s.loc[:"2016-12-31"]; b = s.loc["2017-01-01":]
    cg = lambda x: ((1 + x).prod() ** (12 / len(x)) - 1) * 100 if len(x) else None  # noqa: E731
    yr = (1 + s).groupby(s.index.year).prod() - 1
    return dict(cagr=round(cg(s), 1), maxdd=round(dd * 100, 1), p1=round(cg(a), 1), p2=round(cg(b), 1), worst_year=round(yr.min() * 100, 1),
                y2022=round(yr.get(2022, np.nan) * 100, 1), y2008=round(yr.get(2008, np.nan) * 100, 1))


m3 = M.pct_change(3); m6 = M.pct_change(6); sma10 = M.rolling(10).mean()


def rot(univ, n=1, filt=False, look=m3):
    def f(d):
        s = look.loc[d, univ].dropna()
        if filt:
            s = s[[M.loc[d, k] > sma10.loc[d, k] for k in s.index]]
        s = s[s > look.loc[d, "BIL"] if pd.notna(look.loc[d, "BIL"]) else s > 0].sort_values(ascending=False)
        pick = list(s.index[:n])
        w = {k: 1 / n for k in pick}
        if len(pick) < n:
            w["BIL"] = w.get("BIL", 0) + (n - len(pick)) / n
        return w
    return f


def fixed(w):
    return lambda d: dict(w)


tests = {
    "S&P 500 buy & hold": fixed({"SPY": 1}),
    "Rotation (now): best 1 of S&P/Nasdaq/Mid/Small, 3-m": rot(EQ),
    "Rotation + gold: best 1 of 5": rot(EQ + ["GLD"]),
    "Rotation + gold + bonds: best 1 of 6 (adds TLT)": rot(EQ + ["GLD", "TLT"]),
    "Rotation + gold + commodities + bonds: best 1 of 8": rot(EQ + ["GLD", "SLV", "DBC", "TLT"]),
    "Best 2 of S&P/Nasdaq/gold/bonds": rot(["SPY", "QQQ", "GLD", "TLT"], 2),
    "Best 2 of S&P/Nasdaq/gold/bonds, 6-m": rot(["SPY", "QQQ", "GLD", "TLT"], 2, look=m6),
    "Best 3 of 8 with 10-m trend filter": rot(EQ + ["GLD", "SLV", "DBC", "TLT"], 3, filt=True),
    "Fixed 75 S&P / 25 gold": fixed({"SPY": .75, "GLD": .25}),
    "Fixed 60 S&P / 20 gold / 20 bonds": fixed({"SPY": .6, "GLD": .2, "TLT": .2}),
    "Fixed 25 S&P / 25 Nasdaq / 25 gold / 25 bonds": fixed({"SPY": .25, "QQQ": .25, "GLD": .25, "TLT": .25}),
    "Fixed 40 Nasdaq / 30 S&P / 30 gold": fixed({"QQQ": .4, "SPY": .3, "GLD": .3}),
    "Fixed 70 S&P / 15 gold / 15 commodities": fixed({"SPY": .7, "GLD": .15, "DBC": .15}),
}
res = []
for k, f in tests.items():
    s = run(f); res.append(dict(name=k, **stats(s)))
cur = rot(EQ + ["GLD", "SLV", "DBC", "TLT"])(M.index[-1])
out = dict(generated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"), months=len(M.loc["2008-01-31":]) - 1, last=str(M.index[-1].date()),
           note="US$ returns, monthly rebalance, 0.15% per unit traded, ETF prices with dividends. p1 = 2008-16, p2 = 2017-26.",
           results=res, now_best1_of8=cur, m3_now={k: round(float(m3.iloc[-1][k]) * 100, 1) for k in EQ + ["GLD", "SLV", "DBC", "TLT", "BIL"] if pd.notna(m3.iloc[-1][k])})
os.makedirs("data/research", exist_ok=True)
json.dump(out, open("data/research/pie_commod.json", "w"), indent=1)
for r in res: print(r)
