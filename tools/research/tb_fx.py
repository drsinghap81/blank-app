"""Top Bottom on currency pairs (24 Nov 2026, Amritpal: "I need a basket of currency pairs too. Have you tested Top Bottom in those?").
Live engine (tools/topbottom_backtest.run_live), both sides (and buy-only for comparison), Yahoo daily spot 2010 -> today:
majors, crosses and INR pairs (USDINR/EURINR/GBPINR/JPYINR trade as NSE currency futures on Angel).
Two rule sets: index rules (1% entry-day stop, 2% max stop, breakeven 2%, 1% gap) and FX-scaled rules (half of those: currencies
move ~0.5%/day vs ~1% for indices). Buffer 0.05%, cost 0.02% a round trip. Per pair: trades, profit factor 2010-17 -> 2018-26,
CAGR / max DD on notional (1x), last 1/3/5 years. Books (daily marked to close, monthly rebalance): equal weight, inverse-vol, and
inverse-vol scaled to 10% annual volatility (max 5x - FX is normally traded with leverage). Newest-first windows, yearly returns."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURCHF",
         "USDINR", "EURINR", "GBPINR", "JPYINR"]
RULES = {"index": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0), "fx": dict(day_sl_pct=0.5, max_sl_pct=1.0, be_pct=1.0, gap_pct=0.5)}
COST = 0.0002


def yh(p):
    d = yf.download(p + "=X", start="2009-06-01", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna()
    x = x[(x.High >= x.Low) & (x.Close > 0) & (x.index >= "2010-01-01")]
    j = x.Close.pct_change().abs(); return x[~(j > 0.08)]          # drop bad ticks


def daily(x, t):
    c = x.Close; r = pd.Series(0.0, index=x.index)
    for _, tr in t.iterrows():
        e, xd = pd.Timestamp(tr.EntryDate), pd.Timestamp(tr.ExitDate); sgn = 1 if tr.Side == "BUY" else -1
        days = c.loc[e:xd].index; prev = tr.Entry
        for d in days:
            px = tr.Exit if (d == xd and not tr.get("Open", False)) else c.loc[d]
            r.loc[d] += sgn * (px / prev - 1); prev = px
        if not tr.get("Open", False) and len(days):
            r.loc[xd] -= COST
    return r


def pf(t):
    if not len(t):
        return None
    p = t.PnLPct if "PnLPct" in t else (np.where(t.Side == "BUY", t.Exit / t.Entry - 1, t.Entry / t.Exit - 1) * 100)
    p = pd.Series(np.asarray(p, float)) - COST * 100; g, l = p[p > 0].sum(), -p[p < 0].sum()
    return round(float(g / l), 2) if l > 0 else None


def stats(r):
    if r.abs().sum() == 0:
        return "no trades"
    eq = (1 + r).cumprod(); yrs = len(r) / 252; cagr = eq.iloc[-1] ** (1 / yrs) - 1; dd = (eq / eq.cummax() - 1).min()
    m = (1 + r).groupby(r.index.to_period("M")).prod() - 1; vol = r.std() * np.sqrt(252)
    y = np.log(eq.values); r2 = np.corrcoef(np.arange(len(y)), y)[0, 1] ** 2
    w = {k: ((1 + r[r.index > r.index[-1] - pd.DateOffset(years=k)]).prod() ** (1 / k) - 1) * 100 for k in (1, 3, 5)}
    return (f"CAGR {cagr * 100:5.1f}% | DD {dd * 100:6.1f}% | R2 {r2:.2f} | up months {(m > 0).mean() * 100:3.0f}% | vol {vol * 100:4.1f}% "
            f"Sharpe {(r.mean() * 252 / vol if vol else 0):.2f} | 1y {w[1]:+.1f} 3y {w[3]:+.1f} 5y {w[5]:+.1f}")


def main():
    X = {}
    for p in PAIRS:
        try:
            X[p] = yh(p); print("R| loaded", p, len(X[p]), X[p].index[0].date(), flush=True)
        except Exception as e:  # noqa: BLE001
            print("R| skip", p, e)
    for rn, rp in RULES.items():
        for side in ("both", "buy"):
            S = {}
            for p, x in X.items():
                prm = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=(side == "buy"), **rp)
                t = tbb.run_live(x, prm); t = t[~t.get("Open", False)] if "Open" in t else t
                a = t[pd.to_datetime(t.EntryDate) < "2018-01-01"]; b = t[pd.to_datetime(t.EntryDate) >= "2018-01-01"]
                S[p] = daily(x, tbb.run_live(x, prm))
                print(f"R| {rn:5s} {side:4s} {p:7s} trades {len(t):4d} | PF 2010-17 {pf(a)} -> 2018-26 {pf(b)} | {stats(S[p])}", flush=True)
            R = pd.DataFrame(S).fillna(0.0); R = R.groupby(R.index.normalize()).sum(); months = R.index.to_period("M")

            def book(sel, target=None):
                out = pd.Series(0.0, index=R.index)
                for m in sorted(set(months)):
                    idx = R.index[months == m]; h = R[R.index < idx[0]].iloc[-120:][sel]
                    v = h.std().replace(0, np.nan); w = (1 / v).fillna(0) if len(h) >= 60 and not v.isna().all() else pd.Series(1.0, index=sel)
                    w = w / w.sum() if w.sum() else pd.Series(1.0 / len(sel), index=sel)
                    if target and len(h) > 60:
                        pv = (h @ w).std() * np.sqrt(252)
                        if pv > 0:
                            w = w * min(5.0, target / pv)
                    out.loc[idx] = R.loc[idx, sel] @ w
                return out
            allp = list(R.columns)
            # pairs that were good in 2010-17 only (no look-ahead pick): PF > 1.1 in the first half
            good = []
            for p, x in X.items():
                prm = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=(side == "buy"), **rp)
                t = tbb.run_live(x, prm); a = t[pd.to_datetime(t.EntryDate) < "2018-01-01"]
                if (pf(a) or 0) > 1.1:
                    good.append(p)
            for lab, sel in (("all pairs", allp), (f"2010-17 PF>1.1 ({len(good)}: {' '.join(good)})", good)):
                if not sel:
                    continue
                for bl, tg in (("inverse-vol 1x", None), ("inverse-vol, 10% vol target (max 5x)", 0.10)):
                    r = book(sel, tg); r2 = r[r.index >= "2018-01-01"]
                    print(f"R| BOOK {rn} {side} | {lab} | {bl} | all {stats(r)} || 2018-26 only {stats(r2)}", flush=True)
                    yr = ((1 + r).groupby(r.index.year).prod() - 1) * 100
                    print(f"R| BOOK {rn} {side} | {lab} | {bl} | years " + " ".join(f"{y}:{v:+.0f}" for y, v in yr.sort_index(ascending=False).items()), flush=True)
            print("R| median pairwise corr", round(float(np.nanmedian(R.corr().values[np.triu_indices(R.shape[1], 1)])), 2), flush=True)


if __name__ == "__main__":
    main()
