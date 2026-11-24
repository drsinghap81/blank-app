"""Hedging backtest (24 Nov 2026, Amritpal: "backtest hedging" after "how to hedge a 20 [lakh] portfolio fully").
Books (monthly, data/scan/alloc_curves.json, NSE 2017-26, costs in): 'mix' = Momentum 60 + Cup 9/21 40 (the stock book),
'mom' = Momentum alone, 'nifty' = a plain Nifty portfolio. Hedges added month by month (rebalanced each month-end, decided on
information at that month-end - no look-ahead):
  F100 / F50       short Nifty futures = 100% / 50% of the book: -Nifty return + carry (futures premium ~ 6.5% cash - 1.3% dividend
                   = 5.2%/yr earned by the short), 0.05% a month cost, margin 15% parked in liquid (not counted)
  F100 <200DMA     the same only when Nifty closed the month below its 200-day average (also <10-month SMA, <50DMA)
  PUT5             buy a 1-month Nifty put 5% out of the money for 100% of the book every month; PUT5 <200DMA conditional
  PS2/5            put spread: buy 2% OTM, sell 5% OTM (1-month); always / Nifty < 50DMA (the earlier weekly-test winner)
                   option prices: Black-Scholes on India VIX (+2 vol points skew for OTM puts), 0.5% of premium cost -
                   an approximation; the weekly test on real NSE option prices is in claude/conditional-put-spread-hedge.md
  GOLD20 / USD20 / GOLD10+USD10   20% of the book moved into GOLDBEES / US dollars (USDINR), rebalanced monthly
  TB               the app's Top Bottom 1 lot on top ('mix_tb' series)
Stats: CAGR, max drawdown (monthly), worst month, worst 12 months, Nifty's 10 worst months (book vs hedged), newest-first windows."""
import json
import math

import numpy as np
import pandas as pd
import yfinance as yf

A = {s["key"]: s for s in json.load(open("data/scan/alloc_curves.json"))["series"]}
def curve(k):
    s = A[k]; v = pd.Series(s["v"], index=pd.PeriodIndex(s["t"], freq="M")); v = pd.concat([pd.Series([100.0], index=[v.index[0] - 1]), v])
    return v.pct_change().dropna()


def yh(t):
    d = yf.download(t, start="2015-06-01", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None); return d


nif = yh("^NSEI"); vix = yh("^INDIAVIX"); gold = yh("GOLDBEES.NS"); usd = yh("INR=X")
me = nif.resample("ME").last(); P = me.index.to_period("M")
nret = pd.Series(me.pct_change().values, index=P)
s200 = nif.rolling(200).mean().resample("ME").last(); s50 = nif.rolling(50).mean().resample("ME").last(); m10 = me.rolling(10).mean()
below200 = pd.Series((me < s200).values, index=P).shift(1).fillna(False).astype(bool)      # decided at the previous month-end
below50 = pd.Series((me < s50).values, index=P).shift(1).fillna(False).astype(bool)
below10m = pd.Series((me < m10).values, index=P).shift(1).fillna(False).astype(bool)
iv = pd.Series(vix.resample("ME").last().values, index=vix.resample("ME").last().index.to_period("M")).shift(1)
low_m = pd.Series(nif.resample("ME").min().values, index=P)
gret = pd.Series(gold.resample("ME").last().pct_change().values, index=gold.resample("ME").last().index.to_period("M"))
uret = pd.Series(usd.resample("ME").last().pct_change().values, index=usd.resample("ME").last().index.to_period("M"))
CARRY = 0.052 / 12; FCOST = 0.0005; R_ = 0.065


def bs_put(S, K, T, vol, r=R_):
    if vol <= 0 or T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + vol * vol / 2) * T) / (vol * math.sqrt(T)); d2 = d1 - vol * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return K * math.exp(-r * T) * N(-d2) - S * N(-d1)


def put_ret(m, k_otm, short_otm=None):
    """return of the hedge per Rs 1 of book for month m: bought at the previous month-end, settled at this month-end"""
    i = me.index.get_indexer([m.to_timestamp("M")], method="nearest")[0]
    if i < 1:
        return 0.0
    S0, S1 = me.iloc[i - 1], me.iloc[i]; v = (iv.get(m, np.nan) or 15) / 100
    if not np.isfinite(v):
        v = 0.15
    K = S0 * (1 - k_otm); prem = bs_put(S0, K, 1 / 12, v + 0.02); pay = max(K - S1, 0.0)
    if short_otm:
        K2 = S0 * (1 - short_otm); prem -= bs_put(S0, K2, 1 / 12, v + 0.03); pay -= max(K2 - S1, 0.0)
    return (pay - prem * 1.005) / S0


def stats(r, lab, base=None):
    eq = (1 + r).cumprod(); yrs = len(r) / 12; cagr = eq.iloc[-1] ** (1 / yrs) - 1; dd = (eq / eq.cummax() - 1).min()
    r12 = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    w = {k: ((1 + r.iloc[-12 * k:]).prod() ** (1 / k) - 1) * 100 for k in (1, 3, 5)}
    worst = nret.reindex(r.index).nsmallest(10).index; crash = r.loc[worst].mean() * 100
    xc = r[~((r.index >= pd.Period("2020-02", "M")) & (r.index <= pd.Period("2020-12", "M")))]; xcagr = ((1 + xc).prod() ** (12 / len(xc)) - 1) * 100
    yr = ((1 + r).groupby(r.index.year).prod() - 1) * 100
    print(f"R| {lab:42s} | CAGR {cagr * 100:5.1f}% | max DD {dd * 100:6.1f}% | worst month {r.min() * 100:6.1f}% | worst 12m {r12.min() * 100:6.1f}% | "
          f"Nifty's 10 worst months avg {crash:+5.1f}% | 1y {w[1]:+.1f} 3y {w[3]:+.1f} 5y {w[5]:+.1f} | ex-Covid {xcagr:.1f}% | years "
          + " ".join(f"{y}:{v:+.0f}" for y, v in yr.sort_index(ascending=False).items()), flush=True)


for bk in ("mix", "mom", "nifty"):
    b = curve(bk); idx = b.index; n = nret.reindex(idx).fillna(0)
    print(f"R| ===== book: {A[bk]['name']} ({idx[0]} -> {idx[-1]}) =====", flush=True)
    fut = -n + CARRY - FCOST
    H = {"no hedge": b,
         "F100 short Nifty futures always": b + fut, "F50 half hedge always": b + 0.5 * fut,
         "F100 only when Nifty < 200DMA": b + fut * below200.reindex(idx).fillna(False),
         "F100 only when Nifty < 10-month SMA": b + fut * below10m.reindex(idx).fillna(False),
         "F100 only when Nifty < 50DMA": b + fut * below50.reindex(idx).fillna(False),
         "F50 only when Nifty < 200DMA": b + 0.5 * fut * below200.reindex(idx).fillna(False)}
    p5 = pd.Series([put_ret(m, 0.05) for m in idx], index=idx); ps = pd.Series([put_ret(m, 0.02, 0.05) for m in idx], index=idx)
    H.update({"PUT 5% OTM always": b + p5, "PUT 5% OTM when Nifty < 200DMA": b + p5 * below200.reindex(idx).fillna(False),
              "Put spread 2/5% always": b + ps, "Put spread 2/5% when Nifty < 50DMA": b + ps * below50.reindex(idx).fillna(False)})
    g = gret.reindex(idx).fillna(0); u = uret.reindex(idx).fillna(0)
    H.update({"20% in gold (GOLDBEES)": 0.8 * b + 0.2 * g, "20% in US dollars": 0.8 * b + 0.2 * (u + 0.0),
              "10% gold + 10% US dollars": 0.8 * b + 0.1 * g + 0.1 * u})
    if bk == "mix":
        H["+ Top Bottom 1 lot (app 'mix_tb')"] = curve("mix_tb").reindex(idx)
        H["+ Top Bottom + 10% gold + 10% USD"] = 0.8 * curve("mix_tb").reindex(idx) + 0.1 * g + 0.1 * u
        H["+ Top Bottom + put spread < 50DMA"] = curve("mix_tb").reindex(idx) + ps * below50.reindex(idx).fillna(False)
    for k, r in H.items():
        stats(r.dropna(), k)
print(f"R| Nifty < 200DMA in {below200.loc['2017-01':].mean() * 100:.0f}% of months; < 50DMA {below50.loc['2017-01':].mean() * 100:.0f}%", flush=True)
