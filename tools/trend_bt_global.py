"""Backtest of the EMA 9/21 cross trend system on NSE, US or ASX stocks (Yahoo daily data, 2016 → today).
Same rules as the NSE point-in-time test (see project doc trend-scan.md):
  signal : EMA9 crosses above EMA21, Supertrend(10,3) green, close > EMA50, EMA50 above its value 10 sessions ago,
           RSI(14) >= 55, 20-day avg traded value >= market minimum, >= 120 sessions listed, close >= 70% of 52w high
  entry  : next open; stop = lowest low of the last 5 sessions, skip if > 12% away
  exit   : Supertrend turns red -> next open
  sizing : 1% of equity at risk, max 10 positions, <= 20% of equity each, <= 5% of the stock's daily traded value
CAVEAT: Yahoo only has stocks that still trade -> survivorship bias. Running market=NSE through this same pipeline gives
the bias directly (compare with the point-in-time NSE result: 26.1%/yr, 2022-26 14.5%).
Usage: python trend_bt_global.py MARKET  -> data/bt/<MARKET>.json + data/bt/<MARKET>_equity.csv
"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import MARKETS, symbols  # noqa: E402

OUT = "data/bt"


def supertrend_dir(h, l, c, n=10, m=3.0):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.empty_like(c); atr[0] = tr[0]
    for i in range(1, len(c)):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / n
    mid = (h + l) / 2
    fu, fl = mid + m * atr, mid - m * atr
    d = np.ones(len(c), dtype=np.int8)
    for i in range(1, len(c)):
        ub, lb = mid[i] + m * atr[i], mid[i] - m * atr[i]
        fu[i] = ub if (ub < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb if (lb > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = (-1 if c[i] < fl[i] else 1) if d[i - 1] == 1 else (1 if c[i] > fu[i] else -1)
    return d


def features(sym, o, h, l, c, v, minval):
    x = pd.DataFrame({"OPEN": o, "HIGH": h, "LOW": l, "CLOSE": c}).dropna()
    x = x[(x.CLOSE > 0) & (x.OPEN > 0)]
    if len(x) < 150:
        return None
    val = (x.CLOSE * v.reindex(x.index).fillna(0)).rolling(20).mean()
    if val.max() < minval:
        return None
    cc = x.CLOSE
    e9, e21, e50 = (cc.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    dlt = cc.diff()
    up = dlt.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-dlt.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    st = supertrend_dir(x.HIGH.values, x.LOW.values, cc.values)
    hi = cc.rolling(250, min_periods=60).max()
    n = np.arange(len(x))
    sig = ((e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (st == 1) & (cc > e50) & (e50 > e50.shift(10)) & (rsi >= 55)
           & (val >= minval) & (n >= 120) & (cc >= 0.7 * hi))
    return pd.DataFrame({"Date": x.index, "SYMBOL": sym, "OPEN": x.OPEN.values, "HIGH": x.HIGH.values, "LOW": x.LOW.values,
                         "CLOSE": cc.values, "st": st, "low5": x.LOW.rolling(5).min().values, "val": val.values,
                         "sig": sig.values}).astype({"OPEN": "float32", "HIGH": "float32", "LOW": "float32", "CLOSE": "float32",
                                                     "low5": "float32", "val": "float32"})


def load(market):
    cfg = MARKETS[market]
    u = symbols(market)
    print(market, "universe", len(u), flush=True)
    frames = []
    tick = list(u.ticker)
    for i in range(0, len(tick), 200):
        chunk = tick[i:i + 200]
        for attempt in range(3):
            try:
                d = yf.download(chunk, start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", i, e); time.sleep(20); d = None
        if d is None or d.empty:
            continue
        for t in chunk:
            try:
                f = features(t, d["Open"][t], d["High"][t], d["Low"][t], d["Close"][t], d["Volume"][t], cfg["min_value"])
            except Exception:  # noqa: BLE001
                f = None
            if f is not None:
                frames.append(f)
        print(market, i + len(chunk), "downloaded,", len(frames), "liquid", flush=True)
        time.sleep(3)
    return pd.concat(frames, ignore_index=True), u


def run(d, cfg, maxpos=10, risk=0.01, maxw=0.20, liq=0.05, skip=0.12, start="2016-06-01", seed=0, cap0=2_000_000):
    cost, slip = cfg["cost"], cfg["slip"]
    d = d[d.Date >= pd.Timestamp(start) - pd.Timedelta(days=10)]
    days = sorted(d.Date.unique())
    by = {dt: x.set_index("SYMBOL") for dt, x in d.groupby("Date")}
    rng = np.random.default_rng(seed)
    cash, pos, eq, trades, pending = cap0, {}, {}, [], []

    def sell(sym, px, dt, why):
        nonlocal cash
        p = pos.pop(sym)
        f = px * (1 - slip) * (1 - cost / 2)
        cash += p["q"] * f
        trades.append(dict(sym=sym, entry=p["dt"], exit=dt, pnl=p["q"] * (f - p["cin"]), R=p["q"] * (f - p["cin"]) / p["risk"], why=why))

    for dt in days:
        if dt < pd.Timestamp(start):
            continue
        x = by[dt]
        for sym, stop, v in pending:
            if sym not in x.index or sym in pos or len(pos) >= maxpos:
                continue
            o = float(x.at[sym, "OPEN"])
            if o <= stop or (o - stop) / o > skip:
                continue
            e = cash + sum(p["q"] * p["last"] for p in pos.values())
            fill = o * (1 + slip) * (1 + cost / 2)
            q = min(risk * e / (o - stop), maxw * e / o, liq * v / o, cash / fill)
            if q * o < 0.005 * cap0:
                continue
            cash -= q * fill
            pos[sym] = dict(q=q, cin=fill, stop=stop, dt=dt, last=o, risk=q * (o - stop))
        pending = []
        for sym in list(pos):
            p = pos[sym]
            if sym not in x.index:
                p["gone"] = p.get("gone", 0) + 1
                if p["gone"] >= 20:
                    sell(sym, p["last"], dt, "gone")
                continue
            p["gone"] = 0
            r = x.loc[sym]
            if r.LOW <= p["stop"]:
                sell(sym, min(float(r.OPEN), p["stop"]), dt, "stop"); continue
            p["last"] = float(r.CLOSE)
            if r.st == -1:
                p["sell_next"] = True          # Supertrend red at the close -> sell at the next open
        if len(pos) < maxpos:
            t = x[x.sig & ~x.index.isin(list(pos))]
            if len(t):
                t = t.iloc[rng.permutation(len(t))]
                pending = [(s, float(r.low5), float(r.val)) for s, r in t.head(maxpos - len(pos)).iterrows()]
        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
        # sells decided at this close execute at the next open
        nxt = days[days.index(dt) + 1] if dt != days[-1] else None
        if nxt is not None:
            xn = by[nxt]
            for sym in [s for s, p in pos.items() if p.get("sell_next")]:
                if sym in xn.index:
                    sell(sym, float(xn.at[sym, "OPEN"]), nxt, "st")
    return pd.Series(eq), pd.DataFrame(trades)


def stats(e, a, b):
    e = e[(e.index >= a) & (e.index <= b)]
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return dict(cagr=round(((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100, 1), maxdd=round((e / e.cummax() - 1).min() * 100, 1))


def main():
    market = sys.argv[1]
    cfg = MARKETS[market]
    os.makedirs(OUT, exist_ok=True)
    d, u = load(market)
    print("signals", int(d.sig.sum()), "rows", len(d), flush=True)
    res, curves = [], {}
    for seed in range(5):
        eq, T = run(d, cfg, seed=seed)
        a = stats(eq, "2017-01-01", "2030-01-01"); b = stats(eq, "2017-01-01", "2021-12-31"); c = stats(eq, "2022-01-01", "2030-01-01")
        res.append(dict(seed=seed, cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"],
                        trades=len(T), win=round((T.pnl > 0).mean() * 100) if len(T) else None,
                        pf=round(T.pnl[T.pnl > 0].sum() / max(-T.pnl[T.pnl < 0].sum(), 1), 2) if len(T) else None,
                        years={str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()}))
        curves[seed] = eq
        print(res[-1], flush=True)
    R = pd.DataFrame(res)
    med = R.sort_values("cagr").iloc[len(R) // 2]
    bench = yf.download(cfg["benchmark"], start="2016-12-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    bench = bench[bench.index >= "2017-01-01"]
    out = dict(market=market, label=cfg["label"], asof=str(date.today()), universe=len(u), liquid=int(d.SYMBOL.nunique()),
               signals=int(d.sig.sum()), runs=res, median_seed=int(med.seed),
               median=dict(cagr=float(R.cagr.median()), maxdd=float(R.maxdd.median()), cagr_17_21=float(R.cagr_17_21.median()),
                           cagr_22_26=float(R.cagr_22_26.median()), pf=float(R.pf.median()), trades=float(R.trades.median()),
                           win=float(R.win.median())),
               range=dict(cagr_min=float(R.cagr.min()), cagr_max=float(R.cagr.max())),
               benchmark=dict(name=cfg["benchmark_name"], **stats(bench, "2017-01-01", "2030-01-01"),
                              cagr_22_26=stats(bench, "2022-01-01", "2030-01-01")["cagr"]))
    json.dump(out, open(f"{OUT}/{market}.json", "w"), indent=1, default=str)
    pd.DataFrame({f"seed{k}": v for k, v in curves.items()}).to_csv(f"{OUT}/{market}_equity.csv")
    print(json.dumps(out["median"]), json.dumps(out["benchmark"]))


if __name__ == "__main__":
    main()
