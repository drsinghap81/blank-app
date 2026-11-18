"""Turtle 20/10 on F&O stocks (19 Nov 2026, Amritpal: "also F&O stocks - backtest first").

Rules as tools/turtle_watch.py (long only): buy-stop above the highest high of the last 20 days (filled at max(open, that high));
N = ATR(20, Wilder) the day before; fixed stop = entry - 2N; trailing stop = lowest low of the last 10 days; out at the first hit
(at min(open, stop)). Stocks in cash (no leverage): 1% of equity at risk per trade, at most 1/positions of equity in one stock,
at most 5% of the stock's 20-day traded value. When more breakouts than free slots: random (2 seeds) or strongest 3-month gain.
Also the same on Nifty-filtered days only (Nifty above its 200-day average).
Universe: today's F&O stocks (data/universe/fno_stocks.csv - survivors), Yahoo daily 2015 -> today; costs 0.25% round trip +
0.15% slippage a side. Reference: the live 9/21 system on the same F&O stocks, same engine (tools/research/concentrated_921.py).
Output: data/research/turtle_fno.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import features, stats  # noqa: E402
import concentrated_921 as C  # noqa: E402

COST, SLIP = 0.0025, 0.0015


def prep(sym, x):
    x = x[["Open", "High", "Low", "Close", "Volume"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
    if len(x) < 260:
        return None
    h, l, c = x.High, x.Low, x.Close
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    N = tr.ewm(alpha=1 / 20, adjust=False, min_periods=20).mean()
    return pd.DataFrame({"Date": x.index, "SYMBOL": sym, "O": x.Open.values, "H": h.values, "L": l.values, "C": c.values,
                         "hh": h.shift(1).rolling(20).max().values, "ll": l.shift(1).rolling(10).min().values, "N": N.shift(1).values,
                         "val": (c * x.Volume).rolling(20).mean().values, "r63": (c / c.shift(63) - 1).values})


def run(T, maxpos, rank, seed, mkt_ok=None, start="2016-06-01", cap0=2_000_000, risk=0.01):
    days = sorted(T.Date.unique()); by = {d: x.set_index("SYMBOL") for d, x in T.groupby("Date")}
    rng = np.random.default_rng(seed); cash, pos, eq, trades = cap0, {}, {}, []
    maxw = 1.0 / maxpos
    for d in days:
        if d < pd.Timestamp(start):
            continue
        x = by[d]
        # exits first (stops are resting orders from the previous close)
        for s in list(pos):
            p = pos[s]
            if s not in x.index:
                continue
            r = x.loc[s]; st = max(p["fix"], r.ll) if np.isfinite(r.ll) else p["fix"]
            if r.L <= st:
                px = min(r.O, st) * (1 - SLIP) * (1 - COST / 2); cash += p["q"] * px
                trades.append(dict(sym=s, entry=p["d"], exit=d, ret=px / p["cin"] - 1)); del pos[s]
            else:
                p["last"] = r.C
        # new entries: today's breakouts (buy-stop above yesterday's 20-day high), slots permitting
        if len(pos) < maxpos and (mkt_ok is None or mkt_ok.get(d, False)):
            c_ = x[(x.H > x.hh) & np.isfinite(x.hh) & np.isfinite(x.N) & (x.N > 0) & (x.C >= 50) & (x.val >= 5e7) & ~x.index.isin(list(pos))]
            if len(c_):
                c_ = c_.iloc[rng.permutation(len(c_))] if rank == "random" else c_.sort_values("r63", ascending=False)
                e = cash + sum(p["q"] * p["last"] for p in pos.values())
                for s, r in c_.iterrows():
                    if len(pos) >= maxpos:
                        break
                    fill = max(r.O, r.hh) * (1 + SLIP) * (1 + COST / 2); fix = max(r.O, r.hh) - 2 * r.N
                    q = min(risk * e / (2 * r.N), maxw * e / fill, 0.05 * r.val / fill, cash / fill)
                    if q * fill < 0.005 * cap0:
                        continue
                    cash -= q * fill; pos[s] = dict(q=q, cin=fill, fix=fix, d=d, last=r.C)
                    if r.L <= fix:                                   # stopped the same day
                        px = fix * (1 - SLIP) * (1 - COST / 2); cash += q * px
                        trades.append(dict(sym=s, entry=d, exit=d, ret=px / fill - 1)); del pos[s]
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos.values())
    return pd.Series(eq), pd.DataFrame(trades)


def summ(eq, T):
    a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
    hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
    yrs = {str(k.year): round(v * 100, 1) for k, v in eq.resample("YE").last().pct_change().dropna().items()}
    return dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                win=round((T.ret > 0).mean() * 100) if len(T) else None, avg_trade=round(T.ret.mean() * 100, 2) if len(T) else None,
                hold_median_days=float(hold.median()) if len(hold) else None, losing_years=sum(v < 0 for v in yrs.values()), years=yrs)


def main():
    syms = pd.read_csv("data/universe/fno_stocks.csv").Symbol.tolist()
    tk = [s + ".NS" for s in syms]; frames, f921 = [], []
    for i in range(0, len(tk), 60):
        D = yf.download(tk[i:i + 60], start="2015-01-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in tk[i:i + 60]:
            try:
                x = D[t]
            except Exception:  # noqa: BLE001
                continue
            p = prep(t[:-3], x)
            if p is not None:
                frames.append(p)
            try:
                f = features(t[:-3], x.Open, x.High, x.Low, x.Close, x.Volume, 1e7)
                if f is not None:
                    f921.append(f)
            except Exception:  # noqa: BLE001
                pass
        print("downloaded", i + 60, flush=True)
    T = pd.concat(frames, ignore_index=True)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    ok = (nif > nif.rolling(200).mean()).to_dict()
    res = dict(method=__doc__, stocks=int(T.SYMBOL.nunique()))
    for mp in (5, 10, 20):
        for rank, seeds in (("random", (0, 1)), ("r63", (0,))):
            for sd in seeds:
                for filt in (None, "nifty>200d"):
                    eq, tr = run(T, mp, rank, sd, ok if filt else None)
                    k = f"Turtle, {mp} positions, {rank}{'' if rank != 'random' else ' s' + str(sd)}{', ' + filt if filt else ''}"
                    res[k] = summ(eq, tr); print(k, {x: res[k][x] for x in ('cagr', 'maxdd', 'cagr_22_26', 'trades', 'win', 'hold_median_days')}, flush=True)
    # 9/21 reference on the same stocks
    d = pd.concat(f921, ignore_index=True).sort_values(["SYMBOL", "Date"]); g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max()); d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    for mp, rank in ((10, "random"), (5, "r63")):
        eq, tr = C.run(d, mp, 0.01, rank, 0)
        k = f"9/21 reference, {mp} positions, {rank}"
        res[k] = summ(eq, tr.assign(ret=tr.ret)); print(k, {x: res[k][x] for x in ('cagr', 'maxdd', 'cagr_22_26', 'trades')}, flush=True)
    b = nif[nif.index >= "2017-01-01"]
    res["Nifty 50"] = dict(cagr=round(((b.iloc[-1] / b.iloc[0]) ** (365.25 / (b.index[-1] - b.index[0]).days) - 1) * 100, 1),
                           maxdd=round(((b / b.cummax()) - 1).min() * 100, 1))
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/turtle_fno.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
