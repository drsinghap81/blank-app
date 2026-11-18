"""High-conviction, concentrated version of the Trend 9/21 swing system (18 Nov 2026, Amritpal: "one trade at a time with full
capital, then the next ... a swing system of 1-2 weeks ... backtest a high-conviction concentrated system").

Signals, entry, stop and exit exactly as tools/trend_bt_global.py (the live 9/21 rules): EMA9 crosses above EMA21, Supertrend(10,3)
green, close > EMA50 (rising), RSI(14) >= 55, close >= 70% of the 52-week high, liquid; buy next open; stop = 5-day low (skip if
> 12% away); exit when Supertrend turns red (next open) or the stop.
What changes:
  positions : 1, 2, 3, 5 or 10 at a time
  sizing    : 1% / 2% / 3% of equity at risk per trade (capped at 1/positions of equity), or "all in" (each position gets
              1/positions of equity, no risk cap - "full capital")
  conviction: when more signals than free slots - random (2 seeds), nearest the 52-week high, or strongest 3-month return
NSE stocks from Yahoo 2016 -> today (stocks that still trade: survivorship bias flatters every row equally; the point-in-time
10-position result was about 5 points a year lower). Costs as the live test (0.25% + 0.15% slippage a side).
Output: data/research/concentrated_921.json"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import MARKETS  # noqa: E402
from trend_bt_global import load, stats  # noqa: E402

CFG = MARKETS["NSE"]
D = None


def run(d, maxpos, risk, rank, seed, skip=0.12, liq=0.05, start="2016-06-01", cap0=2_000_000):
    cost, slip = CFG["cost"], CFG["slip"]
    maxw = 1.0 / maxpos
    days = sorted(d.Date.unique())
    by = {dt: x.set_index("SYMBOL") for dt, x in d.groupby("Date")}
    rng = np.random.default_rng(seed)
    cash, pos, eq, trades, pending = cap0, {}, {}, [], []

    def sell(sym, px, dt, why):
        nonlocal cash
        p = pos.pop(sym); f = px * (1 - slip) * (1 - cost / 2); cash += p["q"] * f
        trades.append(dict(sym=sym, entry=p["dt"], exit=dt, ret=f / p["cin"] - 1, pnl=p["q"] * (f - p["cin"]), why=why))

    for k, dt in enumerate(days):
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
            q = min(maxw * e / o, liq * v / o, cash / fill) if risk is None else min(risk * e / (o - stop), maxw * e / o, liq * v / o, cash / fill)
            if q * o < 0.005 * cap0:
                continue
            cash -= q * fill
            pos[sym] = dict(q=q, cin=fill, stop=stop, dt=dt, last=o)
        pending = []
        for sym in list(pos):
            p = pos[sym]
            if sym not in x.index:
                p["gone"] = p.get("gone", 0) + 1
                if p["gone"] >= 20:
                    sell(sym, p["last"], dt, "gone")
                continue
            p["gone"] = 0; r = x.loc[sym]
            if r.LOW <= p["stop"]:
                sell(sym, min(float(r.OPEN), p["stop"]), dt, "stop"); continue
            p["last"] = float(r.CLOSE)
            if r.st == -1:
                p["sell_next"] = True
        if len(pos) < maxpos:
            t = x[x.sig & ~x.index.isin(list(pos))]
            if len(t):
                if rank == "random":
                    t = t.iloc[rng.permutation(len(t))]
                else:
                    t = t.sort_values(rank, ascending=False)
                pending = [(s, float(r.low5), float(r.val)) for s, r in t.head(maxpos - len(pos)).iterrows()]
        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
        nxt = days[k + 1] if k + 1 < len(days) else None
        if nxt is not None:
            xn = by[nxt]
            for sym in [s for s, p in pos.items() if p.get("sell_next")]:
                if sym in xn.index:
                    sell(sym, float(xn.at[sym, "OPEN"]), nxt, "st")
    return pd.Series(eq), pd.DataFrame(trades)


def one(args):
    maxpos, risk, rank, seed = args
    eq, T = run(D, maxpos, risk, rank, seed)
    a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
    m = eq.resample("ME").last().pct_change().dropna()
    hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
    yrs = {str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()}
    return dict(positions=maxpos, sizing="all in" if risk is None else f"{risk * 100:g}% risk", rank=rank, seed=seed,
                cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"],
                worst_month=round(m.min() * 100, 1) if len(m) else None, losing_years=sum(v < 0 for v in yrs.values()), years=yrs,
                trades=len(T), win=round((T.pnl > 0).mean() * 100) if len(T) else None,
                avg_trade=round(T.ret.mean() * 100, 2) if len(T) else None,
                hold_median_days=float(hold.median()) if len(hold) else None,
                hold_share_5_15d=round(((hold >= 5) & (hold <= 15)).mean() * 100) if len(hold) else None,
                time_in_market=round((eq.diff().fillna(0) != 0).mean() * 100) if len(eq) else None)


def main():
    global D
    d, _ = load("NSE")
    d = d.sort_values(["SYMBOL", "Date"])
    g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    D = d
    print("signals", int(d.sig.sum()), flush=True)
    grid = []
    for mp in (1, 2, 3, 5, 10):
        for rk in (0.01, 0.02, 0.03, None):
            for rank, seeds in (("random", (0, 1)), ("near_high", (0,)), ("r63", (0,))):
                for sd in seeds:
                    grid.append((mp, rk, rank, sd))
    with Pool(4) as pool:
        res = []
        for r in pool.imap_unordered(one, grid):
            res.append(r); print(json.dumps({k: v for k, v in r.items() if k != "years"}), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(dict(method=__doc__, runs=sorted(res, key=lambda r: (r["positions"], r["sizing"], r["rank"], r["seed"]))),
              open("data/research/concentrated_921.json", "w"), indent=1)


if __name__ == "__main__":
    main()
