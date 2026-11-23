"""Which liquid instruments suit Top Bottom? (24 Nov 2026, Amritpal: "identify liquid stocks or assets where we can run Top Bottom").
Near-month futures from NSE bhavcopies (data/futures/*.csv: 52 Nifty-50 stocks + NIFTY/BANKNIFTY), long + short, live engine
(tools/topbottom_backtest.run_live), buffer 0.05%. Stocks: 1.5% entry-day SL / 3% max / breakeven 3%; indices: 1/2/2. Cost 0.1% (stocks)
0.05% (indices) a round trip. Returns on contract value, compounded per trade.
To avoid picking lucky winners, traits are measured on the FIRST half (2010-2017) and judged on the SECOND half (2018 -> today):
  PF_in (Top Bottom profit factor 2010-17), ATR% (median ATR14 / close), ER (median 20-day efficiency ratio = |net move| / sum of
  daily moves), ADX (median ADX14), whipsaw rate (share of trades stopped within 2 days).
Output: per instrument both halves, rank correlations of each trait with the second-half result, and second-half results by
first-half tercile. Also the latest-5-year ranking (what to run now)."""
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

SPLIT = pd.Timestamp("2018-01-01")


def traits(x):
    h, l, c = x.High, x.Low, x.Close
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean(); atrp = (atr / c * 100).median()
    er = ((c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum()).median()
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdi = 100 * pd.Series(pdm, index=x.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=x.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi)).ewm(alpha=1 / 14, adjust=False).mean()
    return dict(atr=round(atrp, 2), er=round(er, 3), adx=round(adx.median(), 1))


def perf(t, cost):
    if t.empty:
        return dict(n=0)
    r = t.Pct / 100 - cost; yrs = max((t.ExitDate.max() - t.EntryDate.min()).days / 365.25, 0.5)
    eq = (1 + r).cumprod(); g, b = r[r > 0].sum(), -r[r < 0].sum()
    quick = ((t.ExitDate - t.EntryDate).dt.days <= 3) & (r < 0)
    return dict(n=len(t), win=round((r > 0).mean() * 100), pf=round(g / b, 2) if b else 9.0, cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1),
                dd=round(((eq / eq.cummax()) - 1).min() * 100, 1), whip=round(quick.mean() * 100), long_pf=round(r[t.Side == "BUY"][r > 0].sum() / max(1e-9, -r[t.Side == "BUY"][r < 0].sum()), 2))


def main():
    rows = []
    for f in sorted(glob.glob("data/futures/*.csv")):
        sym = os.path.basename(f)[:-4]
        x = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]].dropna()
        x = x[(x.index >= "2010-01-01") & (x.High >= x.Low)]
        if len(x) < 1500:
            continue
        idx = sym in ("NIFTY", "BANKNIFTY", "FINNIFTY")
        kw = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0) if idx else dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)
        cost = 0.0005 if idx else 0.001
        t = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **kw))
        if t.empty:
            continue
        t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ExitDate"] = pd.to_datetime(t.ExitDate)
        a, b = t[t.EntryDate < SPLIT], t[t.EntryDate >= SPLIT]
        end = t.ExitDate.max(); l5 = t[t.ExitDate > end - pd.DateOffset(years=5)]; l2 = t[t.ExitDate > end - pd.DateOffset(years=2)]
        tin = traits(x[x.index < SPLIT]) if (x.index < SPLIT).sum() > 500 else dict(atr=np.nan, er=np.nan, adx=np.nan)
        tnow = traits(x[x.index >= x.index[-1] - pd.DateOffset(years=2)])
        r = dict(sym=sym, kind="index" if idx else "stock", first=x.index[0].date(), **{f"in_{k}": v for k, v in perf(a, cost).items()},
                 **{f"out_{k}": v for k, v in perf(b, cost).items()}, **{f"l5_{k}": v for k, v in perf(l5, cost).items()},
                 **{f"l2_{k}": v for k, v in perf(l2, cost).items()}, **{f"tin_{k}": v for k, v in tin.items()}, **{f"tnow_{k}": v for k, v in tnow.items()})
        rows.append(r)
    D = pd.DataFrame(rows); D.to_csv("data/research/tb_universe.csv", index=False)
    print(f"R| instruments {len(D)}", flush=True)
    ok = D.dropna(subset=["in_pf", "out_pf", "tin_atr"])
    for k in ("in_pf", "in_cagr", "tin_atr", "tin_er", "tin_adx", "in_whip"):
        print(f"R| rank corr of {k} (2010-17) with 2018-26 PF {ok[k].corr(ok.out_pf, method='spearman'):+.2f} | with 2018-26 CAGR {ok[k].corr(ok.out_cagr, method='spearman'):+.2f}", flush=True)
    for k in ("in_pf", "tin_er", "tin_adx", "tin_atr"):
        q = pd.qcut(ok[k].rank(method="first"), 3, labels=["low", "mid", "high"])
        g = ok.groupby(q).agg(n=("sym", "size"), out_pf=("out_pf", "median"), out_cagr=("out_cagr", "median"), out_dd=("out_dd", "median"), share_pf_gt1=("out_pf", lambda v: round((v > 1).mean() * 100)))
        print(f"R| 2018-26 by 2010-17 tercile of {k}: " + " | ".join(f"{i}: n{r.n} PF {r.out_pf:.2f} CAGR {r.out_cagr:+.1f}% DD {r.out_dd:.1f}% PF>1 {r.share_pf_gt1}%" for i, r in g.iterrows()), flush=True)
    print(f"R| share of instruments with 2018-26 PF > 1: {(D.out_pf > 1).mean() * 100:.0f}% (median PF {D.out_pf.median():.2f}, median CAGR {D.out_cagr.median():+.1f}%)", flush=True)
    for _, r in D.sort_values("l5_cagr", ascending=False).iterrows():
        print(f"R| {r.sym:11s} {r.kind:5s} | 2010-17 PF {r.in_pf} {r.in_cagr:+.1f}% | 2018-26 PF {r.out_pf} {r.out_cagr:+.1f}% DD {r.out_dd}% | last 5y PF {r.l5_pf} {r.l5_cagr:+.1f}% DD {r.l5_dd}% | last 2y PF {r.l2_pf} {r.l2_cagr:+.1f}% | long PF {r.out_long_pf} | ATR {r.tnow_atr}% ER {r.tnow_er} ADX {r.tnow_adx} whip {r.out_whip}%", flush=True)


if __name__ == "__main__":
    main()
