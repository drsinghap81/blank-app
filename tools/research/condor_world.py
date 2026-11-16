"""'Pause after a big move' iron condor on 9 liquid indices, 2010-2026 (16 Nov 2026).

Only Nifty has real option prices (NSE bhavcopy test: claude/quiet-market-condor-test.md). Here every index is priced
with Black-Scholes from its own volatility index (or 20-day realised vol x the median IV/RV ratio when Yahoo has no
vol index), with a put/call skew. The model is calibrated on Nifty ALL weeks to the real-price result (average credit
0.131% of spot, average P&L -0.004% of spot per trade), then the signal is evaluated on every index.

Rule: |10-day move| >= 3.5% and last 3 days' high-low range < 2%; enter at the close of the first qualifying day 4, 3 or
2 trading days before the weekly expiry; short call/put 2% OTM, 1% wings, hold to expiry (settle at the close).
Result in % of spot and as return on capital at risk (wing - credit). Output: data/research/condor_world.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

IDX = [("NIFTY", "^NSEI", "^INDIAVIX", 3), ("SENSEX", "^BSESN", "^INDIAVIX", 3), ("SPX", "^GSPC", "^VIX", 4),
       ("NDX", "^NDX", "^VXN", 4), ("RUT", "^RUT", "^RVX", 4), ("SX5E", "^STOXX50E", "^V2TX", 4),
       ("DAX", "^GDAXI", "^VDAX", 4), ("N225", "^N225", "^JNIV", 4), ("HSI", "^HSI", "^VHSI", 4)]
REAL = dict(all_credit=0.131, all_pnl=-0.004, sig_credit=0.124, sig_pnl=0.0678, sig_win=89, sig_n=55)
SHORT, WING, MOVE, PAUSE = 0.02, 0.01, 0.035, 2.0
SKEW = {"sc": 0.93, "lc": 0.90, "sp": 1.12, "lp": 1.20}       # IV multiple by leg (2-3% OTM, short dated)


def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, call):
    if T <= 0 or v <= 0:
        return max(S - K, 0) if call else max(K - S, 0)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if call else K * N(-d2) - S * N(-d1)


def get(t):
    h = yf.download(t, start="2009-06-01", interval="1d", auto_adjust=False, progress=False)
    if hasattr(h.columns, "levels"):
        h.columns = h.columns.get_level_values(0)
    return h.dropna(subset=["Close"])


def trades(h, iv, wd, k, cost):
    C, H, L = h.Close.values, h.High.values, h.Low.values; idx = h.index
    r10 = pd.Series(C, idx) / pd.Series(C, idx).shift(10) - 1
    r3 = (pd.Series(H, idx).rolling(3).max() - pd.Series(L, idx).rolling(3).min()) / pd.Series(C, idx) * 100
    pos = {d: i for i, d in enumerate(idx)}
    # weekly expiries: last trading day of each week on or before weekday wd
    wk = pd.Series(idx, idx).groupby(idx.to_period("W-SUN")).apply(lambda s: [d for d in s if d.weekday() <= wd][-1] if any(d.weekday() <= wd for d in s) else None).dropna()
    out = []
    for e in wk.values:
        e = pd.Timestamp(e); ie = pos[e]
        for n in (4, 3, 2):
            if ie - n < 220:
                continue
            t0 = idx[ie - n]; s0 = C[ie - n]; v = iv.get(t0)
            if v is None or not np.isfinite(v):
                continue
            sig = abs(r10.iloc[ie - n]) >= MOVE and r3.iloc[ie - n] < PAUSE
            out.append(dict(e=e, n=n, sig=bool(sig), **price(s0, C[ie], v * k / 100, n / 252, cost)))
    return pd.DataFrame(out)


def price(s0, s1, v, T, cost):
    K = {"sc": s0 * (1 + SHORT), "lc": s0 * (1 + SHORT + WING), "sp": s0 * (1 - SHORT), "lp": s0 * (1 - SHORT - WING)}
    p = {l: bs(s0, K[l], T, v * SKEW[l], l[1] == "c") for l in K}
    credit = p["sc"] - p["lc"] + p["sp"] - p["lp"]
    pay = max(s1 - K["sc"], 0) - max(s1 - K["lc"], 0) + max(K["sp"] - s1, 0) - max(K["lp"] - s1, 0)
    pnl = credit - pay - cost * s0
    return dict(credit=credit / s0 * 100, pnl=pnl / s0 * 100, roc=pnl / (WING * s0 - credit) * 100, move=s1 / s0 - 1)


def summ(d):
    if not len(d):
        return {}
    yrs = (d.e.max() - d.e.min()).days / 365.25 or 1
    x = d.pnl
    return dict(n=len(d), per_yr=round(len(d) / yrs, 1), win=round((x > 0).mean() * 100, 1), avg_pct=round(x.mean(), 4),
                t=round(x.mean() / (x.std() / math.sqrt(len(x))), 2) if len(x) > 2 else None, worst_pct=round(x.min(), 3),
                credit_pct=round(d.credit.mean(), 4), roc_avg=round(d.roc.mean(), 1), roc_worst=round(d.roc.min(), 1),
                yr_pct=round(x.sum() / yrs, 3), years_pos=f"{int((d.groupby(d.e.dt.year).pnl.sum() > 0).sum())}/{d.e.dt.year.nunique()}")


def main():
    data = {}
    for key, t, vt, wd in IDX:
        h = get(t)
        try:
            v = get(vt).Close
        except Exception:  # noqa: BLE001
            v = pd.Series(dtype=float)
        rv = h.Close.pct_change().rolling(20).std() * math.sqrt(252) * 100
        src = "vol index"
        if len(v) < 500:
            v, src = rv * 1.15, "realised vol x1.15"
        data[key] = (h, v.reindex(h.index).ffill(), wd, src)
        print(key, len(h), src)
    # calibrate k and cost on Nifty ALL weeks (entry 3 days before expiry) against the real-price test
    h, v, wd, _ = data["NIFTY"]; h = h[h.index >= "2019-02-01"]; v = v.reindex(h.index)
    best = None
    for k in np.arange(0.5, 1.61, 0.05):
        base = trades(h, v, wd, k, 0.0); a = base[base.n == 3]
        if not len(a):
            continue
        err = abs(a.credit.mean() - REAL["all_credit"])
        if best is None or err < best[0]:
            best = (err, k, a)
    _, k, a = best
    cost = max(0.0, (a.pnl.mean() - REAL["all_pnl"]) / 100)       # per-trade cost in fraction of spot
    print("calibration k", round(k, 2), "cost % of spot", round(cost * 100, 4))
    res = dict(method=__doc__, calib=dict(k=round(float(k), 2), cost_pct_spot=round(cost * 100, 4), real=REAL), rows=[])
    for key, (h, v, wd, src) in data.items():
        for period, start in (("2010-26", "2010-01-01"), ("2019-26", "2019-02-01")):
            hh = h[h.index >= pd.Timestamp(start) - pd.Timedelta(days=400)]
            T = trades(hh, v.reindex(hh.index), wd, k, cost); T = T[T.e >= start]
            sig = T[T.sig].sort_values("n", ascending=False).groupby("e").first().reset_index()
            allw = T[T.n == 3]
            res["rows"].append(dict(index=key, iv_source=src, period=period, signal=summ(sig), all_weeks=summ(allw)))
            print(key, period, "signal", summ(sig), "| all", summ(allw))
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/condor_world.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
