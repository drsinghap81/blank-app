"""Research (16 Nov 2026): long-only Turtle portfolio on liquid futures-like markets (Yahoo daily, 2010-Nov 2026).
Entry: buy-stop above the 55-day high (System 2) or 20-day high (System 1); exit on the 20-day / 10-day low or the 2N stop.
N = 20-day Wilder ATR. Unit = risk% of equity / (2N) per price point (a 2N stop loses risk%). Variants: 1 unit only, or Turtle
pyramid (+1 unit every 1/2 N up to 4, stop for all units = last entry - 2N). Limits: 4 units per market, 12 units in total,
gross notional cap 400% of equity. Costs 0.05% a side (coins 0.15%). P&L in % of notional, so no currency translation
(research approximation). Continuous front-month futures on Yahoo are not roll-adjusted: roll gaps add noise (worst for crude,
gas and grains). Prints CAGR, max drawdown, by year, average gross exposure."""
import time
import numpy as np, pandas as pd, yfinance as yf

MK = {"GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper", "CL=F": "Crude oil", "NG=F": "Natural gas", "ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soybeans",
      "^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "^GDAXI": "DAX", "^N225": "Nikkei 225", "^FTSE": "FTSE 100",
      "EURUSD=X": "EUR/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD", "GBPUSD=X": "GBP/USD", "USDINR=X": "USD/INR", "BTC-USD": "Bitcoin", "ETH-USD": "Ether"}
D = {}
for t in MK:
    for _ in range(3):
        try:
            x = yf.download(t, start="2009-01-01", interval="1d", auto_adjust=False, progress=False); break
        except Exception as e:  # noqa: BLE001
            print("retry", t, e); time.sleep(5); x = None
    if x is None or x.empty: print("no data", t); continue
    if isinstance(x.columns, pd.MultiIndex): x.columns = x.columns.get_level_values(0)
    x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
    if t.endswith("=X"): x = x.assign(High=np.minimum(x.High, np.maximum(x.Open, x.Close) * 1.03), Low=np.maximum(x.Low, np.minimum(x.Open, x.Close) / 1.03))
    D[t] = x; time.sleep(0.3)
idx = sorted(set().union(*[set(x.index) for x in D.values()])); idx = pd.DatetimeIndex(idx)
F = {k: {c: D[k][c].reindex(idx) for c in ("Open", "High", "Low", "Close")} for k in D}
for k in D:
    h, l, c = D[k].High, D[k].Low, D[k].Close
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    F[k]["N"] = tr.ewm(alpha=1 / 20, adjust=False, min_periods=20).mean().shift(1).reindex(idx)
    for n in (20, 55): F[k][f"HH{n}"] = h.shift(1).rolling(n).max().reindex(idx)
    for n in (10, 20): F[k][f"LL{n}"] = l.shift(1).rolling(n).min().reindex(idx)
A = {k: {c: v.to_numpy() for c, v in F[k].items()} for k in F}
keys = list(A)

def sim(nin=55, nout=20, risk=0.01, pyramid=False, start="2010-01-01", ulim=4, tot=12, gross_cap=4.0):
    E = 1.0; pos = {}; eq = []; gross = []; i0 = idx.searchsorted(pd.Timestamp(start)); last = {k: np.nan for k in keys}
    for i in range(i0, len(idx)):
        pnl = 0.0
        for k in keys:
            a = A[k]; c = a["Close"][i]
            if np.isfinite(c): last[k] = c
        # exits / stops / adds / entries per market
        for k in keys:
            a = A[k]; o, h, l, c = a["Open"][i], a["High"][i], a["Low"][i], a["Close"][i]
            if not np.isfinite(c): continue
            cost = 0.0015 if k.endswith("-USD") else 0.0005
            p = pos.get(k)
            if p:
                ex = max(p["stop"], a[f"LL{nout}"][i]) if np.isfinite(a[f"LL{nout}"][i]) else p["stop"]
                if l <= ex:
                    px = min(o, ex); E += sum(u["q"] * (px - u["e"]) for u in p["u"]) - sum(u["q"] for u in p["u"]) * px * cost; pos.pop(k); continue
                if pyramid and len(p["u"]) < ulim and sum(len(z["u"]) for z in pos.values()) < tot:
                    lvl = p["u"][-1]["e"] + 0.5 * p["N"]
                    if h >= lvl:
                        px = max(o, lvl); N = a["N"][i]
                        if np.isfinite(N) and N > 0:
                            q = risk * E / (2 * N)
                            if (sum(sum(u["q"] for u in z["u"]) * last[kk] for kk, z in pos.items()) + q * px) / E <= gross_cap:
                                p["u"].append(dict(q=q, e=px)); E -= q * px * cost; p["stop"] = px - 2 * N; p["N"] = N
            else:
                hh, N = a[f"HH{nin}"][i], a["N"][i]
                if np.isfinite(hh) and np.isfinite(N) and N > 0 and h > hh and sum(len(z["u"]) for z in pos.values()) < tot:
                    px = max(o, hh); q = risk * E / (2 * N)
                    if (sum(sum(u["q"] for u in z["u"]) * last[kk] for kk, z in pos.items()) + q * px) / E <= gross_cap:
                        pos[k] = dict(u=[dict(q=q, e=px)], stop=px - 2 * N, N=N); E -= q * px * cost
                        if l <= px - 2 * N:
                            st = px - 2 * N; E += q * (st - px) - q * st * cost; pos.pop(k)
        mtm = E + sum(sum(u["q"] * (last[k] - u["e"]) for u in p["u"]) for k, p in pos.items())
        eq.append(mtm); gross.append(sum(sum(u["q"] for u in p["u"]) * last[k] for k, p in pos.items()) / max(mtm, 1e-9))
    return pd.Series(eq, index=idx[i0:]), pd.Series(gross, index=idx[i0:])

def st(e, a, b):
    e = e[(e.index >= a) & (e.index <= b)]; y = (e.index[-1] - e.index[0]).days / 365.25
    return round(((e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1), round((e / e.cummax() - 1).min() * 100, 1)
rows = []; curves = {}
CASES = [("20/10, 1 unit, 1%", dict(nin=20, nout=10))]
for r_ in (0.004, 0.005, 0.006, 0.007):
    CASES.append((f"20/10, pyramid x4, {r_*100:.1f}% per unit", dict(nin=20, nout=10, pyramid=True, risk=r_)))
CASES += [("20/10, 1 unit, 1%, no coins", ("nocoin", dict(nin=20, nout=10)))]
for r_ in (0.004, 0.006):
    CASES.append((f"20/10, pyramid x4, {r_*100:.1f}%, no coins", ("nocoin", dict(nin=20, nout=10, pyramid=True, risk=r_))))
CASES += [("20/10, 1 unit, 0.6%", dict(nin=20, nout=10, risk=0.006))]
for name, kw in CASES:
    if isinstance(kw, tuple):
        saved = keys[:]; keys[:] = [k for k in keys if (k.endswith("-USD")) == (kw[0] == "coins")]; e, g = sim(**kw[1]); keys[:] = saved
    else:
        e, g = sim(**kw)
    curves[name] = e
    c, dd = st(e, "2010-01-01", "2030"); c17, dd17 = st(e, "2017-01-01", "2030"); c22, _ = st(e, "2022-01-01", "2030")
    rows.append(dict(name=name, cagr_2010=c, dd_2010=dd, ratio=round(c / -dd, 2), cagr_2017=c17, dd_2017=dd17, cagr_2022=c22, gross_avg=round(g.mean() * 100), gross_max=round(g.max() * 100)))
pd.set_option("display.width", 220)
print(pd.DataFrame(rows).set_index("name").to_string())
y = pd.DataFrame({k: v.resample("YE").last().pct_change() * 100 for k, v in curves.items()}).round(1); y.index = y.index.year
print("\nBy year (%)"); print(y.iloc[1:].to_string())
print("\nMarkets:", ", ".join(MK[k] for k in keys))
