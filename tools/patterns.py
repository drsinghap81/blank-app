"""Candlestick patterns + chart confluences (from the "Candlestick Pattern – Chart Examples" deck).

detect(df) -> DataFrame, one row per pattern occurrence (all bars), with
    Pattern, Side (+1 bullish / -1 bearish), Bar (index position), Low/High of the pattern
    (stop reference) and one boolean column per confluence.

Shared by the Streamlit scanner and tools/pattern_backtest.py so the live scan and the
backtest use exactly the same definitions. Daily (or weekly) OHLCV with columns
Open, High, Low, Close, Volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PATTERNS = ["Big green candle", "Big red candle", "Hammer", "Shooting star", "Doji (bullish)", "Doji (bearish)",
            "Bullish engulfing", "Bearish engulfing", "Bullish harami", "Bearish harami",
            "Morning star", "Evening star", "Abandoned baby (bullish)", "Abandoned baby (bearish)"]

CONFLUENCES = ["MA44", "MA200", "MA20", "Fib50", "Fib618", "Support/Resistance", "Gap zone", "Trap",
               "RSI 40/60", "RSI extreme", "Volume spike", "Trend"]

NEAR = 0.015          # "at" a level = within 1.5%


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def indicators(df: pd.DataFrame) -> dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float) if "Volume" in df else np.full(len(c), np.nan)
    cs = df["Close"]
    body = np.abs(c - o)
    rng = np.maximum(h - l, 1e-9)
    ind = dict(o=o, h=h, l=l, c=c, v=v, body=body, rng=rng,
               up=h - np.maximum(o, c), lo=np.minimum(o, c) - l,
               avgbody=pd.Series(body).rolling(20, min_periods=10).mean().to_numpy(),
               avgvol=pd.Series(v).rolling(20, min_periods=10).mean().shift(1).to_numpy(),
               ma20=cs.rolling(20).mean().to_numpy(), ma44=cs.rolling(44).mean().to_numpy(),
               ma200=cs.rolling(200).mean().to_numpy(), rsi=_rsi(cs).to_numpy())
    # prior trend: 5-bar change
    ind["chg5"] = c / pd.Series(c).shift(5).to_numpy() - 1
    return ind


# ---------------------------------------------------------------------------- patterns
def _pattern_masks(I: dict) -> dict[str, tuple[np.ndarray, int, int]]:
    """name -> (bool mask at the LAST bar of the pattern, side, n_bars)"""
    o, h, l, c, body, rng, up, lo, ab = (I[k] for k in ("o", "h", "l", "c", "body", "rng", "up", "lo", "avgbody"))
    sh = lambda a, k=1: np.concatenate([np.full(k, np.nan), a[:-k]])  # noqa: E731
    green, red = c > o, c < o
    down, upt = I["chg5"] < -0.02, I["chg5"] > 0.02
    big = body > 2.0 * sh(ab)
    small = body < 0.5 * ab
    doji = body <= 0.1 * rng
    o1, h1, l1, c1, b1 = sh(o), sh(h), sh(l), sh(c), sh(body)
    o2, h2, l2, c2, b2 = sh(o, 2), sh(h, 2), sh(l, 2), sh(c, 2), sh(body, 2)
    ab1 = sh(ab)
    m = {}
    m["Big green candle"] = (green & big & (c - l >= 0.75 * rng), 1, 1)
    m["Big red candle"] = (red & big & (h - c >= 0.75 * rng), -1, 1)
    m["Hammer"] = ((lo >= 2 * body) & (up <= np.maximum(body, 0.1 * rng)) & (lo >= 0.55 * rng) & down, 1, 1)
    m["Shooting star"] = ((up >= 2 * body) & (lo <= np.maximum(body, 0.1 * rng)) & (up >= 0.55 * rng) & upt, -1, 1)
    m["Doji (bullish)"] = (doji & down, 1, 1)
    m["Doji (bearish)"] = (doji & upt, -1, 1)
    prev_red, prev_green = c1 < o1, c1 > o1
    m["Bullish engulfing"] = (green & prev_red & (c >= o1) & (o <= c1) & (body > b1) & sh(down.astype(float)).astype(bool), 1, 2)
    m["Bearish engulfing"] = (red & prev_green & (c <= o1) & (o >= c1) & (body > b1) & sh(upt.astype(float)).astype(bool), -1, 2)
    inside_body = (np.maximum(o, c) <= np.maximum(o1, c1)) & (np.minimum(o, c) >= np.minimum(o1, c1))
    m["Bullish harami"] = (prev_red & (b1 > ab1) & inside_body & (body < 0.5 * b1), 1, 2)
    m["Bearish harami"] = (prev_green & (b1 > ab1) & inside_body & (body < 0.5 * b1), -1, 2)
    first_red_big, first_green_big = (c2 < o2) & (b2 > sh(ab, 2)), (c2 > o2) & (b2 > sh(ab, 2))
    star_small = b1 < 0.5 * b2
    m["Morning star"] = (first_red_big & star_small & (np.maximum(o1, c1) <= c2 + 0.1 * b2) & green & (c > (o2 + c2) / 2), 1, 3)
    m["Evening star"] = (first_green_big & star_small & (np.minimum(o1, c1) >= c2 - 0.1 * b2) & red & (c < (o2 + c2) / 2), -1, 3)
    doji1 = b1 <= 0.1 * (h1 - l1 + 1e-9)
    m["Abandoned baby (bullish)"] = ((c2 < o2) & doji1 & (h1 < l2) & green & (l > h1), 1, 3)
    m["Abandoned baby (bearish)"] = ((c2 > o2) & doji1 & (l1 > h2) & red & (h < l1), -1, 3)
    return {k: (np.nan_to_num(v[0].astype(float)).astype(bool), v[1], v[2]) for k, v in m.items()}


# ---------------------------------------------------------------------------- confluences (causal)
def _pivots(h, l, k=3):
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(k, n - k):
        if h[i] == h[i - k:i + k + 1].max():
            ph[i] = True
        if l[i] == l[i - k:i + k + 1].min():
            pl[i] = True
    return ph, pl          # a pivot at i is only KNOWN at i+k


def _sr_levels_at(i, piv_idx, piv_px, k, look=120):
    """pivot prices confirmed before bar i (within look bars)"""
    lo_ = np.searchsorted(piv_idx, i - look)
    hi_ = np.searchsorted(piv_idx, i - k)      # confirmed by bar i-1
    return piv_px[lo_:hi_]


def confluences(I: dict, i: int, side: int, plow: float, phigh: float, cache: dict) -> dict:
    o, h, l, c, v = I["o"], I["h"], I["l"], I["c"], I["v"]
    f = {}
    ref = plow if side > 0 else phigh
    near = lambda a, b: np.isfinite(b) and abs(a / b - 1) <= NEAR  # noqa: E731
    # moving averages: touched and closed on the right side, MA sloping with the trade
    for name, ma in (("MA20", I["ma20"]), ("MA44", I["ma44"]), ("MA200", I["ma200"])):
        m0, m5 = ma[i], ma[i - 5] if i >= 5 else np.nan
        if not np.isfinite(m0) or not np.isfinite(m5):
            f[name] = False
            continue
        if side > 0:
            f[name] = (plow <= m0 * (1 + NEAR)) and c[i] > m0 and (name == "MA200" or m0 > m5)
        else:
            f[name] = (phigh >= m0 * (1 - NEAR)) and c[i] < m0 and (name == "MA200" or m0 < m5)
    # Fibonacci of the latest swing (60 bars): retracement of the last move
    a, b = max(0, i - 60), i
    if b - a > 20:
        if side > 0:
            j = a + int(np.argmax(h[a:b])); H = h[j]
            L = l[max(0, j - 60):j + 1].min() if j > a else np.nan
            ok = np.isfinite(L) and (H - L) / L > 0.10
            f["Fib50"] = ok and near(plow, H - 0.5 * (H - L)) and c[i] > H - 0.5 * (H - L)
            f["Fib618"] = ok and near(plow, H - 0.618 * (H - L)) and c[i] > H - 0.618 * (H - L)
        else:
            j = a + int(np.argmin(l[a:b])); L = l[j]
            H = h[max(0, j - 60):j + 1].max() if j > a else np.nan
            ok = np.isfinite(H) and (H - L) / L > 0.10
            f["Fib50"] = ok and near(phigh, L + 0.5 * (H - L)) and c[i] < L + 0.5 * (H - L)
            f["Fib618"] = ok and near(phigh, L + 0.618 * (H - L)) and c[i] < L + 0.618 * (H - L)
    else:
        f["Fib50"] = f["Fib618"] = False
    # support / resistance: >= 2 earlier pivots within 1.5% of the pattern extreme
    k = cache["k"]
    if side > 0:
        lv = _sr_levels_at(i, cache["pl_idx"], cache["pl_px"], k)
        f["Support/Resistance"] = int(np.sum(np.abs(lv / plow - 1) <= NEAR)) >= 2
    else:
        lv = _sr_levels_at(i, cache["ph_idx"], cache["ph_px"], k)
        f["Support/Resistance"] = int(np.sum(np.abs(lv / phigh - 1) <= NEAR)) >= 2
    # gap zone: an earlier gap (last 120 bars) whose zone the pattern extreme tests
    g = cache["gaps"]
    zs = g[(g[:, 0] >= i - 120) & (g[:, 0] < i - 1)]
    if side > 0:
        zs = zs[zs[:, 3] > 0]   # gap-ups act as support
        f["Gap zone"] = bool(np.any((plow <= zs[:, 2] * (1 + NEAR / 2)) & (plow >= zs[:, 1] * (1 - NEAR)) & (c[i] > zs[:, 1]))) if len(zs) else False
    else:
        zs = zs[zs[:, 3] < 0]   # gap-downs act as resistance
        f["Gap zone"] = bool(np.any((phigh >= zs[:, 1] * (1 - NEAR / 2)) & (phigh <= zs[:, 2] * (1 + NEAR)) & (c[i] < zs[:, 2]))) if len(zs) else False
    # trap: broke the prior 20-bar extreme and closed back inside
    if i >= 22:
        if side > 0:
            prior = l[i - 22:i - 2].min()
            f["Trap"] = plow < prior and c[i] > prior
        else:
            prior = h[i - 22:i - 2].max()
            f["Trap"] = phigh > prior and c[i] < prior
    else:
        f["Trap"] = False
    r = I["rsi"]
    if side > 0:
        f["RSI 40/60"] = r[i] >= 40 and np.nanmin(r[max(0, i - 3):i + 1]) <= 46       # pulled back to ~40 and held
        f["RSI extreme"] = np.nanmin(r[max(0, i - 3):i + 1]) <= 30
        f["Trend"] = np.isfinite(I["ma200"][i]) and c[i] > I["ma200"][i]
    else:
        f["RSI 40/60"] = r[i] <= 60 and np.nanmax(r[max(0, i - 3):i + 1]) >= 54
        f["RSI extreme"] = np.nanmax(r[max(0, i - 3):i + 1]) >= 70
        f["Trend"] = np.isfinite(I["ma200"][i]) and c[i] < I["ma200"][i]
    f["Volume spike"] = np.isfinite(I["avgvol"][i]) and v[i] >= 1.5 * I["avgvol"][i]
    return f


def _cache(I: dict, k: int = 3) -> dict:
    h, l, o = I["h"], I["l"], I["o"]
    ph, pl = _pivots(h, l, k)
    gaps = []
    for i in range(1, len(h)):
        if l[i] > h[i - 1] * 1.002:
            gaps.append((i, h[i - 1], l[i], 1))     # zone [prev high, low]
        elif h[i] < l[i - 1] * 0.998:
            gaps.append((i, h[i], l[i - 1], -1))   # zone [high, prev low]
    return dict(k=k, ph_idx=np.where(ph)[0], ph_px=h[ph], pl_idx=np.where(pl)[0], pl_px=l[pl],
                gaps=np.array(gaps, float) if gaps else np.zeros((0, 4)))


def detect(df: pd.DataFrame, last_n: int | None = None) -> pd.DataFrame:
    """All pattern occurrences (optionally only in the last `last_n` bars) with confluence flags."""
    if len(df) < 30:
        return pd.DataFrame()
    I = indicators(df)
    cache = _cache(I)
    n = len(df)
    start = 25 if last_n is None else max(25, n - last_n)
    rows = []
    for name, (mask, side, nb) in _pattern_masks(I).items():
        for i in np.where(mask[start:])[0] + start:
            plow = float(I["l"][i - nb + 1:i + 1].min())
            phigh = float(I["h"][i - nb + 1:i + 1].max())
            f = confluences(I, int(i), side, plow, phigh, cache)
            rows.append(dict(Date=df.index[i], Bar=int(i), Pattern=name, Side=side, PLow=plow, PHigh=phigh,
                             Close=float(I["c"][i]), RSI=round(float(I["rsi"][i]), 1), **f))
    return pd.DataFrame(rows).sort_values("Bar").reset_index(drop=True) if rows else pd.DataFrame()


def tags(row) -> str:
    return " + ".join(k for k in CONFLUENCES if bool(row.get(k)))
