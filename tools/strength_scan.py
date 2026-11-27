"""Strength scan (28 Nov 2026, Amritpal: "go with the website features but use slightly different names") - NSE, after the close.
Ideas checked on getmarketstrength.com and backtested on our data (claude/market-strength-website-scans-test.md); our own code and names:
  Strength score 1-99 : rank of 0.4 x 3-month + 0.2 x 6m + 0.2 x 9m + 0.2 x 12m return across liquid stocks (9/12m fall back to 6m)
  Uptrend health 0-8  : price above the 150 & 200-day; 150 > 200; 200-day rising (21 sessions); 50 > 150 & 200; price above the 50;
                        >= 30% above the 52-week low; within 25% of the 52-week high; Strength score >= 70
  Phase 1-4           : 150-day average based (1 Basing, 2 Rising, 3 Topping, 4 Falling); a new phase counts after 5 sessions in a row
  vs-Nifty new high   : the stock / Nifty line at a 52-week high
  Market breadth      : % of liquid stocks above their 50 / 200-day, 52-week closing highs / lows, up / down on the day
Watch lists (WATCH ONLY, with a forward record; exits as tested: 3 x ATR(14) trailing close stop or 40 sessions, 0.5% cost):
  Healthy uptrend leaders : Uptrend health turns 8/8 with Strength >= 80 (tested 2021+: +26.9%/yr, worst fall -33%, Nifty gate)
  Tight range breakout    : Strength >= 70, above a rising 50 & 200-day, within 15% of the 52-week closing high, the last 20 days' range
                            <= 15%, a close above that range on >= 1.5x the 50-day volume, day <= +12% (2021+: +21.2%/yr, -26%)
  Both bought at the next close in the test, only while Nifty closes above its 50-day average.
Output data/scan/strength.json (+ strength_log.json). Liquid = 20-day traded value >= Rs 2 cr and price >= 50 (the app's floor)."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "research"))
import flag_volume as FV  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "scan", "strength.json"); LOG = os.path.join(ROOT, "data", "scan", "strength_log.json")
COST = 0.005


def phase_raw(c, s150):
    """Weinstein-style phase each day from the 150-day average (1 basing, 2 rising, 3 topping, 4 falling)."""
    s20 = s150.shift(20); s120 = s150.shift(120); ch = s150 / s20 - 1
    up, dn = ch > 0.01, ch < -0.01; flat = ~up & ~dn; d = c / s150 - 1
    ph = pd.Series(np.nan, index=c.index)
    ph[up & (d >= -0.05)] = 2
    ph[(up & (d < -0.05) & (d >= -0.15)) | (flat & (s150 > s120) & (d >= -0.10))] = 3
    ph[(dn & (d < 0)) | ((~up) & (d < -0.10)) | (up & (d < -0.15))] = 4
    ph[(dn & (d >= 0)) | (flat & (s150 <= s120) & (d >= -0.10))] = 1
    return ph


def held_phase(ph):
    """the latest phase that held 5 sessions in a row"""
    v = ph.dropna().to_numpy()
    for k in range(len(v) - 5, -1, -1):
        if (v[k:k + 5] == v[k]).all():
            return int(v[k])
    return None


def chand_exit(x, j, A):
    """entry at day j's close; exit next close after a close < highest close - 3 ATR, or 40 sessions. -> (k, px) or None if open."""
    c = x.CLOSE.to_numpy(float); n = len(c); hc = c[j]
    for k in range(j + 1, n):
        hc = max(hc, c[k])
        if c[k] < hc - 3 * A[k]:
            return (k + 1, c[k + 1]) if k + 1 < n else None
        if k - j >= 40:
            return k, c[k]
    return None


def main():
    P = FV.load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    C = pd.DataFrame({s: x.CLOSE for s, x in P.items()}).sort_index()
    V = pd.DataFrame({s: x.VOL for s, x in P.items()}).reindex(C.index)
    C = C.iloc[-400:]; V = V.iloc[-400:]
    liq = ((C * V).rolling(20).mean() >= 2e7) & (C >= 50)
    W = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1).fillna(C / C.shift(126) - 1) \
        + 0.2 * (C / C.shift(252) - 1).fillna(C / C.shift(126) - 1)
    RS = (W.where(liq).rank(axis=1, pct=True) * 98 + 1).round()
    s50, s150, s200 = C.rolling(50).mean(), C.rolling(150).mean(), C.rolling(200).mean()
    hi52, lo52 = C.rolling(250, min_periods=120).max(), C.rolling(250, min_periods=120).min()
    H = (((C > s150) & (C > s200)).astype(int) + (s150 > s200) + (s200 > s200.shift(21)) + ((s50 > s150) & (s50 > s200)) + (C > s50)
         + (C >= lo52 * 1.3) + (C >= hi52 * 0.75) + (RS >= 70))
    N = nif.reindex(C.index).ffill(); rsl = C.div(N, axis=0); rslhi = rsl >= rsl.rolling(250, min_periods=120).max()
    gate = bool(N.iloc[-1] > N.rolling(50).mean().iloc[-1])
    d0 = C.index[-1]; L = liq.iloc[-1]; syms = [s for s in C.columns if L.get(s, False)]
    cl, pc = C.iloc[-1], C.iloc[-2]
    breadth = dict(n=len(syms), above50=round(float((cl[syms] > s50.iloc[-1][syms]).mean()) * 100, 1),
                   above200=round(float((cl[syms] > s200.iloc[-1][syms]).mean()) * 100, 1),
                   highs=int((cl[syms] >= hi52.iloc[-1][syms]).sum()), lows=int((cl[syms] <= lo52.iloc[-1][syms]).sum()),
                   up=int((cl[syms] > pc[syms]).sum()), down=int((cl[syms] < pc[syms]).sum()),
                   above50_month_ago=round(float((C.iloc[-22][syms] > s50.iloc[-22][syms]).mean()) * 100, 1))
    S = {}
    for s in syms:
        ph = held_phase(phase_raw(C[s].iloc[-80:], s150[s].iloc[-80:]))
        r = RS.at[d0, s]
        S[s] = [None if pd.isna(r) else int(r), int(H.at[d0, s]), ph, int(bool(rslhi.at[d0, s])),
                None if pd.isna(RS[s].iloc[-22]) else int(RS[s].iloc[-22])]
    # ---- watch lists (signals of the last 3 sessions)
    rows = []
    for s in syms:
        x = P[s].iloc[-400:]; c = x.CLOSE.to_numpy(float); h = x.HIGH.to_numpy(float); l = x.LOW.to_numpy(float); v = x.VOL.to_numpy(float)
        if len(c) < 260:
            continue
        pcl = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pcl), abs(l - pcl))); A = pd.Series(tr).rolling(14).mean().to_numpy()
        v50 = pd.Series(v).rolling(50).mean().to_numpy(); n = len(c)
        Hs = H[s].reindex(x.index).to_numpy(); Rs = RS[s].reindex(x.index).to_numpy()
        S50 = s50[s].reindex(x.index).to_numpy(); S200 = s200[s].reindex(x.index).to_numpy(); HC = hi52[s].reindex(x.index).to_numpy()
        for t in range(n - 3, n):
            base = dict(symbol=s, day=str(x.index[t].date()), close=round(float(c[t]), 2), strength=None if np.isnan(Rs[t]) else int(Rs[t]),
                        stop=round(float(c[t] - 3 * A[t]), 2), age=n - 1 - t)
            if Rs[t] >= 80 and Hs[t] == 8 and Hs[t - 1] < 8:
                rows.append(dict(base, list="leaders", why=f"uptrend health turned 8/8, strength {int(Rs[t])}"))
            hN, lN = h[t - 20:t].max(), l[t - 20:t].min()
            if (Rs[t] >= 70 and c[t] > S50[t] > 0 and c[t] > S200[t] and S50[t] > S50[t - 5] and S200[t] > S200[t - 5] and c[t] >= HC[t] * 0.85
                    and hN / lN - 1 <= 0.15 and c[t] > hN and v[t] >= 1.5 * v50[t] and c[t] / c[t - 1] - 1 <= 0.12):
                rows.append(dict(base, list="tight", why=f"closed above a {(hN / lN - 1) * 100:.0f}% 20-day range on {v[t] / v50[t]:.1f}x volume",
                                 range_top=round(float(hN), 2), range_low=round(float(lN), 2), vol_x=round(float(v[t] / v50[t]), 1)))
    rows.sort(key=lambda r: (r["list"], r["age"], -(r["strength"] or 0)))
    # ---- forward record: entry at the next close after the signal, exit 3 x ATR trail / 40 sessions
    try:
        log = json.load(open(LOG))
    except Exception:  # noqa: BLE001
        log = []
    seen = {(r["symbol"], r["list"], r["day"]) for r in log}
    for r in rows:
        if (r["symbol"], r["list"], r["day"]) not in seen:
            log.append(dict(symbol=r["symbol"], list=r["list"], day=r["day"], gate=gate, result="waiting"))
    for r in log:
        if r.get("result") not in ("waiting", "open"):
            continue
        x = P.get(r["symbol"])
        if x is None:
            continue
        D = [str(d.date()) for d in x.index]
        if r["day"] not in D:
            continue
        b = D.index(r["day"]); j = b + 1
        if j >= len(D):
            continue
        c = x.CLOSE.to_numpy(float); h = x.HIGH.to_numpy(float); l = x.LOW.to_numpy(float)
        pcl = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pcl), abs(l - pcl)))).rolling(14).mean().to_numpy()
        e = c[j]; r.update(entry_day=D[j], entry=round(float(e), 2)); ex = chand_exit(x, j, A)
        if ex is None:
            r.update(result="open", now_pct=round(float((c[-1] / e - 1 - COST) * 100), 2))
        else:
            k, px = ex; r.update(result="closed", exit_day=D[min(k, len(D) - 1)], exit=round(float(px), 2), ret_pct=round(float((px / e - 1 - COST) * 100), 2))
    rec = {}
    for nm in ("leaders", "tight"):
        z = [r for r in log if r["list"] == nm and r.get("ret_pct") is not None]
        rec[nm] = dict(n=sum(1 for r in log if r["list"] == nm), closed=len(z), won=sum(1 for r in z if r["ret_pct"] > 0),
                       avg_pct=round(float(np.mean([r["ret_pct"] for r in z])), 2) if z else None)
    wk = nif.resample("W-FRI").last().iloc[-62:]
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=str(d0.date()), gate=gate, breadth=breadth,
               keys=["strength", "health", "phase", "vs_nifty_high", "strength_month_ago"], s=S,
               nifty_w=dict(t=[str(d.date()) for d in wk.index], c=[round(float(v), 2) for v in wk]), rows=rows, record=rec,
               note="Watch only. Tested 2021+: Healthy uptrend leaders +26.9%/yr (worst fall -33%), Tight range breakout +21.2%/yr (-26%); Nifty 11.0%/yr (-17%).")
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    json.dump(log, open(LOG, "w"), indent=0)
    print("R| liquid", len(syms), "breadth", breadth, "rows", {k: sum(r["list"] == k for r in rows) for k in ("leaders", "tight")}, "record", rec, flush=True)


if __name__ == "__main__":
    main()
