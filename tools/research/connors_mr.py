"""Connors-style mean reversion, done to the book (25 Nov 2026, Amritpal: "so no mean reversion or extension strategy like Connors will work? Are you sure").
The swing test used a 2xATR stop and 0.4% cost - neither is Connors. Here: NO stop, entry at the close, exit at the close.
  C-RSI2<10    close > 200-SMA, RSI(2) < 10, exit first close > 5-SMA
  C-RSI2<5     same, RSI(2) < 5
  C-CumRSI<35  2-day sum of RSI(2) < 35 (Connors cumulative RSI), exit RSI(2) > 65
  C-3down      3 lower closes in a row above the 200-SMA, exit close > 5-SMA
  X-BBlow      close below the lower Bollinger band (20, 2) above the 200-SMA, exit close > 5-SMA
  X-stretch    close more than 2.5 ATR below the 20-EMA above the 200-SMA, exit close > 5-SMA
Shorts = the mirror (below a falling 200-SMA). Max hold 20 sessions.
Returns shown GROSS and net of 0.1% (index futures / ETF) and 0.4% (stock delivery).
Portfolio: 10 equal slots (10% each), net 0.4% for stocks / 0.1% for indices. Newest-first years, bull/bear (index above its 200-SMA), ex-Covid.
Universes: NSE stocks (FV.load), large caps (today's Nifty 100), and indices/ETFs (Nifty, Bank Nifty, NIFTYBEES, BANKBEES, plus SPY/QQQ as the
market Connors built it on). PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

COVID = (pd.Timestamp("2020-02-15"), pd.Timestamp("2020-12-31"))
IDX = {"^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "NIFTYBEES.NS": "NIFTYBEES", "BANKBEES.NS": "BANKBEES", "SPY": "SPY (US)", "QQQ": "QQQ (US)"}


def rsi(c, p=2):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def trades(sym, x, reg):
    c = x.CLOSE; cv = c.to_numpy(float); D = c.index; n = len(cv); out = []
    s200 = c.rolling(200).mean(); s5 = c.rolling(5).mean().to_numpy(float); e20 = c.ewm(span=20, adjust=False).mean()
    r2 = rsi(c); r2v = r2.to_numpy(float); cum = (r2 + r2.shift()).to_numpy(float)
    sd = c.rolling(20).std(); m20 = c.rolling(20).mean()
    atr = pd.concat([x.HIGH - x.LOW, (x.HIGH - c.shift()).abs(), (x.LOW - c.shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
    up = ((c > s200) & (s200 > s200.shift(20))).to_numpy(); dn = ((c < s200) & (s200 < s200.shift(20))).to_numpy()
    d3 = ((c < c.shift()) & (c.shift() < c.shift(2)) & (c.shift(2) < c.shift(3))).to_numpy()
    u3 = ((c > c.shift()) & (c.shift() > c.shift(2)) & (c.shift(2) > c.shift(3))).to_numpy()
    bbl = (c < m20 - 2 * sd).to_numpy(); bbh = (c > m20 + 2 * sd).to_numpy()
    stl = (c < e20 - 2.5 * atr).to_numpy(); sth = (c > e20 + 2.5 * atr).to_numpy()
    rules = {"C-RSI2<10": (r2v < 10, r2v > 90, "s5"), "C-RSI2<5": (r2v < 5, r2v > 95, "s5"), "C-CumRSI<35": (cum < 35, cum > 165, "r65"),
             "C-3down": (d3, u3, "s5"), "X-BBlow": (bbl, bbh, "s5"), "X-stretch": (stl, sth, "s5")}
    for v, (lo, hi, ex) in rules.items():
        for side, sig, tr in (("L", lo, up), ("S", hi, dn)):
            i = 210
            while i < n - 1:
                if tr[i] and sig[i]:
                    k = i + 1
                    while k < min(i + 20, n - 1):
                        if side == "L" and ((ex == "s5" and cv[k] > s5[k]) or (ex == "r65" and r2v[k] > 65)):
                            break
                        if side == "S" and ((ex == "s5" and cv[k] < s5[k]) or (ex == "r65" and r2v[k] < 35)):
                            break
                        k += 1
                    g = cv[k] / cv[i] - 1; g = g if side == "L" else -g
                    out.append(dict(sym=sym, v=v, side=side, d=D[i], dx=D[k], hold=k - i, g=g, bull=bool(reg.get(D[i], True))))
                    i = k + 1
                else:
                    i += 1
    return out


def port(X, cost):
    X = X.sort_values(["d", "sym"]); eq = 1.0; op = []; peak = 1.0; mdd = 0.0
    for r in X.itertuples():
        for p in sorted([p for p in op if p[0] < r.d]):
            eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        op = [p for p in op if p[0] >= r.d]
        if len(op) < 10:
            op.append((r.dx, 0.1 * eq * (r.g - cost)))
    for p in sorted(op):
        eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    yrs = max((X.dx.max() - X.d.min()).days / 365.25, 1)
    return ((max(eq, 1e-9)) ** (1 / yrs) - 1) * 100, mdd * 100


def s(X, cost):
    if len(X) < 30:
        return f"n {len(X)}"
    net = X.g - cost; xc = X[~X.d.between(*COVID)]; gw = net[net > 0].sum(); gl = -net[net < 0].sum()
    cg, dd = port(X, cost)
    return (f"n {len(X):6d} | win {(X.g > 0).mean() * 100:3.0f}% | gross {X.g.mean() * 100:+.2f}% | net0.1 {(X.g.mean() - .001) * 100:+.2f}% | net0.4 {(X.g.mean() - .004) * 100:+.2f}%"
            f" | PF(net {cost * 100:.1f}) {gw / max(gl, 1e-9):.2f} | hold {X.hold.mean():.1f}d | bull {X[X.bull].g.mean() * 100:+.2f}% bear {X[~X.bull].g.mean() * 100:+.2f}%"
            f" | ex-Covid {xc.g.mean() * 100:+.2f}% | port CAGR {cg:+.1f}% maxDD {dd:.1f}%")


def years(X):
    y = X.groupby(X.d.dt.year).g.agg(["size", "mean"]).sort_index(ascending=False)
    return " | ".join(f"{k}: {int(r['size'])} {r['mean'] * 100:+.2f}%" for k, r in y.iterrows())


def main():
    nif = yf.download("^NSEI", start="2010-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    T = []
    # indices / ETFs first
    for t, nm in IDX.items():
        x = yf.download(t, start="2005-01-01", auto_adjust=True, progress=False)
        if x is None or x.empty:
            continue
        x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
        x = x.rename(columns={"Open": "OPEN", "High": "HIGH", "Low": "LOW", "Close": "CLOSE"}).dropna()
        x.index = pd.to_datetime(x.index).tz_localize(None)
        if t in ("SPY", "QQQ"):
            r_ = (x.CLOSE > x.CLOSE.rolling(200).mean()).to_dict()
        else:
            r_ = reg
        T += [dict(r, grp="index", nm=nm) for r in trades(nm, x, r_)]
        print(f"R| loaded {nm}: {x.index[0].date()} to {x.index[-1].date()}", flush=True)
    big = set()
    for f in ("nifty50", "niftynext50"):
        big |= set(pd.read_csv(f"data/universe/{f}.csv").Symbol.str.strip())
    P = FV.load()
    for sym, x in P.items():
        T += [dict(r, grp="stock", nm=sym, big=sym in big) for r in trades(sym, x, reg)]
    T = pd.DataFrame(T); T["big"] = T.get("big", False).fillna(False).astype(bool)
    vs = ["C-RSI2<10", "C-RSI2<5", "C-CumRSI<35", "C-3down", "X-BBlow", "X-stretch"]
    for side, lab in (("L", "LONG (buy weakness above a rising 200-SMA)"), ("S", "SHORT (sell strength below a falling 200-SMA)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm in IDX.values():
            for v in vs:
                X = T[(T.grp == "index") & (T.nm == nm) & (T.side == side) & (T.v == v)]
                if len(X):
                    print(f"R| {nm:11s} {v:12s} {s(X, 0.001)}", flush=True)
        for v in vs:
            X = T[(T.grp == "index") & (T.side == side) & (T.v == v) & T.nm.isin(["Nifty 50", "Bank Nifty"])]
            if len(X) >= 30:
                print(f"R| Nifty+BankNifty {v} by year: {years(X)}", flush=True)
        for v in vs:
            X = T[(T.grp == "stock") & (T.side == side) & (T.v == v)]
            print(f"R| ALL STOCKS  {v:12s} {s(X, 0.004)}", flush=True)
            Z = X[X.big]
            print(f"R| LARGE CAPS  {v:12s} {s(Z, 0.004)}", flush=True)
        for v in vs:
            Z = T[(T.grp == "stock") & (T.side == side) & (T.v == v) & T.big]
            if len(Z) >= 30:
                print(f"R| LARGE CAPS {v} by year: {years(Z)}", flush=True)


if __name__ == "__main__":
    main()
