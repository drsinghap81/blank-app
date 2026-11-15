"""Research (16 Nov 2026): Turtle rules on 1-hour bars vs daily bars over the same ~2 years (Yahoo keeps 730 days of hourly data).
Rules as the slide: buy-stop above the N-bar high; fixed stop = entry - 2 ATR(20 bars); trail = M-bar low; first hit exits. Short mirror.
Bar lengths: 20/10 and 55/20 bars on hourly charts, and 20/10 on daily charts for comparison. Cost per side: futures-like 0.02%,
coins 0.08%, indices 0.02%. Output: trades, avg R, profit factor, total return % summed per trade (1 position, no compounding)."""
import time
import numpy as np, pandas as pd, yfinance as yf

MK = {"GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude oil", "HG=F": "Copper", "^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^NSEI": "Nifty 50",
      "^NSEBANK": "Bank Nifty", "EURUSD=X": "EUR/USD", "USDJPY=X": "USD/JPY", "USDINR=X": "USD/INR", "BTC-USD": "Bitcoin", "ETH-USD": "Ether"}

def trades(x, nin, nout, side, cost):
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); n = len(c)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.r_[np.nan, pd.Series(tr).ewm(alpha=1 / 20, adjust=False, min_periods=20).mean().to_numpy()]
    hh = pd.Series(h).shift(1).rolling(nin).max().to_numpy(); ll = pd.Series(l).shift(1).rolling(nin).min().to_numpy()
    tlo = pd.Series(l).shift(1).rolling(nout).min().to_numpy(); thi = pd.Series(h).shift(1).rolling(nout).max().to_numpy()
    out = []; t = max(nin, 21) + 1
    while t < n:
        a = atr[t - 1]
        if side == "L" and np.isfinite(hh[t]) and h[t] > hh[t] and np.isfinite(a) and a > 0:
            e = max(o[t], hh[t]); fix = e - 2 * a; xi = None
            for u in range(t, n):
                stp = max(fix, tlo[u]) if u > t and np.isfinite(tlo[u]) else fix
                if l[u] <= stp: xp = min(o[u], stp) if u > t else stp; xi = u; break
            if xi is None: xp, xi = c[-1], n - 1
            r = xp / e - 1 - 2 * cost; out.append(dict(ret=r, R=r * e / (2 * a), bars=xi - t)); t = xi + 1
        elif side == "S" and np.isfinite(ll[t]) and l[t] < ll[t] and np.isfinite(a) and a > 0:
            e = min(o[t], ll[t]); fix = e + 2 * a; xi = None
            for u in range(t, n):
                stp = min(fix, thi[u]) if u > t and np.isfinite(thi[u]) else fix
                if h[u] >= stp: xp = max(o[u], stp) if u > t else stp; xi = u; break
            if xi is None: xp, xi = c[-1], n - 1
            r = e / xp - 1 - 2 * cost; out.append(dict(ret=r, R=r * e / (2 * a), bars=xi - t)); t = xi + 1
        else:
            t += 1
    return out

rows = []
for tk, nm in MK.items():
    cost = 0.0008 if tk.endswith("-USD") else 0.0002
    for itv, per in (("1h", "730d"), ("1d", "2y")):
        try:
            x = yf.download(tk, period=per, interval=itv, auto_adjust=False, progress=False)
        except Exception as e:  # noqa: BLE001
            print("fail", tk, itv, e); continue
        if x is None or x.empty: print("no data", tk, itv); continue
        if isinstance(x.columns, pd.MultiIndex): x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
        if tk.endswith("=X"): x = x.assign(High=np.minimum(x.High, np.maximum(x.Open, x.Close) * 1.01), Low=np.maximum(x.Low, np.minimum(x.Open, x.Close) / 1.01))
        sets = [("20/10", 20, 10), ("55/20", 55, 20)] if itv == "1h" else [("20/10", 20, 10)]
        for sn, a, b in sets:
            for side in "LS":
                for r in trades(x, a, b, side, cost): rows.append(dict(r, asset=nm, tf=itv, sys=sn, side=side, span=f"{x.index[0].date()}..{x.index[-1].date()}"))
        time.sleep(0.4)
T = pd.DataFrame(rows)
def pf(v): return v[v > 0].sum() / -v[v < 0].sum() if (v < 0).any() else np.inf
agg = dict(n=("R", "size"), R=("R", "mean"), pf=("ret", pf), win=("ret", lambda v: (v > 0).mean() * 100), total_pct=("ret", lambda v: v.sum() * 100), bars=("bars", "median"))
pd.set_option("display.width", 220)
print("ALL ASSETS"); print(T.groupby(["tf", "sys", "side"]).agg(**agg).round(2).to_string())
print("\nBY ASSET, long side"); print(T[T.side == "L"].groupby(["asset", "tf", "sys"]).agg(**agg).round(2).to_string())
print("\nBY ASSET, short side"); print(T[T.side == "S"].groupby(["asset", "tf", "sys"]).agg(**agg).round(2).to_string())
print("\nspans:", T.groupby(["asset", "tf"]).span.first().to_dict())
