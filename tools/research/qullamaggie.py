"""Kristjan Kullamaegi (Qullamaggie) momentum breakout (21 Nov 2026, Amritpal pasted the rules). Daily version on NSE stocks 2016 -> today.

Setup (daily, known at the previous close):
  ADR%       = 20-day average of (high / low - 1) >= 4% (variant 3%)
  impulse    = within the last 63 sessions the close rose >= 30% from its lowest close of the 63 sessions before that peak
  alignment  = close > SMA10 and SMA20, both rising (vs 5 sessions ago) and both above SMA50
  base       = 3 to 15 sessions since the 20-day high (the pivot); pullback from the pivot <= 2.5 x ADR (and <= 20%); higher lows
               (lowest low of the base's second half >= first half's); base volume < 50-day average; last 3 days' average range below
               the ADR; base low stays above 97% of SMA20 ("surfing")
Entry: breakout day = high above the pivot + 0.1% with volume >= 1.5x the 50-day average; buy at max(open, pivot + 0.1%) - daily stand-in
       for the 60-minute opening-range-high break on a volume-expansion day (Yahoo has 60-minute bars for ~2 years only)
Stop:  that day's low (LOD); skip if entry - LOD > 1 x ADR. NOTE optimistic: daily bars can't show whether the low came after the entry
Exit:  sell half at the close of day 3 if it is above entry ("into strength"); the rest on the first close below SMA10 (fast) - variant
       SMA20 - sold at the next open; the stop protects both halves until then.
Portfolio: Rs 20 L, risk 1% (variant 0.5%) a trade, <= 20% of equity a stock, max 10 positions, 0.2% cost, biggest volume surge first.
Universe: NSE stocks from Yahoo (survivors), >= Rs 2 cr/day traded, close >= Rs 100. Reporting newest first, bull/bear, ex-Covid, by light.
PILOT env = 200 stocks. Output data/research/qullamaggie.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402
from holy_grail import portfolio, report, tstats  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002


def download(tick):
    out = {}
    for a in range(0, len(tick), 100):
        ch = tick[a:a + 100]
        for k in range(3):
            try:
                d = yf.download(ch, start="2015-06-01", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20 * (k + 1)); d = None
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({c: d[c][t] for c in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(x) > 250:
                x.index = pd.to_datetime(x.index).tz_localize(None); out[t.replace(".NS", "")] = x
        print("downloaded", a + len(ch), len(out), flush=True); time.sleep(2)
    return out


def trades_for(sym, x, adr_min, exit_sma):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")); n = len(c); dts = x.index
    s10, s20, s50 = (pd.Series(c).rolling(k).mean().to_numpy() for k in (10, 20, 50))
    sx = s10 if exit_sma == 10 else s20
    adr = pd.Series(h / l - 1).rolling(20).mean().to_numpy()
    rng = h / l - 1
    v50 = pd.Series(v).rolling(50).mean().to_numpy(); val20 = pd.Series(c * v).rolling(20).mean().to_numpy()
    out = []; i = 120; busy = -1
    while i < n - 1:
        if i <= busy:
            i += 1; continue
        p = i - 1                                    # setup known at the previous close
        if not (adr[p] >= adr_min and val20[p] >= 2e7 and c[p] >= 100 and c[p] > s10[p] and c[p] > s20[p] and s10[p] > s10[p - 5]
                and s20[p] > s20[p - 5] and s10[p] > s50[p] and s20[p] > s50[p]):
            i += 1; continue
        k_hi = p - 19 + int(np.argmax(h[p - 19:p + 1]))   # pivot = 20-day high
        nb = p - k_hi                                  # sessions of base after the pivot
        if not (3 <= nb <= 15):
            i += 1; continue
        pk = int(np.argmax(c[p - 62:p + 1])) + p - 62
        lo_before = np.min(c[max(0, pk - 63):pk + 1])
        if c[pk] / lo_before - 1 < 0.30:
            i += 1; continue
        pivot = h[k_hi]; base_lo = np.min(l[k_hi + 1:p + 1]); depth = pivot / base_lo - 1
        half = (nb + 1) // 2
        lows1, lows2 = l[k_hi + 1:k_hi + 1 + half], l[k_hi + 1 + half:p + 1]
        ok = (depth <= min(0.20, 2.5 * adr[p]) and (len(lows2) == 0 or lows2.min() >= lows1.min())
              and np.mean(v[k_hi + 1:p + 1]) < v50[p] and np.mean(rng[p - 2:p + 1]) < adr[p] and base_lo >= 0.97 * s20[p])
        if not ok:
            i += 1; continue
        trig = pivot * 1.001
        if not (h[i] >= trig and v[i] >= 1.5 * v50[p]):
            i += 1; continue
        e = max(o[i], trig); stop = l[i]
        if e <= stop or (e - stop) / e > adr[p]:
            i += 1; continue
        risk = (e - stop) / e
        half_px = None; exit_px = None; exit_i = None; k = i + 1
        while k < n:
            if l[k] <= stop:
                exit_px, exit_i = min(o[k], stop), k; break
            if half_px is None and k == i + 3 and c[k] > e:
                half_px = c[k]
            if c[k] < sx[k] and k + 1 < n:
                exit_px, exit_i = o[k + 1], k + 1; break
            k += 1
        if exit_px is None:
            exit_px, exit_i = c[-1], n - 1
        u = lambda px: px / e - 1  # noqa: E731
        ret = (0.5 * u(half_px) + 0.5 * u(exit_px) if half_px is not None else u(exit_px)) - COST
        out.append(dict(sym=sym, side=1, entry=dts[i], exit=dts[exit_i], e=e, risk=risk, ret=ret, r_mult=ret / risk, half=half_px is not None,
                        days=exit_i - i, adx=float(v[i] / v50[p]), adr=float(adr[p]), open=exit_i == n - 1))
        busy = exit_i; i = exit_i + 1
    return out


def main():
    u = symbols("NSE")
    tick = list(u.ticker)
    if PILOT:
        tick = tick[:200]
    D = download(tick)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    C = {s: x.Close.to_dict() for s, x in D.items()}
    days = sorted(set().union(*[set(x.index[x.index >= "2016-06-01"]) for x in D.values()]))
    try:
        import light_distribution as LD
        from trend_bt_global import load
        d, _ = load("NSE") if not PILOT else (None, None)
        L = LD.light_series(d) if d is not None else None
    except Exception as e:  # noqa: BLE001
        print("light unavailable", e); L = None
    print("R| stocks", len(D), flush=True)
    res = dict(method=__doc__, runs={})
    for nm, adr_min, ex, rk in (("as given: ADR >= 4%, exit below SMA10, 1% risk", 0.04, 10, 0.01), ("ADR >= 4%, exit below SMA20", 0.04, 20, 0.01),
                                ("ADR >= 3%, exit below SMA10", 0.03, 10, 0.01), ("ADR >= 3%, exit below SMA20", 0.03, 20, 0.01),
                                ("as given at 0.5% risk", 0.04, 10, 0.005)):
        rows = []
        for s, x in D.items():
            rows += trades_for(s, x, adr_min, ex)
        T = pd.DataFrame(rows)
        if not len(T):
            print("R|", nm, "no trades", flush=True); continue
        T = T[T.entry >= "2016-06-01"]
        st = tstats(T); eq = portfolio(T, C, days, risk=rk); rp = report(eq, bull)
        res["runs"][nm] = dict(trades=st, port=rp)
        print(f"R| {nm} | trades {st} | median ADR {T.adr.median() * 100:.1f}% | gain >= 20%: {(T.ret >= 0.2).mean() * 100:.0f}%", flush=True)
        print(f"R| {nm} | portfolio {rp}", flush=True)
        end = T.entry.max()
        print(f"R| {nm} | trades newest first", {f"last {y}y": tstats(T[T.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)}, flush=True)
        if L is not None and nm.startswith("as given:"):
            T = T.assign(light=[L.iloc[max(0, L.index.searchsorted(pd.Timestamp(t)) - 1)] for t in T.entry])
            print(f"R| {nm} | by light", {lt: tstats(T[T.light == lt]) for lt in ("GREEN", "AMBER", "RED")}, flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/qullamaggie.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
