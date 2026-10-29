"""Event study: monthly all-time-high breakouts by base length (how long since the ATH closing month), using Yahoo's
full weekly history (late 1990s ->). For each breakout: forward returns, whether/when it became a 2x/3x/5x/10x, and
what the weekly-30-SMA exit captured. Survivorship: Yahoo only has stocks still listed -> multibagger rates are
flattered; compare base-length buckets with each other rather than reading the levels literally.
Usage: python ath_base_study.py MARKET -> data/study/<MARKET>_events.csv
"""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import MARKETS, symbols  # noqa: E402

MINVAL = {"NSE": 1e7, "US": 2e6, "ASX": 5e5}       # avg daily traded value at the breakout


def events_for(sym, w, minval):
    w = w.dropna()
    w = w[(w.Close > 0) & (w.High > 0)]
    if len(w) < 150:
        return []
    c, h = w.Close.values, w.High.values
    val = (w.Close * w.Volume).rolling(20, min_periods=8).mean().values / 5      # ~ per-day traded value
    sma = w.Close.rolling(30, min_periods=30).mean().values
    sma50 = w.Close.rolling(50, min_periods=50).mean().values
    _m = w.index.to_period("M")
    monthend = pd.Series(_m).ne(pd.Series(_m).shift(-1)).values
    _mc = w.Close.groupby(_m).last()
    m10w = _mc.rolling(10, min_periods=10).mean().reindex(_m).values   # 10-month SMA of month-end closes (incl. current month)
    mon = w.index.to_period("M")
    mC = w.Close.groupby(mon).last(); mH = w.High.groupby(mon).max()
    best = mC.cummax(); isb = mC >= best
    trig_m = mH.where(isb).ffill().shift(1)
    k = pd.Series(np.arange(len(mC)), index=mC.index)
    ath_k = k.where(isb).ffill().shift(1)
    age_m = (k - ath_k)
    hist_m = ath_k                                    # months of data before the ATH month
    runmin = mC.groupby(isb.cumsum()).cummin()
    depth_m = runmin.shift(1) / best.shift(1) - 1
    # map to weeks
    trig = trig_m.reindex(mon).values; age = age_m.reindex(mon).values
    hist = hist_m.reindex(mon).values; depth = depth_m.reindex(mon).values
    out, done_month = [], set()
    n = len(w)
    for i in range(1, n):
        t = trig[i]
        if np.isnan(t) or h[i] <= t or mon[i] in done_month or np.isnan(hist[i]) or hist[i] < 12:
            continue
        done_month.add(mon[i])
        if np.isnan(val[i]) or val[i] < minval:
            continue
        entry = t                                       # stop-buy at the trigger (open gaps ignored on weekly data)
        above = bool(not np.isnan(sma[i - 1]) and c[i - 1] > sma[i - 1])
        e = dict(sym=sym, date=w.index[i].date(), entry=round(float(entry), 4), base_months=int(age[i]),
                 depth=round(float(depth[i]), 3) if not np.isnan(depth[i]) else None, value=float(val[i]),
                 above_sma=above, hist_months=int(hist[i]))
        for y in (1, 2, 3, 5):
            j = i + 52 * y
            e[f"r{y}y"] = round(c[j] / entry - 1, 3) if j < n else None
        fut = c[i:min(n, i + 52 * 5 + 1)]
        e["max5y"] = round(float(fut.max() / entry), 2)
        e["years_left"] = round((n - 1 - i) / 52, 1)
        for m in (2, 3, 5, 10):
            hit = np.flatnonzero(fut >= m * entry)
            e[f"wk_to_{m}x"] = int(hit[0]) if len(hit) else None
        # weekly 30-SMA exit: first weekly close below the SMA after entry week; sell next week's open ~ that close
        ex = None
        for j in range(i, n):
            if not np.isnan(sma[j]) and c[j] < sma[j]:
                ex = j
                break
        if ex is None:
            e.update(exit_ret=round(c[-1] / entry - 1, 3), held_wk=n - 1 - i, open=True,
                     max_in_trade=round(float(c[i:].max() / entry), 2))
        else:
            e.update(exit_ret=round(c[ex] / entry - 1, 3), held_wk=ex - i, open=False,
                     max_in_trade=round(float(c[i:ex + 1].max() / entry), 2))
        # looser exits: weekly close < 50-week SMA; monthly close < 10-month SMA; weekly close back > 15% below the old high
        for tag, lvl in (("sma50", sma50), ("m10", m10w), ("base15", None)):
            ex = None
            for j in range(i + 1, n):
                if tag == "base15":
                    if c[j] < 0.85 * entry:
                        ex = j; break
                elif tag == "m10":
                    if monthend[j] and not np.isnan(lvl[j]) and c[j] < lvl[j]:
                        ex = j; break
                elif not np.isnan(lvl[j]) and c[j] < lvl[j]:
                    ex = j; break
            j = ex if ex is not None else n - 1
            e[f"{tag}_ret"] = round(c[j] / entry - 1, 3)
            e[f"{tag}_wk"] = j - i
            e[f"{tag}_max"] = round(float(c[i:j + 1].max() / entry), 2)
        out.append(e)
    return out


def main():
    market = sys.argv[1]
    os.makedirs("data/study", exist_ok=True)
    u = symbols(market)
    tick = list(u.ticker); name = dict(zip(u.ticker, u.symbol))
    rows = []
    for a in range(0, len(tick), 100):
        chunk = tick[a:a + 100]
        d = None
        for _ in range(3):
            try:
                d = yf.download(chunk, period="max", interval="1wk", auto_adjust=True, progress=False,
                                group_by="column", threads=True)
                break
            except Exception as ex:  # noqa: BLE001
                print("retry", a, ex, flush=True); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in chunk:
            try:
                w = pd.DataFrame({k: d[k][t] for k in ("Open", "High", "Low", "Close", "Volume")})
                rows += events_for(name[t], w, MINVAL[market])
            except Exception:  # noqa: BLE001
                continue
        print(market, a + len(chunk), "stocks,", len(rows), "events", flush=True)
        time.sleep(2)
    ev = pd.DataFrame(rows)
    ev.to_csv(f"data/study/{market}_events.csv", index=False)
    print(ev.groupby(pd.cut(ev.base_months, [0, 6, 12, 24, 36, 60, 84, 120, 600])).agg(
        n=("sym", "size"), r1y=("r1y", "median"), r3y=("r3y", "median"), max5y=("max5y", "median"),
        x3=("max5y", lambda s: (s >= 3).mean()), sma_ret=("exit_ret", "median")).to_string())


if __name__ == "__main__":
    main()
