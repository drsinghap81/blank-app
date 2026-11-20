"""Rotation to make Trend 9/21 work in the short term (20 Nov 2026, Amritpal: "filter 9/21 trend with rotation to gain from short term").
Same panel, live 9/21 signals, 10 positions, 1% risk, 3 seeds and the same weekly industry quadrant as tools/research/lagging_filter_921.py.
Variants (entries / exits change, everything else as live):
  live                 random order when more signals than slots; exit Supertrend red / stop (as now)
  RANK rotation        more signals than slots -> strongest industry RS-momentum first (no industry = last)
  EXIT rotation        also sell at the next open when the stock's industry turns Weakening or Lagging
  RANK + EXIT          both
  SHORT Leading + 9EMA only industries in Leading; sell on a close below the 9 EMA (next open) or the stop / Supertrend
  SHORT Lead+Impr 9EMA same with Improving or Leading
PILOT env = 400 stocks, 1 seed."""
import os
import runpy
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("NO_RUN", "1")
G = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lagging_filter_921.py"), run_name="prep")
d, stats, mom_w = G["d"], G["stats"], G["mom"]
PILOT = G["PILOT"]
# industry RS-momentum known at each day (weekly, carried forward) for ranking
md = mom_w.reindex(sorted(d.Date.unique()), method="ffill")
mm = md.stack(future_stack=True).rename("imom").reset_index(); mm.columns = ["Date", "ind", "imom"]
d = d.merge(mm, on=["Date", "ind"], how="left")
d["imom"] = d.imom.fillna(0)
g = d.groupby("SYMBOL").CLOSE
d["e9"] = g.transform(lambda s: s.ewm(span=9, adjust=False).mean())
CFG = G["K"].CFG


def run(d, rank="random", rot_exit=False, ema9_exit=False, seed=0, maxpos=10, risk=0.01, skip=0.12, liq=0.05, start="2016-06-01", cap0=2_000_000):
    cost, slip = CFG["cost"], CFG["slip"]; maxw = 1.0 / maxpos
    days = sorted(d.Date.unique()); by = {dt: x.set_index("SYMBOL") for dt, x in d.groupby("Date")}
    rng = np.random.default_rng(seed); cash, pos, eq, trades, pending = cap0, {}, {}, [], []

    def sell(sym, px, dt, why):
        nonlocal cash
        p = pos.pop(sym); f = px * (1 - slip) * (1 - cost / 2); cash += p["q"] * f
        trades.append(dict(sym=sym, entry=p["dt"], exit=dt, ret=f / p["cin"] - 1, why=why))
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
            e = cash + sum(p["q"] * p["last"] for p in pos.values()); fill = o * (1 + slip) * (1 + cost / 2)
            q = min(risk * e / (o - stop), maxw * e / o, liq * v / o, cash / fill)
            if q * o < 0.005 * cap0:
                continue
            cash -= q * fill; pos[sym] = dict(q=q, cin=fill, stop=stop, dt=dt, last=o)
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
            if r.st == -1 or (rot_exit and r.quad in ("Weakening", "Lagging")) or (ema9_exit and r.CLOSE < r.e9 and dt > p["dt"]):
                p["sell_next"] = True
        if len(pos) < maxpos:
            t = x[x.sig & ~x.index.isin(list(pos))]
            if len(t):
                t = t.iloc[rng.permutation(len(t))] if rank == "random" else t.sort_values("imom", ascending=False)
                pending = [(s, float(r.low5), float(r.val)) for s, r in t.head(maxpos - len(pos)).iterrows()]
        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
        nxt = days[k + 1] if k + 1 < len(days) else None
        if nxt is not None:
            xn = by[nxt]
            for sym in [s for s, p in pos.items() if p.get("sell_next")]:
                if sym in xn.index:
                    sell(sym, float(xn.at[sym, "OPEN"]), nxt, "exit")
    return pd.Series(eq), pd.DataFrame(trades)


VAR = {
    "live (no rotation)": dict(),
    "RANK by industry rotation": dict(rank="imom"),
    "EXIT when industry turns Weakening / Lagging": dict(rot_exit=True),
    "RANK + EXIT": dict(rank="imom", rot_exit=True),
    "SHORT: Leading only, exit below 9 EMA": dict(only={"Leading"}, ema9_exit=True),
    "SHORT: Improving + Leading, exit below 9 EMA": dict(only={"Leading", "Improving"}, ema9_exit=True),
    "control: all industries, exit below 9 EMA": dict(ema9_exit=True),
}
seeds = (0,) if PILOT else (0, 1, 2)
for nm, kw in VAR.items():
    x = d
    if kw.get("only"):
        x = d.copy(); x["sig"] = x.sig & x.quad.isin(kw["only"])
    kw2 = {k: v for k, v in kw.items() if k != "only"}
    rs = []
    for sd in (seeds if kw2.get("rank", "random") == "random" else (0,)):
        eq, T = run(x, seed=sd, **kw2)
        a = stats(eq, "2017-01-01", "2030-01-01"); b = stats(eq, "2017-01-01", "2021-12-31"); c = stats(eq, "2022-01-01", "2030-01-01")
        hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days
        rs.append((a["cagr"], a["maxdd"], b["cagr"], c["cagr"], len(T), T.ret.mean() * 100, hold.median(), np.mean(T.ret > 0) * 100))
    m = np.array(rs)
    print(f"R| {nm}: CAGR {m[:, 0].mean():.1f}%, max drawdown {m[:, 1].mean():.1f}%, 2017-21 {m[:, 2].mean():.1f}%, 2022-26 {m[:, 3].mean():.1f}%, "
          f"trades {m[:, 4].mean():.0f}, avg trade {m[:, 5].mean():+.2f}%, win {m[:, 7].mean():.0f}%, median hold {m[:, 6].mean():.0f} days", flush=True)
