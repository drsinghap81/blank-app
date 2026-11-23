"""Smooth equity curve: a diversified Top Bottom book (24 Nov 2026, Amritpal: "I want a smooth linearly rising equity curve").
Sleeves (live engine, buffer 0.05%): Bank Nifty both sides (live bot), Nifty buy-only, buy-only India stocks that passed the screen
(TMPV, BEL, LT, TCS from bhavcopy futures; DLF from NSE cash), buy-only US ETFs (QQQ, SMH, XLF, XLE, XLK) and metals (SLV, GLD).
Each sleeve's DAILY return = held position marked to the close (entry price -> close on day 1, close -> exit price on the last day),
minus 0.05% (index/ETF) or 0.1% (stocks) per round trip on the exit day. Returns in local currency (no FX).
Books, rebalanced monthly: (A) Bank Nifty alone; (B) equal weight all sleeves; (C) inverse-volatility weights (trailing 120-day vol);
(D) C scaled to 12% annual volatility (leverage capped at 2x). Smoothness: R^2 of log-equity vs time (1 = a straight line), % up
months, worst month, max drawdown, longest time under water. Newest-first windows. 2011 -> today."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
import topbottom_backtest as tbb  # noqa: E402

IDX = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0); STK = dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)


def daily(x, p, cost):
    t = tbb.run_live(x, p); c = x.Close; r = pd.Series(0.0, index=x.index)
    for _, tr in t.iterrows():
        e, xd = pd.Timestamp(tr.EntryDate), pd.Timestamp(tr.ExitDate); sgn = 1 if tr.Side == "BUY" else -1
        days = c.loc[e:xd].index
        if len(days) == 0:
            continue
        prev = tr.Entry
        for i, d in enumerate(days):
            px = tr.Exit if (d == xd and not tr.get("Open", False)) else c.loc[d]
            r.loc[d] += sgn * (px / prev - 1); prev = px
        if not tr.get("Open", False):
            r.loc[xd] -= cost
    return r


def fut(sym):
    x = pd.read_csv(f"data/futures/{sym}.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]].dropna()
    return x[(x.High >= x.Low) & (x.index >= "2010-01-01")]


def yh(t):
    d = yf.download(t, start="2009-06-01", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); return x[(x.High >= x.Low) & (x.index >= "2010-01-01")]


S = {}
S["BANKNIFTY both"] = daily(fut("BANKNIFTY"), tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **IDX), 0.0005)
S["NIFTY buy"] = daily(fut("NIFTY"), tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **IDX), 0.0005)
for s in ("TMPV", "BEL", "LT", "TCS"):
    if os.path.exists(f"data/futures/{s}.csv"):
        S[f"{s} buy"] = daily(fut(s), tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **STK), 0.001)
S["DLF buy"] = daily(yh("DLF.NS"), tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **STK), 0.001)
for s in ("QQQ", "SMH", "XLF", "XLE", "XLK", "SLV", "GLD"):
    try:
        S[f"{s} buy"] = daily(yh(s), tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **IDX), 0.0005)
    except Exception as ex:  # noqa: BLE001
        print("skip", s, ex)
R = pd.DataFrame(S).sort_index()
R.index = pd.to_datetime(R.index); R = R[R.index >= "2011-01-01"].fillna(0.0)
# align different market calendars: aggregate to business days (a non-trading day for one market = 0)
R = R.groupby(R.index.normalize()).sum()
print("R| sleeves", list(R.columns), "days", len(R), R.index[0].date(), "->", R.index[-1].date(), flush=True)
print("R| sleeve corr (median pairwise)", round(float(np.nanmedian(R.corr().values[np.triu_indices(R.shape[1], 1)])), 2), flush=True)

months = R.index.to_period("M")
def book(w_fn, target=None):
    out = pd.Series(0.0, index=R.index); w = None
    for m in sorted(set(months)):
        idx = R.index[months == m]; hist = R[R.index < idx[0]].iloc[-120:]
        w = w_fn(hist)
        if target and len(hist) > 60:
            pv = (hist @ w).std() * np.sqrt(252)
            if pv > 0:
                w = w * min(2.0, target / pv)
        out.loc[idx] = R.loc[idx] @ w
    return out
eq_w = lambda h: pd.Series(1.0 / R.shape[1], index=R.columns)  # noqa: E731
def iv(h):
    v = h.std().replace(0, np.nan)
    if len(h) < 60 or v.isna().all():
        return eq_w(h)
    w = (1 / v).fillna(0); return w / w.sum()
B = {"A Bank Nifty alone": R["BANKNIFTY both"], "B equal weight (all sleeves)": book(eq_w), "C inverse-volatility": book(iv), "D inverse-vol, 12% vol target (max 2x)": book(iv, 0.12)}
for k in R.columns:
    pass
def stats(r):
    eq = (1 + r).cumprod(); yrs = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; dd = (eq / eq.cummax() - 1)
    y = np.log(eq.values); x = np.arange(len(y)); r2 = np.corrcoef(x, y)[0, 1] ** 2
    m = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    uw = (dd < 0).astype(int); runs = uw.groupby((uw == 0).cumsum()).sum().max()
    vol = r.std() * np.sqrt(252); sharpe = (r.mean() * 252) / vol if vol else 0
    win = {}
    for k in (1, 2, 3, 5):
        x_ = r[r.index > r.index[-1] - pd.DateOffset(years=k)]; win[k] = ((1 + x_).prod() ** (1 / k) - 1) * 100
    yr = ((1 + r).groupby(r.index.year).prod() - 1) * 100
    return f"CAGR {cagr * 100:5.1f}% | max DD {dd.min() * 100:5.1f}% | straightness R2 {r2:.3f} | up months {(m > 0).mean() * 100:3.0f}% | worst month {m.min() * 100:5.1f}% | longest under water {runs} days | vol {vol * 100:4.1f}% Sharpe {sharpe:.2f} | 1y {win[1]:+.1f} 2y {win[2]:+.1f} 3y {win[3]:+.1f} 5y {win[5]:+.1f}", yr
for k, r in B.items():
    s, yr = stats(r); print(f"R| {k:40s} | {s}", flush=True)
    print(f"R| {k:40s} | years " + " ".join(f"{y}:{v:+.0f}" for y, v in yr.sort_index(ascending=False).items()), flush=True)
for c in R.columns:
    s, _ = stats(R[c]); print(f"R| sleeve {c:16s} | {s}", flush=True)
