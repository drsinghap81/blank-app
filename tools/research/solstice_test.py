"""Do trends reverse near solstices / equinoxes (or new / full moons)? (25 Nov 2026, Amritpal: "does trend reverse on planetary action
like summer and winter solstice").
Indices: Nifty 50 (2007+), Sensex (1997+), S&P 500 (1950+), all Yahoo daily. Turning points = zigzag swing highs/lows on closes
(5% and 10% thresholds). Dates: solstices / equinoxes (20 Mar, 21 Jun, 22 Sep, 21 Dec) +-7 calendar days; new and full moon +-2 days
(synodic month 29.530589 days from the new moon of 6 Jan 2000 18:14 UTC). Compared with the share of all trading days that fall in the
same windows (what pure chance gives). Also the 20-session return after each solstice/equinox vs all days."""
import numpy as np
import pandas as pd
import yfinance as yf


def zig(c, thr):
    piv = []; d = 0; hi_i = lo_i = 0
    for i in range(1, len(c)):
        if c[i] > c[hi_i]: hi_i = i
        if c[i] < c[lo_i]: lo_i = i
        if d >= 0 and c[i] <= c[hi_i] * (1 - thr):
            piv.append(hi_i); d = -1; lo_i = i
        elif d <= 0 and c[i] >= c[lo_i] * (1 + thr):
            piv.append(lo_i); d = 1; hi_i = i
    return sorted(set(piv))


def near_season(d, w=7):
    y = d.year; S = [pd.Timestamp(y, 3, 20), pd.Timestamp(y, 6, 21), pd.Timestamp(y, 9, 22), pd.Timestamp(y, 12, 21), pd.Timestamp(y - 1, 12, 21), pd.Timestamp(y + 1, 3, 20)]
    return min(abs((d - s).days) for s in S) <= w


REF = pd.Timestamp("2000-01-06 18:14"); SYN = 29.530589


def moon_phase(d):
    return ((d - REF).total_seconds() / 86400 / SYN) % 1.0          # 0 = new, 0.5 = full


def near_moon(d, w=2):
    p = moon_phase(d) * SYN
    return min(p, SYN - p) <= w or abs(p - SYN / 2) <= w


for name, t, start in (("Nifty 50", "^NSEI", "2007-09-01"), ("Sensex", "^BSESN", "1997-07-01"), ("S&P 500", "^GSPC", "1950-01-01")):
    c = yf.download(t, start=start, progress=False, auto_adjust=True)["Close"].squeeze().dropna(); c.index = pd.to_datetime(c.index).tz_localize(None)
    D = c.index; cv = c.to_numpy(float)
    base_s = np.mean([near_season(d) for d in D]); base_m = np.mean([near_moon(d) for d in D])
    for thr in (0.05, 0.10):
        P = zig(cv, thr); pd_ = D[P]
        fs = np.mean([near_season(d) for d in pd_]); fm = np.mean([near_moon(d) for d in pd_])
        print(f"R| {name:8s} zigzag {int(thr * 100)}% | {len(P)} turning points | near solstice/equinox +-7d: {fs * 100:.1f}% (chance {base_s * 100:.1f}%) "
              f"| near new/full moon +-2d: {fm * 100:.1f}% (chance {base_m * 100:.1f}%)", flush=True)
    fwd = c.shift(-20) / c - 1
    for lab, (m, dd) in {"spring equinox 20 Mar": (3, 20), "summer solstice 21 Jun": (6, 21), "autumn equinox 22 Sep": (9, 22), "winter solstice 21 Dec": (12, 21)}.items():
        v = []
        for y in sorted(set(D.year)):
            i = D.searchsorted(pd.Timestamp(y, m, dd))
            if i < len(D) - 20:
                v.append(fwd.iloc[i])
        v = pd.Series(v).dropna()
        print(f"R| {name:8s} next 20 sessions after {lab:23s}: avg {v.mean() * 100:+.2f}% up {(v > 0).mean() * 100:.0f}% (n {len(v)}) | all days avg {fwd.mean() * 100:+.2f}% up {(fwd > 0).mean() * 100:.0f}%", flush=True)
