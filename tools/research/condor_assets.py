"""'Pause after a big move' iron condor on commodities and liquid stocks / ETFs, 2010-2026 (21 Nov 2026, Amritpal: "suggest iron
condors in all liquid assets including commodities" -> "Yes" to testing first).

Same method as tools/research/condor_world.py (Black-Scholes priced, calibrated on Nifty's real option prices: IV scale k and a
per-trade cost), with three changes for single assets:
  1. Volatility-scaled rule. Nifty's tested rule (10-day move >= 3.5%, 3-day range < 2%, shorts 2.5% away, 1.5% wings) is scaled
     by f = the asset's median 1-year realised vol / Nifty's (about 14%). Natural gas (f ~ 4) needs a ~14% move and ~10% shorts;
     a quiet stock (f ~ 1.5) about 5% and 3.8%. A fixed-% version (f = 1) is reported too.
  2. Implied vol = the asset's own vol index where Yahoo has one (gold GVZ, oil OVX, silver VXSLV, Apple VXAPL, Amazon VXAZN,
     Google VXGOG, Goldman VXGS, IBM VXIBM), else 20-day realised vol x 1.15 (the median ratio seen on indices).
  3. Cost x2 (wider option spreads than index options); expiry: weekly Friday for US ETFs / futures / US stocks, monthly last
     Tuesday for NSE stocks and Bank Nifty (NSE has no weekly stock or Bank Nifty options).
Reports per asset: signal trades (n, per year, win %, avg % of spot, t, worst, return on capital at risk, years positive) for
2010-26 / 2019-26 / last 3 years, vs every expiry (3 days before). PILOT env = 3 assets from 2019.
Output data/research/condor_assets.json"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from condor_world import IDX as WIDX, REAL, get, bs  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
MOVE, PAUSE, SHORT, WING = 0.035, 2.0, 0.025, 0.015
SKEW = {"sc": 0.93, "lc": 0.90, "sp": 1.12, "lp": 1.20}
# key, yahoo, vol index (or None), expiry kind ('W' weekly Fri / 'M' monthly last Tue), group, where to trade
A = [("GOLD", "GC=F", "^GVZ", "W", "Commodity", "MCX GOLD (Angel) / GLD (moomoo)"),
     ("SILVER", "SI=F", "^VXSLV", "W", "Commodity", "MCX SILVER (Angel) / SLV (moomoo)"),
     ("CRUDE", "CL=F", "^OVX", "W", "Commodity", "MCX CRUDEOIL (Angel) / USO (moomoo)"),
     ("NATGAS", "NG=F", None, "W", "Commodity", "MCX NATURALGAS (Angel) / UNG (moomoo)"),
     ("COPPER", "HG=F", None, "W", "Commodity", "MCX COPPER (Angel)"),
     ("TLT", "TLT", None, "W", "US ETF", "moomoo"), ("EEM", "EEM", None, "W", "US ETF", "moomoo"), ("XLF", "XLF", None, "W", "US ETF", "moomoo"),
     ("AAPL", "AAPL", "^VXAPL", "W", "US stock", "moomoo"), ("MSFT", "MSFT", None, "W", "US stock", "moomoo"),
     ("NVDA", "NVDA", None, "W", "US stock", "moomoo"), ("AMZN", "AMZN", "^VXAZN", "W", "US stock", "moomoo"),
     ("GOOGL", "GOOGL", "^VXGOG", "W", "US stock", "moomoo"), ("META", "META", None, "W", "US stock", "moomoo"),
     ("TSLA", "TSLA", None, "W", "US stock", "moomoo"), ("JPM", "JPM", None, "W", "US stock", "moomoo"),
     ("BANKNIFTY", "^NSEBANK", None, "M", "India index", "NSE monthly (Angel)"),
     ("RELIANCE", "RELIANCE.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("HDFCBANK", "HDFCBANK.NS", None, "M", "India stock", "NSE F&O (Angel)"),
     ("ICICIBANK", "ICICIBANK.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("INFY", "INFY.NS", None, "M", "India stock", "NSE F&O (Angel)"),
     ("TCS", "TCS.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("SBIN", "SBIN.NS", None, "M", "India stock", "NSE F&O (Angel)"),
     ("AXISBANK", "AXISBANK.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("KOTAKBANK", "KOTAKBANK.NS", None, "M", "India stock", "NSE F&O (Angel)"),
     ("LT", "LT.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("BAJFINANCE", "BAJFINANCE.NS", None, "M", "India stock", "NSE F&O (Angel)"),
     ("ITC", "ITC.NS", None, "M", "India stock", "NSE F&O (Angel)"), ("BHARTIARTL", "BHARTIARTL.NS", None, "M", "India stock", "NSE F&O (Angel)")]
if PILOT:
    A = [a for a in A if a[0] in ("GOLD", "NATGAS", "RELIANCE")]


def expiries(idx, kind):
    s = pd.Series(idx, idx)
    if kind == "W":   # last trading day of each week on or before Friday
        g = s.groupby(idx.to_period("W-SUN")).apply(lambda x: x.iloc[-1])
    else:             # last trading day on or before the month's last Tuesday
        def lt(x):
            m = x.iloc[0]; last = (m + pd.offsets.MonthEnd(0)); tue = last - pd.Timedelta(days=(last.weekday() - 1) % 7)
            y = x[x <= tue]
            return y.iloc[-1] if len(y) else None
        g = s.groupby(idx.to_period("M")).apply(lt)
    return [pd.Timestamp(e) for e in g.dropna().values]


def price(s0, s1, v, T, cost, f):
    sh, wg = SHORT * f, WING * f
    K = {"sc": s0 * (1 + sh), "lc": s0 * (1 + sh + wg), "sp": s0 * (1 - sh), "lp": s0 * (1 - sh - wg)}
    p = {l: bs(s0, K[l], T, v * SKEW[l], l[1] == "c") for l in K}
    credit = p["sc"] - p["lc"] + p["sp"] - p["lp"]
    pay = max(s1 - K["sc"], 0) - max(s1 - K["lc"], 0) + max(K["sp"] - s1, 0) - max(K["lp"] - s1, 0)
    pnl = credit - pay - cost * s0
    return dict(credit=credit / s0 * 100, pnl=pnl / s0 * 100, roc=pnl / max(wg * s0 - credit, 1e-9) * 100)


def trades(h, iv, kind, k, cost, f):
    C, H, L = h.Close, h.High, h.Low; idx = h.index
    r10 = C / C.shift(10) - 1
    r3 = (H.rolling(3).max() - L.rolling(3).min()) / C * 100
    pos = {d: i for i, d in enumerate(idx)}
    out = []
    for e in expiries(idx, kind):
        ie = pos[e]
        for n in (4, 3, 2):
            if ie - n < 260:
                continue
            t0 = idx[ie - n]; v = iv.get(t0)
            if v is None or not np.isfinite(v) or v <= 0:
                continue
            sig = abs(r10.iloc[ie - n]) >= MOVE * f and r3.iloc[ie - n] < PAUSE * f
            out.append(dict(e=e, n=n, sig=bool(sig), **price(C.iloc[ie - n], C.iloc[ie], v * k / 100, n / 252, cost, f)))
    return pd.DataFrame(out)


def summ(d):
    if not len(d):
        return dict(n=0)
    yrs = max((d.e.max() - d.e.min()).days / 365.25, 1)
    x = d.pnl
    return dict(n=len(d), per_yr=round(len(d) / yrs, 1), win=round(float((x > 0).mean() * 100), 1), avg_pct=round(float(x.mean()), 4),
                t=round(float(x.mean() / (x.std() / math.sqrt(len(x)))), 2) if len(x) > 2 and x.std() > 0 else None,
                worst_pct=round(float(x.min()), 3), roc_avg=round(float(d.roc.mean()), 1), roc_worst=round(float(d.roc.min()), 1),
                years_pos=f"{int((d.groupby(d.e.dt.year).pnl.sum() > 0).sum())}/{d.e.dt.year.nunique()}")


def main():
    start0 = "2019-02-01" if PILOT else "2010-01-01"
    # calibration on Nifty (same as condor_world): IV scale k from all weeks' credit, cost from all weeks' P&L
    ni = [x for x in WIDX if x[0] == "NIFTY"][0]
    h = get(ni[1]); vi = get(ni[2]).Close.reindex(h.index).ffill()
    nrv = float((h.Close.pct_change().rolling(252).std() * math.sqrt(252) * 100).median())
    hh = h[h.index >= "2019-02-01"]
    best = None
    for k in np.arange(0.5, 1.61, 0.05):
        a = trades(hh, vi, "W", k, 0.0, 2.0 / 2.5)   # condor_world used 2% shorts / 1% wings: f maps 2.5 -> 2.0 for the calibration
        a = a[a.n == 3]
        if len(a):
            err = abs(a.credit.mean() - REAL["all_credit"])
            if best is None or err < best[0]:
                best = (err, k, a)
    _, k, a = best
    cost = max(0.0, (a.pnl.mean() - REAL["all_pnl"]) / 100)
    print(f"R| calibration k {k:.2f}, index cost {cost * 100:.4f}% of spot, Nifty median 1y realised vol {nrv:.1f}%", flush=True)
    res = dict(method=__doc__, calib=dict(k=round(float(k), 2), cost_pct=round(cost * 100, 4), nifty_rv=round(nrv, 1)), rows=[])
    for key, t, vt, kind, grp, where in A:
        try:
            h = get(t)
        except Exception as ex:  # noqa: BLE001
            print("R|", key, "no data", ex, flush=True); continue
        h = h[(h.Close > 0) & h.High.notna() & h.Low.notna()]
        rv20 = h.Close.pct_change().rolling(20).std() * math.sqrt(252) * 100
        src = "realised x1.15"; iv = rv20 * 1.15
        if vt:
            try:
                v = get(vt).Close.reindex(h.index).ffill()
                if v.notna().sum() > 500:
                    iv = v.where(v.notna(), rv20 * 1.15); src = "vol index " + vt
            except Exception:  # noqa: BLE001
                pass
        arv = float((h.Close.pct_change().rolling(252).std() * math.sqrt(252) * 100).median())
        f = arv / nrv
        row = dict(asset=key, group=grp, where=where, iv=src, vol=round(arv, 1), f=round(f, 2), expiry="weekly" if kind == "W" else "monthly")
        for lab, ff in (("scaled", f), ("fixed", 1.0)):
            T = trades(h, iv, kind, k, cost * 2, ff); T = T[T.e >= start0]
            if not len(T):
                continue
            sig = T[T.sig].sort_values("n", ascending=False).groupby("e").first().reset_index()
            end = T.e.max()
            row[lab] = {"2010-26": summ(sig), "2019-26": summ(sig[sig.e >= "2019-01-01"]), "last 3y": summ(sig[sig.e > end - pd.DateOffset(years=3)]),
                        "every expiry": summ(T[T.n == 3])}
        res["rows"].append(row)
        s = row.get("scaled", {})
        print(f"R| {key} ({grp}, vol {arv:.0f}%, f {f:.2f}, {src}) scaled: {s.get('2010-26')} | 2019-26 {s.get('2019-26')} | last3y {s.get('last 3y')} | every {s.get('every expiry')} | fixed: {row.get('fixed', {}).get('2010-26')}", flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/condor_assets.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
