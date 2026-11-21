"""Qullamaggie breakout with the REAL 60-minute entry and stop (21 Nov 2026, Amritpal: "check Qullamaggie then").

The daily test (tools/research/qullamaggie.py) bought at the pivot and used the whole day's low as the stop, so a trade could never be
stopped on its entry day (optimistic). Here, for the last ~2 years (Yahoo keeps ~730 days of 60-minute bars):
  setup   : exactly the daily setup, known at the previous close (ADR >= 4% / 3%, +30% impulse, SMA10/20 rising above SMA50, tight 3-15
            day base under the 20-day high)
  entry   : on the next session, the first 60-minute bar after the opening bar whose high breaks max(opening-range high, base pivot)
            + 0.1% -> fill at max(that bar's open, level). Volume: the session must close with volume >= 1.5x the 50-day average
            (variant "no volume rule" - the volume test can only be judged at the close)
  stop    : low of the day UP TO the entry (bars before the entry bar); skip if entry - stop > 1 x ADR; later 60-minute bars that day
            trading below it stop the trade out (at the stop)
  after   : daily bars - stop first, half at the day-3 close if above entry, rest on a close below SMA10 (variant SMA20), next open
Compared with the daily version on the same period and the same setups. Portfolio as before (Rs 20 L, 1% risk, 10 positions, 0.2% cost).
PILOT env = 200 stocks. Output data/research/qullamaggie_60m.json"""
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
from qullamaggie import download  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002


def setups(x, adr_min):
    """daily setup flags known at the close of day p (entry on p + 1): list of (p, pivot, adr)"""
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")); n = len(c)
    s10, s20, s50 = (pd.Series(c).rolling(k).mean().to_numpy() for k in (10, 20, 50))
    adr = pd.Series(h / l - 1).rolling(20).mean().to_numpy(); rng = h / l - 1
    v50 = pd.Series(v).rolling(50).mean().to_numpy(); val20 = pd.Series(c * v).rolling(20).mean().to_numpy()
    out = []
    for p in range(120, n - 1):
        if not (adr[p] >= adr_min and val20[p] >= 2e7 and c[p] >= 100 and c[p] > s10[p] and c[p] > s20[p] and s10[p] > s10[p - 5]
                and s20[p] > s20[p - 5] and s10[p] > s50[p] and s20[p] > s50[p]):
            continue
        k_hi = p - 19 + int(np.argmax(h[p - 19:p + 1])); nb = p - k_hi
        if not (3 <= nb <= 15):
            continue
        pk = int(np.argmax(c[p - 62:p + 1])) + p - 62
        if c[pk] / np.min(c[max(0, pk - 63):pk + 1]) - 1 < 0.30:
            continue
        pivot = h[k_hi]; base_lo = np.min(l[k_hi + 1:p + 1]); half = (nb + 1) // 2
        l1, l2 = l[k_hi + 1:k_hi + 1 + half], l[k_hi + 1 + half:p + 1]
        if (pivot / base_lo - 1 <= min(0.20, 2.5 * adr[p]) and (len(l2) == 0 or l2.min() >= l1.min()) and np.mean(v[k_hi + 1:p + 1]) < v50[p]
                and np.mean(rng[p - 2:p + 1]) < adr[p] and base_lo >= 0.97 * s20[p]):
            out.append((p, pivot, adr[p], v50[p]))
    return out


def follow(x, i, e, stop, exit_sma):
    """from the day after entry day i on daily bars: returns (exit_i, exit_px, half_px)"""
    o, l, c = (x[k].to_numpy(float) for k in ("Open", "Low", "Close")); n = len(c)
    sx = pd.Series(c).rolling(exit_sma).mean().to_numpy()
    half_px = None; k = i + 1
    while k < n:
        if l[k] <= stop:
            return k, min(o[k], stop), half_px
        if half_px is None and k == i + 3 and c[k] > e:
            half_px = c[k]
        if c[k] < sx[k] and k + 1 < n:
            return k + 1, o[k + 1], half_px
        k += 1
    return n - 1, c[-1], half_px


def main():
    tick = list(symbols("NSE").ticker)
    if PILOT:
        tick = tick[:200]
    D = download(tick)
    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=715)
    cand = {}
    for s, x in D.items():
        for amin in (0.03, 0.04):
            for p, pivot, adr, v50 in setups(x, amin):
                if x.index[p + 1] >= start:
                    cand.setdefault(s, {})[(p, amin)] = (pivot, adr, v50)
    syms = sorted(cand)
    print(f"R| daily data {len(D)} stocks; stocks with a setup in the 60-minute window: {len(syms)}; setups {sum(len(v) for v in cand.values())}", flush=True)
    H = {}
    for a in range(0, len(syms), 40):
        ch = [s + ".NS" for s in syms[a:a + 40]]
        for k in range(3):
            try:
                d = yf.download(ch, period="730d", interval="60m", progress=False, group_by="column", auto_adjust=False, threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20 * (k + 1)); d = None
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                y = pd.DataFrame({c: d[c][t] for c in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(y):
                y.index = pd.to_datetime(y.index).tz_convert("Asia/Kolkata").tz_localize(None); H[t[:-3]] = y
        time.sleep(2)
    print(f"R| 60-minute data for {len(H)} stocks, from {min(y.index[0] for y in H.values()).date() if H else None}", flush=True)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    res = dict(method=__doc__, runs={}); skips = {}
    for nm, amin, ex, volrule in (("60m, ADR >= 3%, SMA10 exit, volume rule", 0.03, 10, True), ("60m, ADR >= 4%, SMA10 exit, volume rule", 0.04, 10, True),
                                  ("60m, ADR >= 3%, SMA10 exit, no volume rule", 0.03, 10, False), ("60m, ADR >= 3%, SMA20 exit, volume rule", 0.03, 20, True)):
        T60, TD = [], []
        for s, cs in cand.items():
            x = D[s]; y = H.get(s); dts = x.index
            o, h, l, c, v = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
            busy60 = busyD = -1
            for (p, am), (pivot, adr, v50) in sorted(cs.items()):
                if am != amin:
                    continue
                i = p + 1
                vol_ok = v[i] >= 1.5 * v50
                # ---- daily version (as in qullamaggie.py) on the same setups, for comparison
                if i > busyD and h[i] >= pivot * 1.001 and vol_ok:
                    e = max(o[i], pivot * 1.001); st = l[i]
                    if e > st and (e - st) / e <= adr:
                        xi, xp, hp = follow(x, i, e, st, ex)
                        r_ = (0.5 * (hp / e - 1) + 0.5 * (xp / e - 1) if hp else xp / e - 1) - COST
                        TD.append(dict(sym=s, side=1, entry=dts[i], exit=dts[xi], e=e, risk=max((e - st) / e, 0.005), ret=r_, r_mult=r_ / max((e - st) / e, 0.005),
                                       half=hp is not None, days=xi - i, adx=float(v[i] / v50), open=xi == len(c) - 1)); busyD = xi
                # ---- 60-minute version
                if y is None or i <= busy60 or (volrule and not vol_ok):
                    skips["no data / busy / volume"] = skips.get("no data / busy / volume", 0) + 1; continue
                bars = y[y.index.normalize() == dts[i].normalize()]
                if len(bars) < 3:
                    skips["no 60m bars that day"] = skips.get("no 60m bars that day", 0) + 1; continue
                bo, bh, bl, bc = (bars[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
                lvl = max(bh[0], pivot) * 1.001; j = next((q for q in range(1, len(bars)) if bh[q] >= lvl), None)
                if j is None:
                    skips["no ORH / pivot break"] = skips.get("no ORH / pivot break", 0) + 1; continue
                e = max(bo[j], lvl); st = np.min(bl[:j])
                if e <= st or (e - st) / e > adr:
                    skips["LOD too far (> 1 ADR)"] = skips.get("LOD too far (> 1 ADR)", 0) + 1; continue
                if np.any(bl[j + 1:] <= st) or (bl[j] <= st):
                    xi, xp, hp = i, st, None                                   # stopped out the same day
                else:
                    xi, xp, hp = follow(x, i, e, st, ex)
                r_ = (0.5 * (hp / e - 1) + 0.5 * (xp / e - 1) if hp else xp / e - 1) - COST
                risk = max((e - st) / e, 0.005)
                T60.append(dict(sym=s, side=1, entry=dts[i], exit=dts[xi], e=e, risk=risk, ret=r_, r_mult=r_ / risk, half=hp is not None, days=xi - i,
                                adx=float(v[i] / v50), open=xi == len(c) - 1, same_day_stop=xi == i, hour=bars.index[j].hour))
                busy60 = xi
        for lbl, rows in (("60-MINUTE", T60), ("DAILY (same period)", TD)):
            T = pd.DataFrame(rows)
            if not len(T):
                print(f"R| {nm} | {lbl}: no trades", flush=True); continue
            C = {s: D[s].Close.to_dict() for s in T.sym.unique()}
            days = sorted(set().union(*[set(D[s].index[D[s].index >= T.entry.min()]) for s in T.sym.unique()]))
            eq = portfolio(T, C, days); rp = report(eq, bull); st_ = tstats(T)
            extra = f", stopped same day {T.same_day_stop.mean() * 100:.0f}%, entry hour {T.hour.value_counts().sort_index().to_dict()}" if "same_day_stop" in T else ""
            res["runs"][f"{nm} | {lbl}"] = dict(trades=st_, port={k: rp[k] for k in ("CAGR", "max DD", "1y", "2y", "years", "bull/bear a year")})
            print(f"R| {nm} | {lbl}: trades {st_}{extra}", flush=True)
            print(f"R| {nm} | {lbl}: portfolio CAGR {rp['CAGR']} maxDD {rp['max DD']} 1y {rp['1y']} 2y {rp['2y']} years {rp['years']} bull/bear {rp['bull/bear a year']}", flush=True)
    print("R| 60m skips (all variants):", skips, flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/qullamaggie_60m.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
