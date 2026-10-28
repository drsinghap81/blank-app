"""
app.py — Global Trading Terminal (US / ASX / NSE)
==================================================

A single-file, lightweight trading terminal built with Streamlit + yfinance.

Features
--------
* Market selector (US, Australia ASX, India NSE) with automatic ticker suffixes
* Market Analysis tab: 60 daily bars, 20-day SMA, 14-day RSI (Wilder), Plotly chart
* Paper Trading tab: Market / Limit orders simulated in st.session_state
* Portfolio tab: positions, live prices, unrealised + realised P&L, trade blotter
* Robust fallbacks: if Yahoo Finance fails or a ticker is invalid, a synthetic
  OHLCV dataset is generated so the UI never breaks (clearly flagged on screen)

Run
---
    pip install "streamlit>=1.50" yfinance plotly pandas numpy
    streamlit run app.py

Notes
-----
* This is a SIMULATION. No orders are sent to any broker.
* Each market keeps its own paper book in its own currency (USD / AUD / INR),
  each starting with 100,000 units of cash.
* Paper-trading state lives in st.session_state, so it resets when the browser
  session ends. (Persisting it to disk/DB is a natural next extension.)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import importlib as _importlib
import os as _os
import sys as _sys


def _fresh(modname: str):
    """Streamlit Cloud can keep an old copy of a helper module in memory after a
    git update; reload it whenever its file has changed on disk."""
    mod = _sys.modules.get(modname)
    if mod is None:
        mod = _importlib.import_module(modname)
    elif getattr(mod, "_loaded_mtime", None) != _os.path.getmtime(mod.__file__):
        mod = _importlib.reload(mod)  # also refreshes copies loaded before this check existed
    mod._loaded_mtime = _os.path.getmtime(mod.__file__)
    return mod


_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tools"))
for _m in ("topbottom", "topbottom_backtest", "topbottom_tab", "patterns"):
    _fresh(_m)
from topbottom_tab import render_topbottom_tab  # noqa: E402

try:  # yfinance is optional at import time so the app still loads without it
    import yfinance as yf
except Exception:  # pragma: no cover - handled gracefully at runtime
    yf = None


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

STARTING_CASH = 100_000.0     # paper cash per market, in that market's currency
DISPLAY_BARS = 60             # default bars shown on the chart (spec: last 60 days)
LOOKBACK_PERIOD = "1y"        # fetch extra history: warms up SMA/RSI and feeds S/R levels
SMA_WINDOW = 20
RSI_WINDOW = 14
CACHE_TTL_SECONDS = 300       # re-fetch prices at most every 5 minutes

# ---- Support / resistance engine (the rules agreed in our chart-reading work) ----
LEVEL_LOOKBACK_BARS = 126     # ~6 months of daily bars
LEVEL_PIVOT_WINDOW = 3        # a swing high/low must be the extreme of +/-3 bars
LEVEL_CLUSTER_TOL = 0.008     # wick pivots within 0.8% are one level
LEVEL_MIN_TOUCHES = 2         # a level needs >= 2 tests to count
LEVEL_NEAR_PCT = 0.03         # "near price" window used to prioritise levels
LEVEL_MAX_SHOWN = 3           # keep charts clean: 2-3 levels

# ---- Pattern rules ----
PATTERN_LEVEL_TOL = 0.006     # candle must reach within 0.6% of the level
PATTERN_LOOKBACK_SIGNALS = 1  # scanner reports patterns on the latest session only (user-selectable)
SCAN_PERIOD = "2y"            # scanner downloads 2 years: 52-week low/high + 200-day average + S/R levels

# ---- Proximity scan & Gann ----
NEAR_SCAN_PCT = 0.02          # "near a level" = last close within 2% of it
GAP_SUPPORT_PCT = 0.01        # pro-gap: red/green pair's low within 1% of a tested support
GAP_MIN_PCT = 0.006           # pro-gap: green candle must open at least 0.6% above the red close
GAP_WICK_TOL = 0.0005         # pro-gap: open = low (bullish) / open = high (bearish), within 0.05%
GANN_CONFLUENCE_PCT = 0.01    # Gann odd square within 1% of a level = confluence


@dataclass(frozen=True)
class MarketConfig:
    """Static settings for one market region."""
    key: str                  # short internal key, e.g. "US"
    label: str                # label shown in the sidebar
    suffix: str               # Yahoo suffix appended to bare tickers
    currency: str             # ISO currency code
    symbol: str               # currency symbol for display
    benchmark: str            # Yahoo symbol of the main index
    benchmark_name: str
    watchlist: tuple = field(default_factory=tuple)


MARKETS: dict[str, MarketConfig] = {
    "United States (US)": MarketConfig(
        key="US", label="United States (US)", suffix="", currency="USD", symbol="$",
        benchmark="^GSPC", benchmark_name="S&P 500",
        # The watchlist doubles as the Scanner universe for each market.
        watchlist=("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
                   "JPM", "V", "MA", "UNH", "XOM", "LLY", "COST", "HD", "NFLX", "AMD",
                   "ORCL", "CRM", "SPY", "QQQ"),
    ),
    "Australia (ASX)": MarketConfig(
        key="ASX", label="Australia (ASX)", suffix=".AX", currency="AUD", symbol="A$",
        benchmark="^AXJO", benchmark_name="S&P/ASX 200",
        watchlist=("CBA.AX", "BHP.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
                   "WES.AX", "MQG.AX", "FMG.AX", "RIO.AX", "WDS.AX", "TLS.AX",
                   "GMG.AX", "WOW.AX", "TCL.AX", "ALL.AX", "STO.AX", "QBE.AX",
                   "REA.AX", "COL.AX"),
    ),
    "India (NSE)": MarketConfig(
        key="NSE", label="India (NSE)", suffix=".NS", currency="INR", symbol="₹",
        benchmark="^NSEI", benchmark_name="Nifty 50",
        # Nifty 50 constituents (as of Oct 2026; edit here when the index rebalances)
        watchlist=("RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "TCS.NS",
                   "SBIN.NS", "BAJFINANCE.NS", "LT.NS", "INFY.NS", "KOTAKBANK.NS",
                   "HINDUNILVR.NS", "SUNPHARMA.NS", "ADANIPORTS.NS", "AXISBANK.NS",
                   "TITAN.NS", "HCLTECH.NS", "ADANIENT.NS", "M&M.NS", "MARUTI.NS",
                   "ITC.NS", "ULTRACEMCO.NS", "ETERNAL.NS", "NTPC.NS", "JSWSTEEL.NS",
                   "BAJAJ-AUTO.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS",
                   "BEL.NS", "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS",
                   "GRASIM.NS", "HDFCLIFE.NS", "HINDALCO.NS", "INDIGO.NS", "JIOFIN.NS",
                   "MAXHEALTH.NS", "NESTLEIND.NS", "ONGC.NS", "POWERGRID.NS",
                   "SBILIFE.NS", "SHRIRAMFIN.NS", "TATACONSUM.NS", "TMPV.NS",
                   "TATASTEEL.NS", "TECHM.NS", "TRENT.NS", "WIPRO.NS"),
    ),
}


# =============================================================================
# 2. PAGE SETUP & STYLING
# =============================================================================

def configure_page() -> None:
    """Set page config and inject a dark, dashboard-style theme."""
    st.set_page_config(page_title="Global Trading Terminal", page_icon="📈",
                       layout="wide", initial_sidebar_state="expanded")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
        html, body, .stApp, [class*="css"], .stMarkdown, button, input, select, textarea {
            font-family: Manrope, system-ui, -apple-system, "Segoe UI", sans-serif !important; }
        .stApp { font-variant-numeric: tabular-nums; }
        .block-container { padding-top: 2.8rem; max-width: 1500px; }
        /* ---- base dark surfaces ---- */
        .stApp { background-color: #0b0e14; color: #d7dce5; }
        section[data-testid="stSidebar"] { background-color: #11151d; border-right: 1px solid #1f2633; }
        h1, h2, h3, h4 { color: #e8ecf3 !important; font-weight: 600; }
        /* ---- metric cards ---- */
        .card { background:#121722; border:1px solid #1f2633; border-radius:10px;
                padding:14px 16px; height:100%; }
        .card .lbl { font-size:12.5px; color:#8a94a6; }
        .card .val { font-size:22px; font-weight:600; color:#f1f4f9; margin-top:4px;
                     font-variant-numeric: tabular-nums; }
        .card .sub { font-size:12px; margin-top:2px; }
        .up { color:#22c55e; } .down { color:#ef4444; } .flat { color:#8a94a6; }
        /* ---- mode badge ---- */
        .mode-badge { display:inline-block; background:#1b2230; color:#cbd5e1;
                      border:1px solid #2b3445; border-radius:999px; padding:5px 12px;
                      font-weight:600; font-size:12.5px; }
        .app-link { display:inline-block; margin-left:8px; background:#E8A33D; color:#14213D !important;
                    border-radius:999px; padding:5px 12px; font-weight:700; font-size:12.5px; text-decoration:none; }
        .data-badge-live { color:#22c55e; font-weight:600; }
        .data-badge-synth { color:#f59e0b; font-weight:600; }
        /* ---- tabs ---- */
        .stTabs [data-baseweb="tab-list"] { gap: 4px; }
        .stTabs [data-baseweb="tab"] { background:#121722; border-radius:999px;
                                        padding:7px 15px; color:#a6b0c3; font-weight:600; }
        .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
        .stTabs [aria-selected="true"] { background:#1b2230 !important; color:#ffffff !important; }
        /* ---- tables ---- */
        div[data-testid="stDataFrame"] { border:1px solid #1f2633; border-radius:8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# 3. TICKER HANDLING
# =============================================================================

def format_ticker(raw: str, market: MarketConfig) -> str:
    """
    Normalise a user-entered ticker for Yahoo Finance.

    * Trims whitespace and upper-cases.
    * Leaves index symbols (^...) and tickers that already carry a suffix alone.
    * Otherwise appends the market suffix (.AX for ASX, .NS for NSE).
    """
    t = (raw or "").strip().upper()
    if not t:
        return ""
    if t.startswith("^") or "." in t or "=" in t:   # index, suffixed, FX/futures
        return t
    return f"{t}{market.suffix}"


# =============================================================================
# 4. DATA LAYER (yfinance + synthetic fallback)
# =============================================================================

def generate_synthetic_ohlcv(ticker: str, bars: int = 130) -> pd.DataFrame:
    """
    Build a realistic-looking random-walk OHLCV frame.

    The random seed is derived from the ticker so the same symbol always produces
    the same fake series (stable charts across reruns).
    """
    seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=bars)

    start = float(rng.uniform(50, 3000))
    rets = rng.normal(0.0004, 0.016, bars)                 # ~1.6% daily vol
    close = start * np.exp(np.cumsum(rets))
    open_ = np.r_[start, close[:-1]] * (1 + rng.normal(0, 0.004, bars))
    spread = np.abs(rng.normal(0, 0.009, bars)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.integers(500_000, 8_000_000, bars).astype(float)

    return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                         "Close": close, "Volume": volume}, index=dates)


def _clean_yf_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance's (possible) MultiIndex columns and keep OHLCV only."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_ohlcv(ticker: str, period: str = LOOKBACK_PERIOD) -> tuple[pd.DataFrame, bool, str]:
    """
    Download daily bars from Yahoo Finance.

    Returns
    -------
    (frame, is_live, message)
        frame   : OHLCV DataFrame (never empty)
        is_live : True if real data, False if the synthetic fallback was used
        message : human-readable reason when falling back
    """
    if yf is None:
        return generate_synthetic_ohlcv(ticker), False, "yfinance is not installed."
    try:
        raw = yf.download(ticker, period=period, interval="1d",
                          auto_adjust=False, progress=False, threads=False)
        if raw is None or raw.empty:
            raise ValueError(f"No data returned for '{ticker}' (invalid symbol or delisted).")
        df = _clean_yf_frame(raw)
        if len(df) < SMA_WINDOW + 5:
            raise ValueError(f"Only {len(df)} bars returned for '{ticker}'.")
        return df, True, ""
    except Exception as exc:  # network errors, rate limits, bad symbols …
        return generate_synthetic_ohlcv(ticker), False, str(exc)


def get_last_price(ticker: str) -> tuple[float, bool]:
    """Latest close for a ticker (uses the cached daily download)."""
    df, live, _ = fetch_ohlcv(ticker)
    return float(df["Close"].iloc[-1]), live


# =============================================================================
# 5. INDICATORS
# =============================================================================

def sma(series: pd.Series, window: int = SMA_WINDOW) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def rsi_wilder(series: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing (the standard definition,
    matching TradingView / most broker platforms).
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100.0).where(avg_loss.notna())  # all-gain windows -> 100


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with SMA and RSI columns appended."""
    out = df.copy()
    out[f"SMA{SMA_WINDOW}"] = sma(out["Close"])
    out[f"RSI{RSI_WINDOW}"] = rsi_wilder(out["Close"])
    return out


# =============================================================================
# 5b. SUPPORT / RESISTANCE ENGINE
# -----------------------------------------------------------------------------
# Rules (as agreed during manual chart reading):
#   * levels come from candle WICKS: swing highs (High) and swing lows (Low)
#   * ~6 months of history; pivots within 0.8% are clustered into one level
#   * a level needs at least 2 tests
#   * a level that has acted as BOTH support and resistance is a "flip"
#     (role reversal) and gets priority when it sits near the current price
#   * the chart shows only 2-3 levels: nearest above, nearest below, plus the
#     most important remaining one
# =============================================================================

@dataclass
class Level:
    price: float          # average of the clustered wick pivots
    touches: int          # number of tests
    flip: bool            # acted as both support and resistance
    kinds: str            # sequence of 'H'/'L' pivots, oldest first
    last_touch: pd.Timestamp

    def role(self, ref_price: float) -> str:
        """'R' if the level is above the reference price, else 'S'."""
        return "R" if self.price > ref_price else "S"

    def label(self, ref_price: float) -> str:
        tag = " flip" if self.flip else ""
        return f"{self.role(ref_price)} {self.price:,.2f} ×{self.touches}{tag}"


def _wick_pivots(df: pd.DataFrame, window: int = LEVEL_PIVOT_WINDOW) -> list[tuple[float, int, str]]:
    """Swing highs/lows: a bar whose High (Low) is the max (min) of +/-window bars."""
    highs, lows = df["High"].to_numpy(), df["Low"].to_numpy()
    n, out = len(df), []
    for i in range(n):
        a, z = max(0, i - window), min(n, i + window + 1)
        if highs[i] == highs[a:z].max():
            out.append((float(highs[i]), i, "H"))
        if lows[i] == lows[a:z].min():
            out.append((float(lows[i]), i, "L"))
    return out


def compute_levels(df: pd.DataFrame, lookback: int = LEVEL_LOOKBACK_BARS) -> list[Level]:
    """All levels with >= LEVEL_MIN_TOUCHES tests in the last `lookback` bars."""
    hist = df.tail(lookback)
    if len(hist) < 2 * LEVEL_PIVOT_WINDOW + 5:
        return []
    pivots = sorted(_wick_pivots(hist))
    groups: list[list[tuple[float, int, str]]] = []
    for p in pivots:
        if groups and p[0] <= groups[-1][0][0] * (1 + LEVEL_CLUSTER_TOL):
            groups[-1].append(p)
        else:
            groups.append([p])

    levels = []
    for g in groups:
        if len(g) < LEVEL_MIN_TOUCHES:
            continue
        g_sorted = sorted(g, key=lambda p: p[1])
        kinds = "".join(p[2] for p in g_sorted)
        levels.append(Level(price=float(np.mean([p[0] for p in g])), touches=len(g),
                            flip=("H" in kinds and "L" in kinds), kinds=kinds,
                            last_touch=hist.index[g_sorted[-1][1]]))
    return levels


def select_levels(levels: list[Level], ref_price: float, k: int = LEVEL_MAX_SHOWN) -> list[Level]:
    """
    Pick the 2-3 levels worth drawing:
      1. nearest resistance above price
      2. nearest support below price
      3. best remaining level: near-price flips first, then most tests, then closest
    """
    if not levels:
        return []
    dist = lambda lv: abs(lv.price / ref_price - 1)
    above = sorted([lv for lv in levels if lv.price > ref_price], key=dist)
    below = sorted([lv for lv in levels if lv.price <= ref_price], key=dist)
    picks = [lst[0] for lst in (above, below) if lst]
    rest = [lv for lv in levels if lv not in picks]
    rest.sort(key=lambda lv: (not (lv.flip and dist(lv) <= LEVEL_NEAR_PCT),
                              -lv.touches, dist(lv)))
    picks += rest[: max(0, k - len(picks))]
    return sorted(picks, key=lambda lv: -lv.price)


def gann_odd_squares(price: float, count: int = 2) -> list[tuple[int, float]]:
    """
    Gann Square-of-Nine odd squares around a price (method agreed earlier):
      take sqrt(price), find the odd integers on either side, square them.
      e.g. 1,211 -> sqrt 34.8 -> 33² = 1,089 below, 35² = 1,225 above.
    `count` = how many odd squares on EACH side (1 -> nearest pair).
    Returns [(root, square), ...] from low to high.
    """
    if price <= 0:
        return []
    f = int(np.floor(np.sqrt(price)))
    lo = f if f % 2 else f - 1
    roots = [lo - 2 * k for k in range(count - 1, -1, -1)] + [lo + 2 * (k + 1) for k in range(count)]
    return [(r, float(r * r)) for r in roots if r > 0]


def nearest_gann(level: float) -> tuple[int, float]:
    """Odd square closest to a given level."""
    return min(gann_odd_squares(level, 1), key=lambda g: abs(g[1] - level))


# =============================================================================
# 5c. CANDLESTICK PATTERNS AT LEVELS
# =============================================================================

def _is_shooting_star(o: float, h: float, l: float, c: float, avg_range: float) -> bool:
    """
    Bearish shooting star: small body near the low, long upper wick, tiny lower wick.
      body  <= 35% of range
      upper wick >= 2x body and >= 55% of range
      lower wick <= 15% of range
      range not tiny (>= 60% of the 14-bar average range)
    """
    rng = h - l
    if rng <= 0 or rng < 0.6 * avg_range:
        return False
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return body <= 0.35 * rng and upper >= 2 * body and upper >= 0.55 * rng and lower <= 0.15 * rng


def _is_morning_star(b1: pd.Series, b2: pd.Series, b3: pd.Series, avg_body: float) -> bool:
    """
    Bullish 3-candle morning star (adapted for equities, where true gaps are rare):
      candle 1: strong bearish body (>= 60% of the 20-bar average body)
      candle 2: small body (<= 50% of candle 1's body) sitting at/below candle 1's close
      candle 3: bullish, closing above the midpoint of candle 1's body
    """
    body1 = b1["Open"] - b1["Close"]
    if body1 <= 0 or body1 < 0.6 * avg_body:
        return False
    body2 = abs(b2["Close"] - b2["Open"])
    if body2 > 0.5 * body1 or max(b2["Open"], b2["Close"]) > b1["Close"] + 0.25 * body1:
        return False
    midpoint1 = b1["Close"] + body1 / 2
    return b3["Close"] > b3["Open"] and b3["Close"] >= midpoint1


def detect_signals(df: pd.DataFrame, last_n: int = PATTERN_LOOKBACK_SIGNALS) -> list[dict]:
    """
    Scan the last `last_n` bars for:
      * SHOOTING STAR AT RESISTANCE: after a rise, the candle's high reaches within
        PATTERN_LEVEL_TOL of a tested level (or pokes through it) and closes below it
      * MORNING STAR AT SUPPORT: after a fall, the 3-candle pattern's low reaches
        within PATTERN_LEVEL_TOL of a tested level and candle 3 closes above it
      * PRO GAP AT SUPPORT: a red candle followed by a green candle with no lower wick
        (open = low, within GAP_WICK_TOL) whose OPEN is at least GAP_MIN_PCT above the red close, with the pair's low within GAP_SUPPORT_PCT of a tested
        support (support = a level at or below today's close)
      * PRO GAP-DOWN AT RESISTANCE: the mirror — a green candle followed by a red candle with
        no upper wick (open = high) opening at least GAP_MIN_PCT below the green close,
        pair's high near resistance

    Levels are computed ONLY from bars before the pattern starts, so a pattern
    never "creates" the level it is being tested against.
    """
    signals = []
    n = len(df)
    if n < 40:
        return signals
    rng = (df["High"] - df["Low"])
    body = (df["Close"] - df["Open"]).abs()

    for i in range(max(25, n - last_n), n):
        bar = df.iloc[i]
        avg_range = float(rng.iloc[i - 14:i].mean())
        avg_body = float(body.iloc[i - 20:i].mean())

        # ---- Shooting star at resistance ----
        rising = df["Close"].iloc[i - 1] > df["Close"].iloc[i - 5]
        if rising and _is_shooting_star(bar["Open"], bar["High"], bar["Low"], bar["Close"], avg_range):
            for lv in compute_levels(df.iloc[:i]):
                if bar["High"] >= lv.price * (1 - PATTERN_LEVEL_TOL) and bar["Close"] < lv.price:
                    signals.append({"Date": df.index[i], "Pattern": "Shooting star at resistance",
                                    "Bias": "Bearish", "Level": lv.price, "Tests": lv.touches,
                                    "Flip": lv.flip, "Close": float(bar["Close"]), "idx": i})
                    break

        # ---- Morning star at support ----
        b1, b2 = df.iloc[i - 2], df.iloc[i - 1]
        falling = b1["Close"] < df["Close"].iloc[i - 6]
        if falling and _is_morning_star(b1, b2, bar, avg_body):
            pattern_low = float(min(b1["Low"], b2["Low"], bar["Low"]))
            for lv in sorted(compute_levels(df.iloc[:i - 2]), key=lambda x: -x.price):
                if pattern_low <= lv.price * (1 + PATTERN_LEVEL_TOL) and bar["Close"] > lv.price:
                    signals.append({"Date": df.index[i], "Pattern": "Morning star at support",
                                    "Bias": "Bullish", "Level": lv.price, "Tests": lv.touches,
                                    "Flip": lv.flip, "Close": float(bar["Close"]), "idx": i})
                    break
        # ---- Pro gap at support: red candle, then a green candle that OPENS above the red close ----
        prev = df.iloc[i - 1]
        red_prev = prev["Close"] < prev["Open"]
        green_now = bar["Close"] > bar["Open"]
        no_low_wick = bar["Open"] - bar["Low"] <= bar["Open"] * GAP_WICK_TOL
        if red_prev and green_now and no_low_wick and bar["Open"] >= prev["Close"] * (1 + GAP_MIN_PCT):
            pair_low = float(min(prev["Low"], bar["Low"]))
            supports = [lv for lv in compute_levels(df.iloc[:i - 1]) if lv.price <= bar["Close"]]
            for lv in sorted(supports, key=lambda x: -x.price):
                if abs(pair_low / lv.price - 1) <= GAP_SUPPORT_PCT:
                    gap_pct = (bar["Open"] / prev["Close"] - 1) * 100
                    signals.append({"Date": df.index[i], "Pattern": f"Pro gap at support (+{gap_pct:.2f}% gap)",
                                    "Bias": "Bullish", "Level": lv.price, "Tests": lv.touches,
                                    "Flip": lv.flip, "Close": float(bar["Close"]), "idx": i, "Kind": "PG"})
                    break

        # ---- Pro gap-down at resistance: green candle, then a red candle that OPENS below the green close ----
        green_prev = prev["Close"] > prev["Open"]
        red_now = bar["Close"] < bar["Open"]
        no_high_wick = bar["High"] - bar["Open"] <= bar["Open"] * GAP_WICK_TOL
        if green_prev and red_now and no_high_wick and bar["Open"] <= prev["Close"] * (1 - GAP_MIN_PCT):
            pair_high = float(max(prev["High"], bar["High"]))
            resist = [lv for lv in compute_levels(df.iloc[:i - 1]) if lv.price >= bar["Close"]]
            for lv in sorted(resist, key=lambda x: x.price):
                if abs(pair_high / lv.price - 1) <= GAP_SUPPORT_PCT:
                    gap_pct = (1 - bar["Open"] / prev["Close"]) * 100
                    signals.append({"Date": df.index[i], "Pattern": f"Pro gap-down at resistance (−{gap_pct:.2f}% gap)",
                                    "Bias": "Bearish", "Level": lv.price, "Tests": lv.touches,
                                    "Flip": lv.flip, "Close": float(bar["Close"]), "idx": i, "Kind": "PGd"})
                    break
    return signals


EMA_FAST, EMA_SLOW = 9, 20
EMA_PULLBACK_MAX = 6   # pullback can last up to this many candles touching EMA 9


def ema_alerts(df: pd.DataFrame, last_n: int = 1, need_ema20_touch: bool = True) -> list[dict]:
    """EMA 9/20 pullback-and-release.
    LONG : EMA9 > EMA20 and BOTH EMAs rising on the alert candle; the previous candle(s) touched EMA9 (low <= EMA9 <= high) and, during
           that pullback, at least one candle also reached EMA20 (low <= EMA20); the ALERT candle
           is the first one whose whole range sits above EMA9 (low > EMA9).
    SHORT: the mirror (EMA9 < EMA20, both EMAs falling, pullback up to EMA9/EMA20, alert candle high < EMA9).
    Trigger = alert candle high (long) / low (short); stop = EMA 20 on the alert candle
    (exit on a move below EMA 20 for longs / above it for shorts)."""
    out = []
    n = len(df)
    if n < EMA_SLOW + EMA_PULLBACK_MAX + 2:
        return out
    c, h, l = df["Close"], df["High"], df["Low"]
    e9 = c.ewm(span=EMA_FAST, adjust=False).mean()
    e20 = c.ewm(span=EMA_SLOW, adjust=False).mean()
    for i in range(max(EMA_SLOW + EMA_PULLBACK_MAX, n - last_n), n):
        for side in (1, -1):
            if (e9.iloc[i] - e20.iloc[i]) * side <= 0:
                continue
            # both EMAs must be sloping in the trade direction on the alert candle
            if (e9.iloc[i] - e9.iloc[i - 1]) * side <= 0 or (e20.iloc[i] - e20.iloc[i - 1]) * side <= 0:
                continue
            clear = l.iloc[i] > e9.iloc[i] if side > 0 else h.iloc[i] < e9.iloc[i]
            if not clear:
                continue
            # pullback = consecutive candles just before i that touched EMA9
            j = i - 1
            while j >= i - EMA_PULLBACK_MAX and l.iloc[j] <= e9.iloc[j] <= h.iloc[j]:
                j -= 1
            if j == i - 1:
                continue  # candle before the alert did not touch EMA9 -> not the "first" to leave
            pb = range(j + 1, i)
            hit20 = any((l.iloc[k] <= e20.iloc[k]) if side > 0 else (h.iloc[k] >= e20.iloc[k]) for k in pb)
            if need_ema20_touch and not hit20:
                continue
            trig = float(h.iloc[i] if side > 0 else l.iloc[i])
            stop = float(e20.iloc[i])  # SL just below EMA 20 (long) / above EMA 20 (short)
            out.append({"Ticker": None, "Date": df.index[i],
                        "Pattern": "EMA 9/20 long alert" if side > 0 else "EMA 9/20 short alert",
                        "Bias": "Bullish" if side > 0 else "Bearish", "Level": round(float(e9.iloc[i]), 2),
                        "EMA20": round(float(e20.iloc[i]), 2), "Trigger": round(trig, 2),
                        "Stop": round(stop, 2), "Risk %": round(abs(trig - stop) / trig * 100, 2),
                        "Pullback candles": len(pb), "Touched EMA20": "yes" if hit20 else "no",
                        "Last close": round(float(c.iloc[-1]), 2)})
    return out


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_universe(tickers: tuple[str, ...], period: str = LOOKBACK_PERIOD) -> tuple[dict, list[str], str]:
    """
    Batch-download daily bars for a whole watchlist in ONE Yahoo request.

    Returns ({ticker: frame}, [tickers that failed], error_message).
    No synthetic fallback here: fake data would produce fake signals.
    """
    if yf is None:
        return {}, list(tickers), "yfinance is not installed."
    raws, last_err = [], ""
    tick = list(tickers)
    for k in range(0, len(tick), 100):          # Yahoo copes better with batches of ~100
        chunk = tick[k:k + 100]
        try:
            r = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                            auto_adjust=False, progress=False, threads=True)
            if len(chunk) == 1 and not isinstance(r.columns, pd.MultiIndex):
                r = pd.concat({chunk[0]: r}, axis=1)
            raws.append(r)
        except Exception as exc:
            last_err = str(exc)
    if not raws:
        return {}, list(tickers), last_err
    raw = pd.concat(raws, axis=1) if len(raws) > 1 else raws[0]
    frames, failed = {}, []
    for t in tickers:
        try:
            sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            sub = _clean_yf_frame(sub.copy())
            if len(sub) >= 40:
                frames[t] = sub
            else:
                failed.append(t)
        except Exception:
            failed.append(t)
    return frames, failed, ""


# =============================================================================
# 5d. BACKTEST ENGINE — Morning star at tested support (long only)
# -----------------------------------------------------------------------------
# Design choices (all chosen to AVOID flattering the results):
#   * no look-ahead: levels are built only from bars BEFORE the pattern starts
#   * entry at the NEXT day's open after the 3rd candle closes
#   * stop = lowest low of the 3-candle pattern (minus an optional buffer)
#   * target = nearest tested resistance above entry at signal time; if none,
#     a fixed R-multiple; plus a maximum holding period (time stop)
#   * if stop and target are both inside one day's range, assume the STOP hit
#     first (conservative)
#   * round-trip costs deducted from every trade (STT, brokerage, slippage)
#   * portfolio: N equal slots; signals beyond free slots are skipped
# Known bias: the universe is TODAY's index members (survivorship bias), which
# tends to make backtests look better than live trading.
# =============================================================================

@dataclass
class BacktestParams:
    min_tests: int = 2              # minimum tests of the support level
    trend_filter: bool = False      # require close > 200-day SMA at signal
    volume_filter: bool = False     # require candle-3 volume > 20-day average
    gann_filter: bool = False       # require a Gann odd square within 1% of the level
    target_mode: str = "Next resistance"   # or "Fixed R-multiple"
    r_multiple: float = 2.0
    max_hold: int = 15              # trading days
    stop_buffer_pct: float = 0.2    # % below pattern low
    cost_pct: float = 0.30          # round-trip costs, % of position
    slots: int = 10                 # concurrent positions (each = 1/slots of equity)


def find_morning_star_trades(df: pd.DataFrame, ticker: str, p: BacktestParams) -> list[dict]:
    """Walk through history and simulate every qualifying morning-star trade for one stock."""
    trades: list[dict] = []
    n = len(df)
    if n < LEVEL_LOOKBACK_BARS + 30:
        return trades
    o, h, l, c = (df[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    vol = df["Volume"].to_numpy() if "Volume" in df else np.ones(n)
    body = np.abs(c - o)
    sma200 = pd.Series(c).rolling(200, min_periods=200).mean().to_numpy()
    vol20 = pd.Series(vol).rolling(20, min_periods=20).mean().to_numpy()

    i = LEVEL_LOOKBACK_BARS + 10
    busy_until = -1
    while i < n - 1:
        if i <= busy_until:                       # one position per stock at a time
            i += 1
            continue
        b1, b2, b3 = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        avg_body = float(body[i - 20:i].mean())
        falling = c[i - 2] < c[i - 6]
        if not (falling and _is_morning_star(b1, b2, b3, avg_body)):
            i += 1
            continue
        if p.trend_filter and not (sma200[i] == sma200[i] and c[i] > sma200[i]):
            i += 1
            continue
        if p.volume_filter and not (vol20[i] == vol20[i] and vol[i] > vol20[i]):
            i += 1
            continue

        pattern_low = float(min(l[i - 2], l[i - 1], l[i]))
        levels = compute_levels(df.iloc[:i - 2])
        support = None
        for lv in sorted(levels, key=lambda x: -x.price):
            if (lv.touches >= p.min_tests and pattern_low <= lv.price * (1 + PATTERN_LEVEL_TOL)
                    and c[i] > lv.price):
                support = lv
                break
        if support is None:
            i += 1
            continue
        if p.gann_filter:
            _, g_sq = nearest_gann(support.price)
            if abs(g_sq / support.price - 1) > GANN_CONFLUENCE_PCT:
                i += 1
                continue

        # ---- Trade plan (decided with information available at bar i) ----
        entry_i = i + 1
        entry = float(o[entry_i])
        stop = pattern_low * (1 - p.stop_buffer_pct / 100)
        if entry <= stop:                          # gapped below the stop: skip
            i += 1
            continue
        risk = entry - stop
        target = entry + p.r_multiple * risk
        if p.target_mode == "Next resistance":
            above = [lv.price for lv in levels if lv.price > entry * 1.003]
            if above:
                target = min(above)

        # ---- Walk forward day by day ----
        exit_i, exit_px, reason = None, None, None
        last_i = min(n - 1, entry_i + p.max_hold - 1)
        for j in range(entry_i, last_i + 1):
            if l[j] <= stop:                       # stop first (conservative)
                exit_i, exit_px, reason = j, min(stop, o[j]) if j > entry_i else stop, "Stop"
                break
            if h[j] >= target:
                exit_i, exit_px, reason = j, max(target, o[j]) if j > entry_i else target, "Target"
                break
        if exit_i is None:
            if last_i == n - 1 and last_i < entry_i + p.max_hold - 1:
                exit_i, exit_px, reason = last_i, float(c[last_i]), "Open (marked)"
            else:
                exit_i, exit_px, reason = last_i, float(c[last_i]), "Time"

        gross = exit_px / entry - 1
        net = gross - p.cost_pct / 100
        trades.append({
            "Ticker": ticker, "Signal date": df.index[i].date(), "Entry date": df.index[entry_i].date(),
            "Exit date": df.index[exit_i].date(), "Entry": round(entry, 2), "Stop": round(stop, 2),
            "Target": round(target, 2), "Exit": round(float(exit_px), 2), "Exit reason": reason,
            "Support": round(support.price, 2), "Tests": support.touches,
            "Days": exit_i - entry_i + 1, "Net %": round(net * 100, 2),
            "R": round((exit_px - entry) / risk, 2),
            "_entry_ts": df.index[entry_i], "_exit_ts": df.index[exit_i],
        })
        busy_until = exit_i
        i = exit_i + 1
    return trades


def simulate_portfolio(trades: list[dict], frames: dict, p: BacktestParams) -> tuple[pd.Series, pd.DataFrame]:
    """
    Run trades through an equal-slot portfolio and mark it to market daily.
    Returns (equity_curve, taken_trades). Starting equity = 1.0.
    """
    if not trades:
        return pd.Series(dtype=float), pd.DataFrame()
    dates = sorted(set().union(*[f.index for f in frames.values()]))
    cal = pd.DatetimeIndex(dates)
    start = min(t["_entry_ts"] for t in trades)
    cal = cal[cal >= start - pd.Timedelta(days=5)]

    by_entry: dict = {}
    for t in sorted(trades, key=lambda t: (t["_entry_ts"], t["Ticker"])):
        by_entry.setdefault(t["_entry_ts"], []).append(t)

    cash, equity_curve, open_pos, taken = 1.0, [], [], []
    for day in cal:
        # 1. close positions that exit today (at their exit price)
        still = []
        for pos in open_pos:
            if pos["t"]["_exit_ts"] <= day:
                cash += pos["alloc"] * (1 + pos["t"]["Net %"] / 100)
            else:
                still.append(pos)
        open_pos = still
        # 2. open new positions at today's open while slots are free
        equity_now = cash + sum(
            pos["alloc"] * float(frames[pos["t"]["Ticker"]]["Close"].asof(day)) / pos["t"]["Entry"]
            for pos in open_pos)
        for t in by_entry.get(day, []):
            if len(open_pos) >= p.slots:
                break
            alloc = min(cash, equity_now / p.slots)
            if alloc <= 0:
                break
            cash -= alloc
            taken.append(t)
            if t["_exit_ts"] <= day:                 # entered and exited the same day
                cash += alloc * (1 + t["Net %"] / 100)
            else:
                open_pos.append({"t": t, "alloc": alloc})
        # 3. mark to market at the close
        mtm = cash + sum(
            pos["alloc"] * float(frames[pos["t"]["Ticker"]]["Close"].asof(day)) / pos["t"]["Entry"]
            for pos in open_pos)
        equity_curve.append(mtm)
    return pd.Series(equity_curve, index=cal), pd.DataFrame(taken)


def backtest_stats(trades_df: pd.DataFrame, equity: pd.Series) -> dict:
    """Headline metrics for the approval decision."""
    if trades_df.empty or equity.empty:
        return {}
    r = trades_df["Net %"] / 100
    wins, losses = r[r > 0], r[r <= 0]
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    peak = equity.cummax()
    return {
        "Trades": len(r),
        "Hit rate %": round(len(wins) / len(r) * 100, 1),
        "Avg win %": round(wins.mean() * 100, 2) if len(wins) else 0.0,
        "Avg loss %": round(losses.mean() * 100, 2) if len(losses) else 0.0,
        "Profit factor": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else float("inf"),
        "Expectancy % / trade": round(r.mean() * 100, 2),
        "Avg R": round(trades_df["R"].mean(), 2),
        "Avg days held": round(trades_df["Days"].mean(), 1),
        "CAGR %": round((equity.iloc[-1] ** (1 / years) - 1) * 100, 2),
        "Max drawdown %": round(((equity / peak) - 1).min() * 100, 2),
        "Years": round(years, 1),
    }


# =============================================================================
# 6. PAPER-TRADING ENGINE (st.session_state)
# =============================================================================

def init_state() -> None:
    """Create one independent paper book per market on first run."""
    if "books" not in st.session_state:
        st.session_state.books = {
            cfg.key: {"cash": STARTING_CASH, "positions": {}, "open_orders": [],
                      "blotter": [], "realized": 0.0}
            for cfg in MARKETS.values()
        }
    if "order_seq" not in st.session_state:
        st.session_state.order_seq = 1


def book_for(market: MarketConfig) -> dict:
    """Shortcut to the active market's paper book."""
    return st.session_state.books[market.key]


def _apply_fill(book: dict, ticker: str, side: str, qty: int, price: float) -> tuple[bool, str]:
    """
    Apply a fill to cash and positions.

    Long-only model: BUY needs enough cash; SELL needs enough shares.
    Average entry price is size-weighted on buys; sells book realised P&L.
    """
    pos = book["positions"].get(ticker, {"qty": 0, "avg": 0.0})
    notional = qty * price

    if side == "BUY":
        if notional > book["cash"] + 1e-9:
            return False, f"Insufficient buying power (needs {notional:,.2f}, have {book['cash']:,.2f})."
        new_qty = pos["qty"] + qty
        pos["avg"] = (pos["avg"] * pos["qty"] + notional) / new_qty
        pos["qty"] = new_qty
        book["cash"] -= notional
    else:  # SELL
        if qty > pos["qty"]:
            return False, f"Cannot sell {qty}; only {pos['qty']} held (short selling disabled)."
        book["realized"] += (price - pos["avg"]) * qty
        pos["qty"] -= qty
        book["cash"] += notional

    if pos["qty"] == 0:
        book["positions"].pop(ticker, None)
    else:
        book["positions"][ticker] = pos

    book["blotter"].append({"Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Ticker": ticker, "Side": side, "Qty": qty,
                            "Fill Price": round(price, 4), "Notional": round(notional, 2)})
    return True, f"Filled {side} {qty} {ticker} @ {price:,.2f}"


def place_order(market: MarketConfig, ticker: str, side: str, order_type: str,
                qty: int, limit_price: float | None) -> tuple[str, str]:
    """
    Route a paper order.

    * MARKET  -> fills immediately at the latest price.
    * LIMIT   -> fills immediately if marketable (BUY limit >= last, SELL limit <= last)
                 at the limit price; otherwise rests in open_orders and is
                 re-checked on every app refresh.
    Returns (status, message) where status is 'filled' | 'working' | 'rejected'.
    """
    book = book_for(market)
    if qty <= 0:
        return "rejected", "Quantity must be greater than zero."

    last, _ = get_last_price(ticker)

    if order_type == "Market":
        ok, msg = _apply_fill(book, ticker, side, qty, last)
        return ("filled" if ok else "rejected"), msg

    # ---- Limit order ----
    if limit_price is None or limit_price <= 0:
        return "rejected", "Limit price must be greater than zero."
    marketable = (side == "BUY" and limit_price >= last) or (side == "SELL" and limit_price <= last)
    if marketable:
        ok, msg = _apply_fill(book, ticker, side, qty, limit_price)
        return ("filled" if ok else "rejected"), msg

    order = {"id": st.session_state.order_seq, "ticker": ticker, "side": side,
             "qty": qty, "limit": float(limit_price),
             "placed": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    st.session_state.order_seq += 1
    book["open_orders"].append(order)
    return "working", f"Limit {side} {qty} {ticker} @ {limit_price:,.2f} is working (last {last:,.2f})."


def process_open_orders(market: MarketConfig) -> list[str]:
    """Fill any resting limit orders whose price has now been reached."""
    book = book_for(market)
    messages, still_open = [], []
    for o in book["open_orders"]:
        last, _ = get_last_price(o["ticker"])
        hit = (o["side"] == "BUY" and last <= o["limit"]) or (o["side"] == "SELL" and last >= o["limit"])
        if hit:
            ok, msg = _apply_fill(book, o["ticker"], o["side"], o["qty"], o["limit"])
            messages.append(("✅ " if ok else "⚠️ ") + msg)
            if not ok:
                still_open.append(o)
        else:
            still_open.append(o)
    book["open_orders"] = still_open
    return messages


def portfolio_snapshot(market: MarketConfig) -> tuple[pd.DataFrame, float, float]:
    """
    Mark every position to market.

    Returns (positions_df, market_value, unrealised_pnl).
    """
    book = book_for(market)
    rows, mv_total, upnl_total = [], 0.0, 0.0
    for tkr, pos in book["positions"].items():
        last, live = get_last_price(tkr)
        mv = last * pos["qty"]
        cost = pos["avg"] * pos["qty"]
        upnl = mv - cost
        mv_total += mv
        upnl_total += upnl
        rows.append({"Ticker": tkr, "Qty": pos["qty"], "Avg Entry": pos["avg"],
                     "Current Price": last, "Market Value": mv, "Unrealised P&L": upnl,
                     "P&L %": (upnl / cost * 100) if cost else 0.0,
                     "Data": "Live" if live else "Synthetic"})
    return pd.DataFrame(rows), mv_total, upnl_total


# =============================================================================
# 7. UI COMPONENTS
# =============================================================================

def metric_card(label: str, value: str, sub: str = "", tone: str = "flat") -> str:
    """Return the HTML for one dark metric card."""
    return (f'<div class="card"><div class="lbl">{label}</div>'
            f'<div class="val">{value}</div><div class="sub {tone}">{sub}</div></div>')


def render_sidebar() -> tuple[MarketConfig, str]:
    """Market selector, watchlist and manual search. Returns (market, ticker)."""
    st.sidebar.markdown("## 🌐 Market")
    choice = st.sidebar.radio("Target Market", list(MARKETS.keys()), index=2)
    market = MARKETS[choice]

    st.sidebar.markdown("## 🔎 Instrument")
    pick = st.sidebar.selectbox(f"{market.key} watchlist", market.watchlist, key=f"wl_{market.key}")
    manual = st.sidebar.text_input(
        "Or search a ticker",
        placeholder={"US": "e.g. AAPL", "ASX": "e.g. CBA", "NSE": "e.g. RELIANCE"}[market.key],
        key=f"search_{market.key}",
        help=f"Suffix '{market.suffix}' is added automatically." if market.suffix else "US tickers need no suffix.",
    )
    ticker = format_ticker(manual, market) if manual.strip() else pick
    st.sidebar.caption(f"Resolved symbol: **{ticker}**  ·  Currency: **{market.currency}**")

    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh prices", width="stretch"):
        fetch_ohlcv.clear()
        fetch_universe.clear()
        st.rerun()
    if st.sidebar.button(f"♻️ Reset {market.key} paper book", width="stretch"):
        st.session_state.books[market.key] = {"cash": STARTING_CASH, "positions": {},
                                              "open_orders": [], "blotter": [], "realized": 0.0}
        st.rerun()
    return market, ticker


def render_header(market: MarketConfig) -> None:
    """Persistent header: title, simulation badge and account / benchmark cards."""
    left, right = st.columns([3, 2])
    with left:
        st.markdown("### 📈 Global Trading Terminal")
        st.caption(f"{market.label}, prices in {market.currency}, delayed data from Yahoo Finance")
    with right:
        st.markdown('<div style="text-align:right;margin-top:10px;">'
                    '<span class="mode-badge">Paper trading only — no real orders</span>'
                    f'<a class="app-link" href="{PHONE_APP_URL}" target="_blank">Open the phone app</a></div>',
                    unsafe_allow_html=True)

    book = book_for(market)
    _, mv, upnl = portfolio_snapshot(market)
    equity = book["cash"] + mv
    total_pnl = equity - STARTING_CASH
    sym = market.symbol

    bench_df, bench_live, _ = fetch_ohlcv(market.benchmark)
    b_last, b_prev = bench_df["Close"].iloc[-1], bench_df["Close"].iloc[-2]
    b_chg = (b_last / b_prev - 1) * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(metric_card("Account Equity", f"{sym}{equity:,.2f}",
                            f"{'+' if total_pnl >= 0 else ''}{total_pnl:,.2f} since start",
                            "up" if total_pnl > 0 else "down" if total_pnl < 0 else "flat"),
                unsafe_allow_html=True)
    c2.markdown(metric_card("Buying Power", f"{sym}{book['cash']:,.2f}",
                            f"{len(book['open_orders'])} working order(s)"), unsafe_allow_html=True)
    c3.markdown(metric_card("Unrealised P&L", f"{sym}{upnl:,.2f}",
                            f"Realised {sym}{book['realized']:,.2f}",
                            "up" if upnl > 0 else "down" if upnl < 0 else "flat"),
                unsafe_allow_html=True)
    c4.markdown(metric_card(market.benchmark_name, f"{b_last:,.2f}",
                            f"{'+' if b_chg >= 0 else ''}{b_chg:.2f}% day"
                            + ("" if bench_live else " · synthetic"),
                            "up" if b_chg > 0 else "down" if b_chg < 0 else "flat"),
                unsafe_allow_html=True)
    st.write("")


PHONE_APP_URL = "https://drsinghap81.github.io/blank-app/"

# Plotly toolbar / gestures: scroll-wheel zoom; drag an END of the price axis to stretch it,
# drag its middle to pan; double-click resets.
CHART_CONFIG = {"scrollZoom": True, "displaylogo": False,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


OI_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "oi", "oi_levels.json")


@st.cache_data(ttl=1800, show_spinner=False)
def load_oi_levels() -> dict:
    """Nightly option-OI levels (max put OI = support, max call OI = resistance) from the NSE F&O bhavcopy."""
    try:
        import json as _json
        with open(OI_PATH, encoding="utf-8") as f:
            return _json.load(f).get("levels", {})
    except Exception:  # noqa: BLE001
        return {}


def oi_for(ticker: str) -> dict | None:
    return load_oi_levels().get(ticker)


def _mix(t: float) -> str:
    """0 = green (support) -> 0.5 = amber -> 1 = red (resistance)."""
    g, a, r = (34, 197, 94), (234, 179, 8), (239, 68, 68)
    c0, c1, u = (g, a, t * 2) if t <= 0.5 else (a, r, (t - 0.5) * 2)
    return ",".join(str(int(c0[i] + (c1[i] - c0[i]) * u)) for i in range(3))


def draw_oi_zone(fig, df, oi: dict, y0: float, y1: float, bands: int = 36, alpha: float = 0.24):
    sup, res = float(oi["support"]), float(oi["resistance"])
    lo, hi = min(sup, res), max(sup, res)
    if hi <= lo:
        return
    x0, x1 = df.index[0], df.index[-1]
    step = (hi - lo) / bands
    for k in range(bands):
        b0, b1 = lo + k * step, lo + (k + 1) * step
        c0, c1 = max(b0, y0), min(b1, y1)
        if c1 <= c0:
            continue
        mid = (b0 + b1) / 2
        t = (mid - sup) / (res - sup)              # 0 at support, 1 at resistance (either orientation)
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=c0, y1=c1, line=dict(width=0), layer="below",
                      fillcolor=f"rgba({_mix(min(max(t, 0), 1))},{alpha})", row=1, col=1)
    fmt = lambda v: f"{v / 1e7:.2f} Cr" if v >= 1e7 else f"{v / 1e5:.1f} L"   # noqa: E731
    for price, col, txt, pos in ((sup, "#22c55e", f"Put-OI support {sup:,.0f} · {fmt(oi['support_oi'])} OI", "bottom right"),
                                 (res, "#ef4444", f"Call-OI resistance {res:,.0f} · {fmt(oi['resistance_oi'])} OI", "top right")):
        if y0 <= price <= y1:
            fig.add_hline(y=price, row=1, col=1, line=dict(color=col, width=2),
                          annotation_text=txt, annotation_position=pos,
                          annotation_font=dict(size=11, color=col), annotation_bgcolor="rgba(15,19,27,0.8)")


def oi_caption(oi: dict) -> str:
    nxt_s = f" (next {oi['support_2']:,.0f})" if oi.get("support_2") else ""
    nxt_r = f" (next {oi['resistance_2']:,.0f})" if oi.get("resistance_2") else ""
    trap = ""
    if oi.get("support_any") and oi["support_any"] != oi["support"]:
        trap += f" ⚠️ Biggest put OI overall is at {oi['support_any']:,.0f}, above the price — put writers trapped (bearish pressure)."
    if oi.get("resistance_any") and oi["resistance_any"] != oi["resistance"]:
        trap += f" ⚠️ Biggest call OI overall is at {oi['resistance_any']:,.0f}, below the price — call writers trapped (short-covering fuel)."
    return (f"Option OI (NSE close {oi['date']}, expiry {oi['expiry']}): put-OI support **{oi['support']:,.0f}**{nxt_s}"
            f" · call-OI resistance **{oi['resistance']:,.0f}**{nxt_r} · PCR {oi['pcr']:.2f}. "
            "Support = biggest put OI at/below the price, resistance = biggest call OI at/above it. "
            "Shading runs green at support → red at resistance." + trap)


def build_price_chart(df: pd.DataFrame, ticker: str, levels: list[Level] | None = None,
                      signals: list[dict] | None = None,
                      gann: list[tuple[int, float]] | None = None,
                      price_zoom: float = 1.0, oi: dict | None = None) -> go.Figure:
    """
    Candles + SMA + S/R lines + pattern markers on top, volume in the middle,
    RSI with 70/30 bands below.
    The price axis is on the RIGHT and fitted to the candles (lines far away never squash
    the chart). price_zoom > 1 stretches the candles vertically around the last close.
    """
    sma_col, rsi_col = f"SMA{SMA_WINDOW}", f"RSI{RSI_WINDOW}"
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.62, 0.14, 0.24])

    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
                                 close=df["Close"], name=ticker,
                                 increasing_line_color="#22c55e", decreasing_line_color="#ef4444"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df[sma_col], name=f"SMA {SMA_WINDOW}",
                             line=dict(color="#60a5fa", width=1.8)), row=1, col=1)

    vol_colors = np.where(df["Close"] >= df["Open"], "#1f7a4d", "#8b2c2c")
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color=vol_colors,
                         showlegend=False), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df[rsi_col], name=f"RSI {RSI_WINDOW}",
                             line=dict(color="#c084fc", width=1.6)), row=3, col=1)
    for lvl, col in ((70, "#ef4444"), (30, "#22c55e")):
        fig.add_hline(y=lvl, line=dict(color=col, width=1, dash="dash"), row=3, col=1)

    # ---- Price range: fitted to the candles, optionally stretched around the last close ----
    ref = float(df["Close"].iloc[-1])
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    if oi:   # bring nearby OI levels (within 6% of the close) into view
        for lvl in (float(oi["support"]), float(oi["resistance"])):
            if abs(lvl / ref - 1) <= 0.06:
                lo, hi = min(lo, lvl), max(hi, lvl)
    pad = (hi - lo) * 0.06 or hi * 0.01
    y0, y1 = lo - pad, hi + pad
    z = max(0.3, float(price_zoom or 1.0))
    if abs(z - 1.0) > 1e-9:
        half = (y1 - y0) / 2 / z
        y0, y1 = ref - half, ref + half
    in_view = lambda p: y0 <= p <= y1   # noqa: E731

    # ---- Option-OI zone: put-OI support (green) shading up to call-OI resistance (red) ----
    if oi:
        draw_oi_zone(fig, df, oi, y0, y1)

    # ---- Horizontal support / resistance lines (only those inside the view) ----
    for lv in levels or []:
        if not in_view(lv.price):
            continue
        is_res = lv.price > ref
        fig.add_hline(y=lv.price, row=1, col=1,
                      line=dict(color="#ef4444" if is_res else "#22c55e", width=1.1, dash="dash"),
                      annotation_text=lv.label(ref), annotation_position="top left",
                      annotation_font=dict(size=10, color="#fca5a5" if is_res else "#86efac"),
                      annotation_bgcolor="rgba(15,19,27,0.75)")

    # ---- Gann odd-square lines: drawn only when they fall inside the view ----
    for root, sq in gann or []:
        if not in_view(sq):
            continue
        fig.add_hline(y=sq, row=1, col=1, line=dict(color="#a78bfa", width=1.1, dash="dot"),
                      annotation_text=f"Gann {root}² = {sq:,.0f}", annotation_position="bottom left",
                      annotation_font=dict(size=10, color="#c4b5fd"),
                      annotation_bgcolor="rgba(15,19,27,0.75)")

    # ---- Pattern markers (only those inside the visible window) ----
    for s in signals or []:
        if s["Date"] not in df.index:
            continue
        bar = df.loc[s["Date"]]
        bearish = s["Bias"] == "Bearish"
        fig.add_trace(go.Scatter(
            x=[s["Date"]], y=[bar["High"] * 1.006 if bearish else bar["Low"] * 0.994],
            mode="markers+text", showlegend=False,
            marker=dict(symbol="triangle-down" if bearish else "triangle-up", size=13,
                        color="#f87171" if bearish else "#4ade80"),
            text=[s.get("Kind", "SS" if bearish else "MS").replace("PGd", "PG")], textfont=dict(size=10, color="#e5e7eb"),
            textposition="top center" if bearish else "bottom center",
            hovertext=f"{s['Pattern']} @ {s['Level']:,.2f} (×{s['Tests']})", hoverinfo="text"),
            row=1, col=1)

    fig.update_layout(template="plotly_dark", height=640, paper_bgcolor="#0b0e14",
                      plot_bgcolor="#0f131b", margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.04, x=0), xaxis_rangeslider_visible=False,
                      hovermode="x unified")
    fig.update_yaxes(gridcolor="#1f2633", side="right", fixedrange=False, ticks="outside")
    fig.update_yaxes(range=[y0, y1], tickformat=",.2f" if ref < 1000 else ",.0f", row=1, col=1)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_xaxes(gridcolor="#1f2633", rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


def render_analysis_tab(market: MarketConfig, ticker: str) -> None:
    """Tab 1: chart + key stats for the selected instrument."""
    raw, live, msg = fetch_ohlcv(ticker)
    if not live:
        st.warning(f"⚠️ Live data unavailable for **{ticker}** — showing a SYNTHETIC dataset "
                   f"so the terminal keeps working.\n\nReason: {msg}")

    wcol, zcol, gcol, ocol = st.columns([3, 2, 2, 2])
    with wcol:
        window = st.radio("Chart window", [60, 126], index=0, horizontal=True,
                          format_func=lambda n: f"{n} bars" + (" (~6 months)" if n == 126 else ""),
                          key="chart_window")
    with zcol:
        pzoom = st.slider("Price scale (stretch)", 0.5, 4.0, 1.0, 0.25, key="price_zoom",
                          help="Above 1× stretches the candles vertically around the last close. "
                               "You can also drag the top or bottom end of the price axis.")
    with gcol:
        show_gann = st.toggle("Gann odd squares", value=False, key="show_gann",
                              help="√price → nearest odd numbers either side → squared. "
                                   "Lines are drawn only when they fall inside the chart.")
    with ocol:
        show_oi = st.toggle("Option OI zone", value=True, key="show_oi",
                            help="F&O stocks and indices: strike with the most put OI (support) and the most call OI "
                                 "(resistance) on the nearest expiry, from last night's NSE bhavcopy. "
                                 "The space between is shaded green → red.")
    full = add_indicators(raw)
    df = full.tail(window)
    last = df.iloc[-1]

    # Levels use ~6 months of wick history, regardless of the chart window.
    all_levels = compute_levels(full)
    shown_levels = select_levels(all_levels, float(last["Close"]))
    # Patterns anywhere in the visible window get a marker on the chart.
    chart_signals = detect_signals(full, last_n=window)
    prev_close = df["Close"].iloc[-2]
    chg = (last["Close"] / prev_close - 1) * 100
    rsi_val = last[f"RSI{RSI_WINDOW}"]
    sma_val = last[f"SMA{SMA_WINDOW}"]
    rsi_state = "Overbought" if rsi_val >= 70 else "Oversold" if rsi_val <= 30 else "Neutral"
    trend = "Above SMA" if last["Close"] > sma_val else "Below SMA"
    sym = market.symbol

    badge = ('<span class="data-badge-live">● LIVE (delayed)</span>' if live
             else '<span class="data-badge-synth">● SYNTHETIC</span>')
    st.markdown(f"#### {ticker} &nbsp; {badge}", unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Last close", f"{sym}{last['Close']:,.2f}", f"{chg:+.2f}%")
    k2.metric(f"SMA {SMA_WINDOW}", f"{sym}{sma_val:,.2f}", trend, delta_color="off")
    k3.metric(f"RSI {RSI_WINDOW}", f"{rsi_val:.1f}", rsi_state, delta_color="off")
    k4.metric(f"{window}-bar high", f"{sym}{df['High'].max():,.2f}")
    k5.metric(f"{window}-bar low", f"{sym}{df['Low'].min():,.2f}")

    # Live pattern status for the most recent bars (same rules as the Scanner tab)
    recent = [s for s in chart_signals if s["idx"] >= len(full) - PATTERN_LOOKBACK_SIGNALS]
    for s in recent:
        msg = (f"**{s['Pattern']}** on {s['Date']:%d %b %Y} at {sym}{s['Level']:,.2f} "
               f"(×{s['Tests']}{' flip' if s['Flip'] else ''}) · close {sym}{s['Close']:,.2f}")
        (st.error if s["Bias"] == "Bearish" else st.success)(msg)

    gann_lines = gann_odd_squares(float(last["Close"]), 1) if show_gann else None
    oi = oi_for(ticker) if show_oi else None
    st.plotly_chart(build_price_chart(df, ticker, shown_levels, chart_signals, gann_lines, pzoom, oi),
                    width="stretch", key=f"analysis_chart_{ticker}", config=CHART_CONFIG)
    if oi:
        st.caption(oi_caption(oi))
    elif show_oi and market.key == "NSE":
        st.caption("No option-OI levels for this symbol (not in F&O, or tonight's NSE data not loaded yet).")
    if gann_lines:
        st.caption(f"Gann: √{last['Close']:,.2f} = {np.sqrt(last['Close']):.2f} → "
                   + " · ".join(f"{r}² = {sq:,.0f} ({(sq / last['Close'] - 1) * 100:+.1f}%)"
                                for r, sq in gann_lines))
    if not live:
        st.caption("Levels and patterns above are computed on SYNTHETIC data — ignore them.")

    with st.expander("Support & resistance levels (6 months, wick-based, ≥2 tests)"):
        if all_levels:
            ref = float(last["Close"])
            lv_df = pd.DataFrame([{
                "Level": round(lv.price, 2), "Role": lv.role(ref), "Tests": lv.touches,
                "Flip": "yes" if lv.flip else "", "Distance %": round((lv.price / ref - 1) * 100, 2),
                "Nearest Gann": f"{nearest_gann(lv.price)[0]}² = {nearest_gann(lv.price)[1]:,.0f}",
                "Gann confluence": "✓" if abs(nearest_gann(lv.price)[1] / lv.price - 1)
                                   <= GANN_CONFLUENCE_PCT else "",
                "Last test": lv.last_touch.date(), "On chart": "✓" if lv in shown_levels else ""}
                for lv in sorted(all_levels, key=lambda x: -x.price)])
            st.dataframe(lv_df, width="stretch", hide_index=True)
        else:
            st.caption("No level with 2+ tests in the last 6 months.")

    with st.expander(f"Raw data (last {window} bars)"):
        show = df[["Open", "High", "Low", "Close", "Volume", f"SMA{SMA_WINDOW}", f"RSI{RSI_WINDOW}"]]
        st.dataframe(show.iloc[::-1].round(2), width="stretch")


NSE_UNIVERSES = {  # label -> default liquidity floor (₹ crore / day)
    "Nifty 50 (watchlist)": 0.0,
    "F&O stocks (~210, most liquid)": 0.0,
    "Nifty 500 — liquid only (≥ ₹25 cr/day)": 25.0,
    "Nifty 500 — all": 0.0,
    "Nifty Next 50": 0.0,
    "Nifty Midcap 150": 10.0,
    "Nifty Smallcap 250": 5.0,
}
_UNIVERSE_FILES = {"F&O": "fno_stocks.csv", "Nifty 500": "nifty500.csv", "Next 50": "niftynext50.csv",
                   "Midcap 150": "niftymidcap150.csv", "Smallcap 250": "niftysmallcap250.csv"}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_nse_universe(choice: str) -> list[str]:
    """Yahoo tickers for the chosen NSE pool (lists refreshed weekly in data/universe/)."""
    import os
    if choice.startswith("Nifty 50 ("):
        return []
    key = next((k for k in _UNIVERSE_FILES if k in choice), None)
    if key is None:
        return []
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "universe", _UNIVERSE_FILES[key])
    if not os.path.exists(p):
        return []
    df = pd.read_csv(p)
    syms = df["Symbol"].astype(str).str.strip()
    return [f"{x}.NS" for x in syms if x and x.upper() != "NAN"]


def supertrend(df: pd.DataFrame, n: int = 10, m: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Supertrend line and direction (+1 up / -1 down), ATR = Wilder."""
    h, l, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    mid = (h + l) / 2
    ub, lb = mid + m * atr, mid - m * atr
    fu, fl = ub.copy(), lb.copy()
    st, d = np.zeros(len(c)), np.ones(len(c))
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = -1 if (d[i - 1] == 1 and c[i] < fl[i]) else (1 if (d[i - 1] == -1 and c[i] > fu[i]) else d[i - 1])
        st[i] = fl[i] if d[i] == 1 else fu[i]
    return pd.Series(st, index=df.index), pd.Series(d, index=df.index)


def trap52_setups(df: pd.DataFrame, last_n: int = 1) -> list[dict]:
    """Bear trap at the 52-week low: a red candle breaks the prior 52-week low, the next candle is a
    green bullish engulfing (body). Buy next session above the engulfing high; stop below the lower
    of the two lows; hold until Supertrend(10,3) has turned up, then exit on a close below it.
    Backtest 2008-26 (213 F&O stocks): +0.57R per trade, PF 1.96, 34% win, ~14 trades a year."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    lo52 = pd.Series(l).rolling(252, min_periods=240).min().shift(1).to_numpy()
    st, sd = supertrend(df)
    out, n = [], len(c)
    for t in range(max(1, n - last_n), n):
        a = t - 1
        if np.isnan(lo52[a]) or not (l[a] < lo52[a] and c[a] < o[a]):
            continue
        if not (c[t] > o[t] and o[t] <= c[a] and c[t] >= o[a]):
            continue
        trig, stop = h[t], min(l[a], l[t])
        risk = trig - stop
        if risk <= 0 or risk / trig > 0.15:
            continue
        out.append({"Date": df.index[t], "Pattern": "52-week-low trap + bullish engulfing", "Bias": "Bullish",
                    "Buy above": round(trig, 2), "Stop": round(stop * 0.999, 2), "Target 3R": round(trig + 3 * risk, 2),
                    "Risk %": round(risk / trig * 100, 2), "52w low": round(lo52[a], 2),
                    "Supertrend": round(float(st.iloc[-1]), 2), "ST dir": "up" if sd.iloc[-1] > 0 else "down"})
    return out


def load_pattern_setups() -> list[dict]:
    """Backtested pattern + confluence setups (data/pattern_setups.json, from tools/pattern_backtest.py)."""
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "pattern_setups.json")
    try:
        import json as _json
        return _json.load(open(p))["setups"]
    except Exception:  # noqa: BLE001
        return []


def candle_rows_for(tkr: str, frame: pd.DataFrame, last_n: int, setups: list[dict]) -> list[dict]:
    """Every deck pattern on the last `last_n` sessions with its confluence tags and the best
    backtested setup it satisfies (if any)."""
    pt = _sys.modules["patterns"]
    sig = pt.detect(frame, last_n=last_n)
    out = []
    last_close = float(frame["Close"].iloc[-1])
    for _, r in sig.iterrows():
        tags = [k for k in pt.CONFLUENCES if bool(r[k])]
        best = None
        for su in setups:
            if su["pattern"] == r["Pattern"] and set(su["confluences"]) <= set(tags):
                if best is None or su["E1R"] > best["E1R"]:
                    best = su
        bull = r["Side"] > 0
        stop = float(r["PLow"]) * 0.999 if bull else float(r["PHigh"]) * 1.001
        risk = abs(last_close - stop)
        out.append({"Ticker": tkr, "Date": pd.Timestamp(r["Date"]).date(), "Candle": r["Pattern"],
                    "Bias": "Bullish" if bull else "Bearish", "Confluence": " + ".join(tags) or "—",
                    "Tags": len(tags), "Setup": (" + ".join(best["confluences"]) if best else ""),
                    "Hit 1R %": best["hit1R"] if best else None, "Avg R (1R)": best["E1R"] if best else None,
                    "Tested trades": best["n"] if best else None,
                    "Last close": round(last_close, 2), "Stop": round(stop, 2),
                    "Target 1R": round(last_close + (risk if bull else -risk), 2),
                    "Target 2R": round(last_close + (2 * risk if bull else -2 * risk), 2),
                    "Risk %": round(risk / last_close * 100, 2), "RSI": r["RSI"]})
    return out


def render_scanner_tab(market: MarketConfig) -> None:
    """Tab: scan the whole watchlist for patterns at tested levels."""
    universe = market.watchlist
    liq_min = 0.0
    if market.key == "NSE":
        u1, u2 = st.columns([3, 2])
        choice = u1.selectbox("Search pool", list(NSE_UNIVERSES), index=0, key="scan_universe",
                              help="F&O stocks are NSE's most liquid names; Nifty 500 covers ~95% of market value.")
        lst = load_nse_universe(choice)
        if lst:
            universe = tuple(lst)
        liq_min = u2.number_input("Min avg daily traded value (₹ crore)", 0.0, 5000.0,
                                  NSE_UNIVERSES[choice], 5.0, key=f"scan_liq_{choice}",
                                  help="20-day average of close × volume. Skips thinly traded stocks.")
    st.markdown(f"#### Pattern scanner — {market.label} ({len(universe)} symbols)")
    st.caption(
        "Shooting star and pro gap-down at resistance (bearish), morning star and pro gap at support (bullish), "
        "on the latest session (or last 3), plus every stock within "
        f"{NEAR_SCAN_PCT:.0%} of a tested level with Gann odd-square confluence "
        f"(odd square within {GANN_CONFLUENCE_PCT:.0%} of the level). Levels: 6 months of "
        "candle wicks, ≥2 tests, within 0.8%. Daily candles; the latest bar may still be forming "
        "during market hours, so confirm on the close.")

    with st.expander("Pro gap settings (both directions)", expanded=False):
        g1, g2, g3 = st.columns(3)
        gap_min = g1.number_input("Min gap (%) — up over red close / down below green close", 0.0, 5.0, GAP_MIN_PCT * 100, 0.1,
                                  key="pg_gap", help="Green candle's OPEN must be this far above the red candle's CLOSE.")
        gap_sup = g2.number_input("Max distance from support / resistance (%)", 0.2, 5.0, GAP_SUPPORT_PCT * 100, 0.1,
                                  key="pg_sup", help="Lowest low of the red/green pair must be this close to a tested support.")
        st.caption("Backtest, all NSE stock futures 2019–2026 (support/resistance 1%, gap 0.6%, no wick). "
                   "Bullish pro gap, 10 days later: +1.14% avg, 60.9% up (151 signals; with 0.2% wick "
                   "tolerance +1.50%, 61.9% up, 341 signals). Bearish gap-down, 5 days later: −0.37% avg, "
                   "only 46.4% up (110 signals). Any day: +0.69%, 54.1% up over 10 days.")
        wick = g3.number_input("No-wick tolerance (%)", 0.0, 1.0, GAP_WICK_TOL * 100, 0.01, format="%.2f",
                               key="pg_wick", help="Open must equal the low (bullish) / high (bearish) within this %.")
    globals()["GAP_MIN_PCT"], globals()["GAP_SUPPORT_PCT"] = gap_min / 100, gap_sup / 100
    globals()["GAP_WICK_TOL"] = wick / 100

    when = st.radio("Patterns formed on", ["Latest session", "Last 3 sessions"], horizontal=True,
                    key="scan_when", help="Latest = the most recent daily candle (today's, while the market "
                                          "is open — confirm on the close).")
    scan_last_n = 1 if when == "Latest session" else 3
    t1, t2 = st.columns([2, 1])
    sma_filter = t1.toggle(f"Trend filter: near support only if SMA{SMA_WINDOW} rising, near resistance only if falling",
                           value=True, key="scan_sma_filter")
    ema_need20 = st.toggle("EMA 9/20 alert: pullback must also touch EMA 20", value=True, key="scan_ema20",
                           help="Off = a touch of EMA 9 alone is enough before the alert candle.")
    sma_days = int(t2.number_input("SMA slope over (sessions)", 1, 20, 5, 1, key="scan_sma_days",
                                   help=f"Rising = SMA{SMA_WINDOW} today above its value this many sessions ago."))

    with st.spinner(f"Downloading {len(universe)} symbols (6 months)…"):
        frames, failed, err = fetch_universe(tuple(universe), period=SCAN_PERIOD)
    if not frames:
        st.error("Live data unavailable, so the scanner can't run (it never uses synthetic data). "
                 + (f"Reason: {err}" if err else ""))
        return
    if failed:
        st.caption(f"No data for {len(failed)}: {', '.join(t.replace('.NS', '') for t in failed[:40])}"
                   + (" …" if len(failed) > 40 else ""))
    if liq_min > 0:
        def _adv_cr(f):
            v = (f["Close"] * f["Volume"]).tail(20).mean()
            return float(v) / 1e7 if pd.notna(v) else 0.0
        before = len(frames)
        frames = {t: f for t, f in frames.items() if _adv_cr(f) >= liq_min}
        st.caption(f"Liquidity filter: {len(frames)} of {before} stocks trade ≥ ₹{liq_min:,.0f} crore a day.")

    pattern_rows, near_rows, ema_rows, candle_rows, trap_rows = [], [], [], [], []
    setups = load_pattern_setups()
    for tkr, frame in frames.items():
        last_close = float(frame["Close"].iloc[-1])

        # ---- 0a. 52-week-low bear trap + bullish engulfing (buy-stop above the engulfing high) ----
        for a in trap52_setups(frame, last_n=scan_last_n):
            a["Ticker"] = tkr
            a["Date"] = a["Date"].date()
            a["Last close"] = round(last_close, 2)
            trap_rows.append(a)

        # ---- 0. Deck candle patterns + confluence (backtested setups flagged) ----
        try:
            candle_rows.extend(candle_rows_for(tkr, frame, scan_last_n, setups))
        except Exception:  # noqa: BLE001
            pass

        # ---- 1. Candlestick patterns at tested levels ----
        for s in detect_signals(frame, last_n=scan_last_n):
            pattern_rows.append({"Ticker": tkr, "Pattern": s["Pattern"], "Bias": s["Bias"],
                                 "Date": s["Date"].date(), "Level": round(s["Level"], 2),
                                 "Tests": s["Tests"], "Flip": "yes" if s["Flip"] else "",
                                 "Pattern close": round(s["Close"], 2), "Last close": round(last_close, 2),
                                 "Since signal %": round((last_close / s["Close"] - 1) * 100, 2)})

        # ---- 1b. EMA 9/20 pullback-and-release alerts ----
        for a in ema_alerts(frame, last_n=scan_last_n, need_ema20_touch=ema_need20):
            a["Ticker"] = tkr
            a["Date"] = a["Date"].date()
            ema_rows.append(a)

        # ---- 2. Price within NEAR_SCAN_PCT of a tested level (+ Gann confluence) ----
        sma20 = frame["Close"].rolling(SMA_WINDOW).mean()
        sma_slope = (float(sma20.iloc[-1] / sma20.iloc[-1 - sma_days] - 1) * 100
                     if len(sma20.dropna()) > sma_days else float("nan"))
        for lv in compute_levels(frame):
            dist = lv.price / last_close - 1
            if abs(dist) > NEAR_SCAN_PCT:
                continue
            g_root, g_sq = nearest_gann(lv.price)
            near_rows.append({
                "Ticker": tkr, "Last close": round(last_close, 2),
                "Near": "Resistance" if dist > 0 else "Support",
                "Level": round(lv.price, 2), "Tests": lv.touches, "Flip": "yes" if lv.flip else "",
                "Distance %": round(dist * 100, 2),
                f"SMA{SMA_WINDOW} {sma_days}d %": round(sma_slope, 2),
                "Nearest Gann": f"{g_root}² = {g_sq:,.0f}",
                "Gann confluence": "✓" if abs(g_sq / lv.price - 1) <= GANN_CONFLUENCE_PCT else ""})

    # ------------------------------------------------------------------
    # Results: tap a category card -> its list (left, scrollable) -> chart (right)
    # ------------------------------------------------------------------
    near_df = pd.DataFrame(near_rows)
    if len(near_df):
        near_df = near_df.assign(_abs=near_df["Distance %"].abs()).sort_values("_abs").drop(columns="_abs")
    pat_df = pd.DataFrame(pattern_rows)
    if len(pat_df):
        pat_df = pat_df.sort_values(["Date", "Ticker"], ascending=[False, True])

    slope_col = f"SMA{SMA_WINDOW} {sma_days}d %"

    def _near(side: str, sign: int) -> pd.DataFrame:
        if not len(near_df):
            return near_df
        d = near_df[near_df["Near"] == side]
        if sma_filter:
            d = d[(d[slope_col] * sign) > 0]   # support: SMA rising; resistance: SMA falling
        return d

    def _pat(prefix: str) -> pd.DataFrame:
        return pat_df[pat_df["Pattern"].str.startswith(prefix)] if len(pat_df) else pat_df

    ema_df = pd.DataFrame(ema_rows)
    cdf = pd.DataFrame(candle_rows)
    if len(cdf):
        cdf = cdf.sort_values(["Avg R (1R)", "Tags"], ascending=[False, False], na_position="last")

    def _cdl(bias: str, tested: bool) -> pd.DataFrame:
        if not len(cdf):
            return cdf
        d = cdf[cdf["Bias"] == bias]
        return d[d["Setup"] != ""] if tested else d[d["Tags"] >= 2]

    trap_df = pd.DataFrame(trap_rows)
    cats = {
        "🪤🟢 52-week-low trap (long)": trap_df,
        "⭐🟢 Tested candle setup (long)": _cdl("Bullish", True),
        "⭐🔴 Tested candle setup (short)": _cdl("Bearish", True),
        "🕯️🟢 Bullish candles + 2 confluences": _cdl("Bullish", False),
        "🕯️🔴 Bearish candles + 2 confluences": _cdl("Bearish", False),
        "🟢 EMA 9/20 long alert": ema_df[ema_df["Bias"] == "Bullish"] if len(ema_df) else ema_df,
        "🔴 EMA 9/20 short alert": ema_df[ema_df["Bias"] == "Bearish"] if len(ema_df) else ema_df,
        "🟢 Pro gap @ support": _pat("Pro gap at"),
        "🔴 Gap-down @ resistance": _pat("Pro gap-down"),
        "🟢 Morning star @ support": _pat("Morning"),
        "🔴 Shooting star @ resistance": _pat("Shooting"),
        f"🟩 Near support (≤{NEAR_SCAN_PCT:.0%}){f' · SMA{SMA_WINDOW} rising' if sma_filter else ''}": _near("Support", +1),
        f"🟥 Near resistance (≤{NEAR_SCAN_PCT:.0%}){f' · SMA{SMA_WINDOW} falling' if sma_filter else ''}": _near("Resistance", -1),
    }
    ck = f"scan_cat_{market.key}"
    if st.session_state.get(ck) not in cats:
        st.session_state[ck] = next((k for k, v in cats.items() if len(v)), list(cats)[-1])

    latest = max(f.index[-1] for f in frames.values())
    st.caption(f"Scanned {len(frames)} stocks · latest session **{pd.Timestamp(latest).strftime('%a %d %b %Y')}**"
               f" · patterns from {'that session' if scan_last_n == 1 else 'the last 3 sessions'}. "
               "Tap a box to list those stocks.")
    with st.expander("🪤 52-week-low trap — rules and backtest", expanded=False):
        st.markdown("**Setup:** a red candle breaks the prior 52-week low, and the next candle is a green bullish "
                    "engulfing (its body covers the red body). **Entry:** next session, buy above the engulfing high. "
                    "**Stop:** below the lower of the two lows. **Exit:** keep the stop until Supertrend (10,3) turns up, "
                    "then exit on a daily close below Supertrend (purple dotted line). The 3R line is for reference.")
        st.caption("Honest backtest — every stock that was in F&O at the time, including ones later dropped or "
                   "delisted (NSE bhavcopies 2009–2026): +0.12R per trade, profit factor 1.18, 29% winners, worst "
                   "drawdown −41R, ~20 trades a year — a weak edge. On today's F&O list only it looked much better "
                   "(+0.57R, PF 1.96) because companies that collapsed (DHFL, Jet, RCOM…) are missing; on those it lost "
                   "(−0.09R). Treat as a watch-list idea, not a proven system. Stops are wide (median ~6%). "
                   "The mirror short lost money in every variant and is not scanned.")
    with st.expander("⭐ Tested candle setups — what was tested and how", expanded=False):
        st.caption("Patterns and confluences from the 'Candlestick Pattern – Chart Examples' deck, backtested on 213 NSE "
                   "F&O stocks, daily, 2010–2026: enter at the next open, stop just beyond the pattern's low (long) / "
                   "high (short), target 1R or 2R, exit after 15 sessions. Patterns ALONE had no edge (47% hit 1R, "
                   "−0.08R per trade). Only combinations profitable in BOTH 2010–19 and 2020–26 are starred. "
                   "None reach a 70% hit rate at 1R; the best are 53–57% with +0.1 to +0.2R per trade. "
                   "Hand-drawn trendlines are not included. Caution: tested on today's F&O list — other stock "
                   "strategies roughly halved when re-tested on the historical F&O list, so expect less.")
        if setups:
            st.dataframe(pd.DataFrame([{"Candle": x["pattern"], "Confluence": " + ".join(x["confluences"]),
                                        "Trades": x["n"], "Hit 1R %": x["hit1R"], "Avg R (1R target)": x["E1R"],
                                        "Avg R (2R target)": x["E2R"], "2010–19": x["E1R_2010_19"],
                                        "2020–26": x["E1R_2020_26"]} for x in setups]),
                         hide_index=True, width="stretch")
    cols = st.columns(len(cats))
    for col, (name, df_) in zip(cols, cats.items()):
        n = df_["Ticker"].nunique() if len(df_) else 0
        col.button(f"{name}\n\n**{n}**", key=f"{ck}_{name}", width="stretch",
                   type="primary" if st.session_state[ck] == name else "secondary",
                   on_click=lambda nm=name: st.session_state.__setitem__(ck, nm))

    cat = st.session_state[ck]
    rows = cats[cat]
    if cat.startswith(("🟩", "🟥")) and len(rows):  # noqa: SIM102
        if st.toggle("Only Gann confluence", value=False, key=f"conf_{market.key}"):
            rows = rows[rows["Gann confluence"] == "✓"]

    with st.expander("Layout", expanded=False):
        l1, l2, l3 = st.columns(3)
        list_pct = l1.slider("List width (%)", 15, 60, 35, 5, key="scan_list_pct",
                             help="Slide left for a narrower list and a wider chart.")
        chart_h = l2.slider("Chart height (px)", 400, 1100, 640, 20, key="scan_chart_h")
        bars = l3.select_slider("Chart window", [40, 60, 90, 126], value=DISPLAY_BARS, key="scan_bars",
                                format_func=lambda b: f"{b} sessions")
        l4, l5, l6 = st.columns(3)
        scan_zoom = l4.slider("Price scale (stretch)", 0.5, 4.0, 1.0, 0.25, key="scan_price_zoom",
                              help="Above 1× stretches the candles around the last close. "
                                   "You can also drag the top or bottom end of the price axis.")
        scan_gann = l5.toggle("Gann odd squares", value=False, key="scan_gann")
        scan_oi = l6.toggle("Option OI zone", value=True, key="scan_oi")
    left, right = st.columns([list_pct, 100 - list_pct], gap="medium")
    with left:
        st.markdown(f"##### {cat} — {rows['Ticker'].nunique() if len(rows) else 0} stocks")
        if not len(rows):
            st.info("Nothing in this list right now — these are selective setups. "
                    "Try another box, a bigger search pool or looser Pro gap settings.")
            pick = None
        else:
            def _label(r) -> str:
                t = r["Ticker"].replace(".NS", "")
                if "Buy above" in r:
                    return (f"{t}  ·  {pd.Timestamp(r['Date']).strftime('%d %b')}  ·  buy above {r['Buy above']:,.1f}  ·  "
                            f"SL {r['Stop']:,.1f} ({r['Risk %']:.1f}%)  ·  3R {r['Target 3R']:,.1f}  ·  Supertrend {r['ST dir']}")
                if "Candle" in r:
                    tested = (f"  ·  ⭐ tested: {r['Hit 1R %']:.0f}% hit, {r['Avg R (1R)']:+.2f}R/trade ({r['Tested trades']:.0f})"
                              if r["Setup"] else "")
                    return (f"{t}  ·  {pd.Timestamp(r['Date']).strftime('%d %b')}  ·  {r['Candle']}  ·  {r['Confluence']}"
                            f"  ·  close {r['Last close']:,.1f}  ·  SL {r['Stop']:,.1f} ({r['Risk %']:.1f}%){tested}")
                if "Trigger" in r:
                    act = "buy above" if r["Bias"] == "Bullish" else "sell below"
                    return (f"{t}  ·  {pd.Timestamp(r['Date']).strftime('%d %b')}  ·  {act} {r['Trigger']:,.1f}  ·  "
                            f"SL {'below' if r['Bias'] == 'Bullish' else 'above'} EMA20 {r['Stop']:,.1f} ({r['Risk %']:.1f}%)"
                            f"  ·  EMA9 {r['Level']:,.1f}")
                if "Pattern" in r:
                    return f"{t}  ·  {pd.Timestamp(r['Date']).strftime('%d %b')}  ·  level {r['Level']:,.1f}  ·  {r['Last close']:,.1f}"
                trend = "rising" if r[slope_col] > 0 else "falling"
                return (f"{t}  ·  {r['Near'].lower()} {r['Level']:,.1f} ({r['Tests']} tests)  ·  close {r['Last close']:,.1f}"
                        f"  ·  {abs(r['Distance %']):.2f}% away  ·  SMA{SMA_WINDOW} {trend} {abs(r[slope_col]):.1f}% in {sma_days}d"
                        f"{'  · Gann ✓' if r['Gann confluence'] else ''}")
            opts = list(range(len(rows)))
            labels = [_label(r) for _, r in rows.iterrows()]
            pk = f"scan_row_{market.key}_{cat}"
            if st.session_state.get(pk, 0) >= len(opts):
                st.session_state[pk] = 0
            with st.container(height=max(360, chart_h - 120)):
                idx = st.radio("Stocks", opts, format_func=lambda i: labels[i], key=pk,
                               label_visibility="collapsed")
            pick = rows.iloc[idx]["Ticker"]
            with st.expander("Table view / download"):
                st.dataframe(rows, width="stretch", hide_index=True)
    with right:
        if pick:
            full = add_indicators(frames[pick])
            view = full.tail(bars)
            ref = float(view["Close"].iloc[-1])
            fig = build_price_chart(view, pick, select_levels(compute_levels(full), ref),
                                    detect_signals(full, last_n=bars),
                                    gann_odd_squares(ref, 1) if scan_gann else None, scan_zoom,
                                    oi_for(pick) if scan_oi else None)
            fig.update_layout(height=chart_h)
            e9v = full["Close"].ewm(span=EMA_FAST, adjust=False).mean().tail(bars)
            e20v = full["Close"].ewm(span=EMA_SLOW, adjust=False).mean().tail(bars)
            fig.add_trace(go.Scatter(x=e9v.index, y=e9v, name=f"EMA {EMA_FAST}", line=dict(color="#f59e0b", width=1.6)),
                          row=1, col=1)
            fig.add_trace(go.Scatter(x=e20v.index, y=e20v, name=f"EMA {EMA_SLOW}", line=dict(color="#3b82f6", width=1.6)),
                          row=1, col=1)
            if len(rows) and "Buy above" in rows.columns:
                rr = rows.iloc[idx]
                stl, _ = supertrend(full)
                stv = stl.tail(bars)
                fig.add_trace(go.Scatter(x=stv.index, y=stv, name="Supertrend (10,3)", mode="lines",
                                         line=dict(color="#a78bfa", width=1.6, dash="dot")), row=1, col=1)
                for nm, col_, dash in (("Buy above", "#4ade80", "dash"), ("Stop", "#fbbf24", "dot"), ("Target 3R", "#60a5fa", "dash")):
                    fig.add_hline(y=rr[nm], line=dict(color=col_, dash=dash, width=1.2), row=1, col=1,
                                  annotation_text=f"{nm} {rr[nm]:,.1f}", annotation_position="top right",
                                  annotation_font=dict(color=col_, size=11), annotation_bgcolor="rgba(15,19,27,0.75)")
            if len(rows) and "Candle" in rows.columns:
                rr = rows.iloc[idx]
                for nm, col_, dash in (("Stop", "#fbbf24", "dot"), ("Target 1R", "#60a5fa", "dash"), ("Target 2R", "#4ade80", "dash")):
                    fig.add_hline(y=rr[nm], line=dict(color=col_, dash=dash, width=1.2), row=1, col=1,
                                  annotation_text=f"{nm} {rr[nm]:,.1f}", annotation_position="top right",
                                  annotation_font=dict(color=col_, size=11), annotation_bgcolor="rgba(15,19,27,0.75)")
            if len(rows) and "Trigger" in rows.columns:
                rr = rows.iloc[idx]
                col_ = "#4ade80" if rr["Bias"] == "Bullish" else "#f87171"
                fig.add_hline(y=rr["Trigger"], line=dict(color=col_, dash="dash", width=1.4), row=1, col=1,
                              annotation_text=f"Trigger {rr['Trigger']:,.1f}", annotation_position="top right",
                              annotation_bgcolor="rgba(15,19,27,0.75)",
                              annotation_font=dict(color=col_, size=11))
                fig.add_hline(y=rr["Stop"], line=dict(color="#fbbf24", dash="dot", width=1.2), row=1, col=1,
                              annotation_text=f"SL (EMA20) {rr['Stop']:,.1f}", annotation_position="bottom right",
                              annotation_bgcolor="rgba(15,19,27,0.75)",
                              annotation_font=dict(color="#fbbf24", size=11))
            h1, h2 = st.columns([4, 1])
            h1.markdown(f"##### {pick.replace('.NS', '')} — last close {ref:,.2f}")
            if h2.button("⛶ Full screen", key=f"scanner_fs_{pick}", width="stretch"):
                _chart_fullscreen(fig, pick)
            st.plotly_chart(fig, width="stretch", key=f"scanner_chart_{pick}", config=CHART_CONFIG)


@st.dialog("Chart", width="large")
def _chart_fullscreen(fig: go.Figure, ticker: str) -> None:
    """Large pop-up view of a chart (press Esc or ✕ to close)."""
    big = go.Figure(fig)
    big.update_layout(height=820)
    st.markdown(f"#### {ticker.replace('.NS', '')}")
    st.plotly_chart(big, width="stretch", key=f"fs_chart_{ticker}", config=CHART_CONFIG)
    st.caption("Tip: drag the top or bottom end of the price axis (right) to stretch it, scroll to zoom, "
               "double-click to reset.")


def render_backtest_tab(market: MarketConfig) -> None:
    """Tab: backtest 'morning star at tested support' across the watchlist."""
    st.markdown(f"#### Backtest — Morning star at tested support ({market.label})")
    st.caption("Long only. Entry next day's open; stop below the pattern low; target the next tested "
               "resistance (or an R-multiple); time stop. Costs deducted. Levels use only data "
               "before each signal. Universe = today's watchlist (survivorship bias: live results "
               "are usually worse).")

    with st.form(key=f"bt_form_{market.key}"):
        c1, c2, c3 = st.columns(3)
        years = c1.selectbox("History", ["5y", "10y"], index=1)
        min_tests = c1.selectbox("Min tests of support", [2, 3, 4], index=0)
        target_mode = c2.selectbox("Target", ["Next resistance", "Fixed R-multiple"])
        r_mult = c2.number_input("R-multiple (fallback / fixed)", 1.0, 5.0, 2.0, 0.5)
        max_hold = c3.number_input("Max holding days", 3, 60, 15, 1)
        slots = c3.number_input("Portfolio slots", 1, 20, 10, 1,
                                help="Max open positions; each gets 1/slots of equity.")
        f1, f2, f3, f4 = st.columns(4)
        trend = f1.checkbox("Above 200-day SMA")
        volf = f2.checkbox("Volume > 20-day avg")
        gannf = f3.checkbox("Gann confluence")
        cost = f4.number_input("Round-trip cost %", 0.0, 2.0, 0.30, 0.05)
        run = st.form_submit_button("Run backtest", type="primary", width="stretch")

    params = BacktestParams(min_tests=int(min_tests), trend_filter=trend, volume_filter=volf,
                            gann_filter=gannf, target_mode=target_mode, r_multiple=float(r_mult),
                            max_hold=int(max_hold), cost_pct=float(cost), slots=int(slots))
    key = f"bt_result_{market.key}"
    if run:
        with st.spinner(f"Downloading {years} of daily data for {len(market.watchlist)} symbols…"):
            frames, failed, err = fetch_universe(tuple(market.watchlist), period=years)
        if not frames:
            st.error("Live data unavailable — backtests never use synthetic data. "
                     + (f"Reason: {err}" if err else ""))
            return
        with st.spinner("Simulating trades…"):
            all_trades = []
            for tkr, frame in frames.items():
                all_trades += find_morning_star_trades(frame, tkr, params)
            equity, taken = simulate_portfolio(all_trades, frames, params)
        st.session_state[key] = {"params": params, "years": years, "failed": failed,
                                 "signals": len(all_trades), "equity": equity, "taken": taken}

    res = st.session_state.get(key)
    if not res:
        st.info("Set the options and tap **Run backtest**. 10 years × 50 stocks takes about a minute.")
        return
    if not run and res["params"] != params:
        st.caption("Showing the last run; settings above have changed since — run again to update.")

    taken, equity = res["taken"], res["equity"]
    if taken.empty:
        st.warning(f"No qualifying trades in {res['years']} with these filters.")
        return
    stats = backtest_stats(taken, equity)

    # ---- Verdict against the approval thresholds ----
    hit_ok = stats["Hit rate %"] >= 70
    dd_ok = stats["Max drawdown %"] >= -10
    pf_ok = stats["Profit factor"] > 1.3
    st.markdown("##### Verdict vs your criteria")
    v1, v2, v3 = st.columns(3)
    v1.metric("Hit rate (target ≥ 70%)", f"{stats['Hit rate %']}%", "PASS" if hit_ok else "FAIL",
              delta_color="normal" if hit_ok else "inverse")
    v2.metric("Max drawdown (target ≤ 10%)", f"{stats['Max drawdown %']}%", "PASS" if dd_ok else "FAIL",
              delta_color="normal" if dd_ok else "inverse")
    v3.metric("Profit factor (want > 1.3)", f"{stats['Profit factor']}", "PASS" if pf_ok else "FAIL",
              delta_color="normal" if pf_ok else "inverse")

    m = st.columns(4)
    m[0].metric("Trades taken", stats["Trades"], f"of {res['signals']} signals", delta_color="off")
    m[1].metric("CAGR", f"{stats['CAGR %']}%")
    m[2].metric("Expectancy / trade", f"{stats['Expectancy % / trade']}%")
    m[3].metric("Avg win / loss", f"{stats['Avg win %']}% / {stats['Avg loss %']}%")
    st.caption(f"Avg R {stats['Avg R']} · avg hold {stats['Avg days held']} days · {stats['Years']} years"
               + (f" · no data for: {', '.join(res['failed'])}" if res["failed"] else ""))

    fig = go.Figure(go.Scatter(x=equity.index, y=(equity - 1) * 100, mode="lines",
                               line=dict(color="#60a5fa", width=1.8), name="Equity"))
    dd = (equity / equity.cummax() - 1) * 100
    fig.add_trace(go.Scatter(x=dd.index, y=dd, mode="lines", fill="tozeroy", name="Drawdown",
                             line=dict(color="#ef4444", width=1), fillcolor="rgba(239,68,68,0.15)"))
    fig.update_layout(template="plotly_dark", height=360, paper_bgcolor="#0b0e14", plot_bgcolor="#0f131b",
                      margin=dict(l=10, r=10, t=30, b=10), yaxis_title="% (equity / drawdown)",
                      legend=dict(orientation="h", y=1.08, x=0), hovermode="x unified")
    st.plotly_chart(fig, width="stretch", key=f"bt_equity_{market.key}")

    reasons = taken["Exit reason"].value_counts()
    st.caption("Exits: " + " · ".join(f"{k} {v}" for k, v in reasons.items()))
    show = taken.drop(columns=[c for c in taken.columns if c.startswith("_")])
    st.dataframe(show.sort_values("Signal date", ascending=False), width="stretch", hide_index=True)
    st.download_button("Download trades (CSV)", show.to_csv(index=False),
                       file_name=f"morning_star_backtest_{market.key}.csv", mime="text/csv")


def render_trading_tab(market: MarketConfig, ticker: str) -> None:
    """Tab 2: paper-trading ticket + working orders."""
    book = book_for(market)
    last, live = get_last_price(ticker)
    sym = market.symbol

    left, right = st.columns([2, 3])
    with left:
        st.markdown(f"#### Order ticket — {ticker}")
        st.caption(f"Last {sym}{last:,.2f}" + ("" if live else " (synthetic)")
                   + f" · Buying power {sym}{book['cash']:,.2f}")

        with st.form(key=f"ticket_{market.key}", clear_on_submit=False):
            side = st.radio("Side", ["BUY", "SELL"], horizontal=True)
            order_type = st.radio("Order type", ["Market", "Limit"], horizontal=True)
            qty = st.number_input("Quantity", min_value=1, value=10, step=1)
            limit_price = st.number_input("Limit price (Limit orders only)", min_value=0.0,
                                          value=float(round(last, 2)), step=0.05, format="%.2f")
            est = qty * (limit_price if order_type == "Limit" else last)
            st.caption(f"Estimated notional: {sym}{est:,.2f}")
            submitted = st.form_submit_button("Submit paper order", width="stretch",
                                              type="primary")

        if submitted:
            status, msg = place_order(market, ticker, side, order_type, int(qty),
                                      float(limit_price) if order_type == "Limit" else None)
            {"filled": st.success, "working": st.info, "rejected": st.error}[status](msg)

    with right:
        st.markdown("#### Working limit orders")
        if book["open_orders"]:
            oo = pd.DataFrame(book["open_orders"])[["id", "placed", "ticker", "side", "qty", "limit"]]
            oo.columns = ["ID", "Placed", "Ticker", "Side", "Qty", "Limit"]
            st.dataframe(oo, width="stretch", hide_index=True)
            ids = [o["id"] for o in book["open_orders"]]
            cancel_id = st.selectbox("Cancel order", ids, key=f"cancel_{market.key}")
            if st.button("Cancel selected order", key=f"cancel_btn_{market.key}"):
                book["open_orders"] = [o for o in book["open_orders"] if o["id"] != cancel_id]
                st.rerun()
        else:
            st.caption("No working orders. Non-marketable limit orders appear here and fill "
                       "automatically on refresh once price reaches the limit.")

        st.markdown("#### Recent fills")
        if book["blotter"]:
            st.dataframe(pd.DataFrame(book["blotter"]).iloc[::-1].head(10),
                         width="stretch", hide_index=True)
        else:
            st.caption("No fills yet.")


def render_portfolio_tab(market: MarketConfig) -> None:
    """Tab 3: positions marked to market + P&L summary + full blotter."""
    book = book_for(market)
    pos_df, mv, upnl = portfolio_snapshot(market)
    sym = market.symbol
    equity = book["cash"] + mv

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Equity", f"{sym}{equity:,.2f}", f"{equity - STARTING_CASH:+,.2f}")
    s2.metric("Cash", f"{sym}{book['cash']:,.2f}")
    s3.metric("Unrealised P&L", f"{sym}{upnl:,.2f}")
    s4.metric("Realised P&L", f"{sym}{book['realized']:,.2f}")

    st.markdown("#### Open positions")
    if pos_df.empty:
        st.info("No positions yet — place a paper trade in the Order Execution tab.")
    else:
        def _pnl_color(v: float) -> str:
            return "color: #22c55e" if v > 0 else "color: #ef4444" if v < 0 else ""
        styled = (pos_df.style
                  .format({"Avg Entry": "{:,.2f}", "Current Price": "{:,.2f}",
                           "Market Value": "{:,.2f}", "Unrealised P&L": "{:+,.2f}",
                           "P&L %": "{:+.2f}%"})
                  .map(_pnl_color, subset=["Unrealised P&L", "P&L %"]))
        st.dataframe(styled, width="stretch", hide_index=True)

    st.markdown("#### Trade blotter")
    if book["blotter"]:
        blot = pd.DataFrame(book["blotter"]).iloc[::-1]
        st.dataframe(blot, width="stretch", hide_index=True)
        st.download_button("Download blotter (CSV)", blot.to_csv(index=False),
                           file_name=f"paper_blotter_{market.key}.csv", mime="text/csv")
    else:
        st.caption("No trades recorded.")


# =============================================================================
# 8. MAIN
# =============================================================================

APP_BUILD = "2026-10-29 · Trend scan for India, US and Australia v29"


def render_oi_alerts_tab() -> None:
    """Trapped option writers across all NSE F&O underlyings (nightly, from the F&O bhavcopy)."""
    import json as _json
    base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "oi")
    try:
        a = _json.load(open(_os.path.join(base, "alerts.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st.info("OI alerts appear after the first nightly NSE update (about 7 pm IST on trading days).")
        return
    lv = load_oi_levels()
    tp, tc = pd.DataFrame(a.get("trapped_puts", [])), pd.DataFrame(a.get("trapped_calls", []))
    st.markdown(f"#### 🧲 Trapped option writers — NSE close {a['date']}")
    st.caption("**Trapped PUT writers** = the biggest put OI of the chain sits above the price (those puts are in the money): "
               "a **bearish** sign. **Trapped CALL writers** = the biggest call OI sits below the price: short-covering fuel, "
               "a **bullish** sign. Nearest expiry, updated every trading night. Telegram gets the indices and the new names.")
    c = st.columns(4)
    for col, (t, name) in zip(c[:2], (("^NSEI", "Nifty"), ("^NSEBANK", "Bank Nifty"))):
        v = lv.get(t)
        if not v:
            continue
        u = v["underlying"]
        state = ("🔴 Put writers trapped" if v["support_any"] > u else "🟢 Call writers trapped" if v["resistance_any"] < u
                 else "⚪ No trap")
        col.metric(f"{name} {u:,.0f}", state, f"S {v['support']:,.0f} · R {v['resistance']:,.0f} · PCR {v['pcr']:.2f}",
                   delta_color="off")
    n = max(len(lv), 1)
    c[2].metric("Trapped PUT writers (bearish)", f"{len(tp)} / {len(lv)}", f"{len(tp) / n:.0%} of F&O names", delta_color="off")
    c[3].metric("Trapped CALL writers (bullish)", f"{len(tc)} / {len(lv)}", f"{len(tc) / n:.0%} of F&O names", delta_color="off")
    new_only = st.toggle("Only names that are new today", value=False, key="oi_new_only")
    cols = ["symbol", "price", "biggest_put", "biggest_call", "gap_pct", "support", "resistance", "pcr", "new"]
    names = {"symbol": "Symbol", "price": "Price", "biggest_put": "Biggest put OI strike", "biggest_call": "Biggest call OI strike",
             "gap_pct": "Trap depth %", "support": "Support (put OI ≤ price)", "resistance": "Resistance (call OI ≥ price)",
             "pcr": "PCR", "new": "New today"}
    left, right = st.columns(2)
    for box, df_, title in ((left, tp, "🔴 Trapped put writers — bearish"), (right, tc, "🟢 Trapped call writers — bullish")):
        with box:
            st.markdown(f"##### {title}")
            if df_.empty:
                st.write("None today.")
                continue
            d = df_[df_.new] if new_only else df_
            st.dataframe(d[[k for k in cols if k in d]].rename(columns=names), hide_index=True, width="stretch", height=420)
    hp = _os.path.join(base, "history.csv")
    if _os.path.exists(hp):
        h = pd.read_csv(hp)
        b = h.groupby("date").agg(puts=("trapped_puts", "mean"), calls=("trapped_calls", "mean")) * 100
        if len(b) > 1:
            st.markdown("##### Market breadth: % of F&O names with trapped writers")
            st.line_chart(b.rename(columns={"puts": "Trapped put writers % (bearish)", "calls": "Trapped call writers % (bullish)"}))
        else:
            st.caption("Breadth history starts today and builds up every trading night.")
    st.caption("Not yet backtested as a trading signal — the daily history is being recorded so it can be tested.")


TREND_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "scan", "trend_scan.json")


@st.cache_data(ttl=1800, show_spinner=False)
def load_trend_scan(mkey: str = "NSE") -> dict:
    import json as _json
    try:
        path = TREND_PATH if mkey == "NSE" else TREND_PATH.replace(_os.path.join("scan", "trend_scan.json"),
                                                                   _os.path.join("scan", mkey.lower(), "trend_scan.json"))
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def supertrend_line(df: pd.DataFrame, n: int = 10, m: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """Supertrend(10,3) direction (+1/-1) and line, same rules as tools/trend_scan.py."""
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("High", "Low", "Close"))
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.empty_like(c); atr[0] = tr[0]
    for i in range(1, len(c)):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / n
    mid = (h + l) / 2
    fu, fl = mid + m * atr, mid - m * atr
    d = np.ones(len(c), dtype=int); line = fl.copy()
    for i in range(1, len(c)):
        ub, lb = mid[i] + m * atr[i], mid[i] - m * atr[i]
        fu[i] = ub if (ub < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb if (lb > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = (-1 if c[i] < fl[i] else 1) if d[i - 1] == 1 else (1 if c[i] > fu[i] else -1)
        line[i] = fl[i] if d[i] == 1 else fu[i]
    return d, line


def trend_chart(sym: str, trig: dict | None = None, mkey: str = "NSE") -> go.Figure | None:
    """Daily candles with EMA 9/21 and RSI(14) with the 60 line (the trend-scan view)."""
    ticker = {"NSE": f"{sym}.NS", "ASX": f"{sym}.AX", "US": sym.replace(".", "-")}.get(mkey, sym)
    df, live, _ = fetch_ohlcv(ticker, "1y")
    if not live:
        return None
    df = df.copy()
    df["E9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["E21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["RSI"] = rsi_wilder(df["Close"], 14)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.72, 0.28])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 name=sym, increasing_line_color="#22c55e", decreasing_line_color="#ef4444"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["E9"], name="EMA 9", line=dict(color="#f97316", width=1.6)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["E21"], name="EMA 21", line=dict(color="#3b82f6", width=1.6)), row=1, col=1)
    sd, sl = supertrend_line(df)
    fig.add_trace(go.Scatter(x=df.index, y=np.where(sd == 1, sl, np.nan), name="Supertrend (up)", mode="lines",
                             line=dict(color="#16a34a", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=np.where(sd == -1, sl, np.nan), name="Supertrend (down)", mode="lines",
                             line=dict(color="#dc2626", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI 14", line=dict(color="#8b5cf6", width=1.4)), row=2, col=1)
    for lvl, dash in ((60, "solid"), (40, "dot"), (70, "dot")):
        fig.add_hline(y=lvl, line=dict(color="#a78bfa" if lvl == 60 else "#9ca3af", width=1, dash=dash), row=2, col=1)
    if trig and "signal_date" in trig:
        td = pd.Timestamp(trig["signal_date"])
        fig.add_trace(go.Scatter(x=[td], y=[trig["signal_close"]], mode="markers", name="Early entry signal",
                                 marker=dict(symbol="triangle-up", size=14, color="#2563eb")), row=1, col=1)
        fig.add_hline(y=trig["stop"], line=dict(color="#ef4444", width=1, dash="dash"),
                      annotation_text=f"initial stop {trig['stop']:g}", row=1, col=1)
    elif trig:
        td = pd.Timestamp(trig["trigger_date"])
        fig.add_trace(go.Scatter(x=[td], y=[trig["trigger_close"]], mode="markers", name="Entry trigger",
                                 marker=dict(symbol="triangle-up", size=14, color="#16a34a")), row=1, col=1)
        fig.add_hline(y=trig["stop"], line=dict(color="#ef4444", width=1, dash="dash"),
                      annotation_text=f"stop {trig['stop']:g}", row=1, col=1)
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04), title=f"{sym} · daily · EMA 9/21 · RSI 14")
    fig.update_xaxes(range=[df.index[-130], df.index[-1] + pd.Timedelta(days=3)])
    sub = df.iloc[-130:]
    fig.update_yaxes(range=[sub["Low"].min() * 0.97, sub["High"].max() * 1.03], side="right", row=1, col=1)
    fig.update_yaxes(range=[15, 90], side="right", row=2, col=1)
    return fig


def render_trend_scan_tab(market: MarketConfig | None = None) -> None:
    """NSE trend scanner (nightly): trend entries (EMA 9/21 cross, 52w-high base breakouts), pullback triggers, clear
    trends and watchlist. Click a stock in the list on the left and its chart opens on the right."""
    mkey = market.key if market is not None else "NSE"
    d = load_trend_scan(mkey)
    if not d:
        st.info(f"No trend scan for {market.label if market else 'this market'} yet — it runs every evening after the "
                "market closes. Switch the market in the sidebar to see another one.")
        return
    unit = d.get("value_label", "₹ cr")
    rows, trig = pd.DataFrame(d.get("rows", [])), pd.DataFrame(d.get("triggers", []))
    early = pd.DataFrame(d.get("early", []))
    trend = rows[rows.list == "trend"] if len(rows) else rows
    watch = rows[rows.list == "watch"] if len(rows) else rows
    live = early[early.status.str.startswith(("NEW", "open", "EXIT"))] if len(early) else early
    new = early[early.status.str.startswith("NEW - buy")] if len(early) else early
    st.markdown(f"#### 📈 Trend scan — {d.get('market_label', 'India (NSE)')} close {d.get('asof')}")
    c = st.columns(5)
    c[0].metric("Stocks scanned", f"{d.get('scanned', 0):,}")
    c[1].metric("New entries today", len(new))
    c[2].metric("Open trend trades", int((live.status == "open").sum()) if len(live) else 0,
                f"{int(live.status.str.startswith('EXIT').sum()) if len(live) else 0} to exit next open", delta_color="off")
    c[3].metric("Clear trends", len(trend))
    c[4].metric("Watchlist", len(watch))

    with st.expander("Rules and backtest results"):
        st.markdown(
            "- **🚀 EMA 9/21 cross** (main system): EMA 9 crosses above EMA 21 with Supertrend(10,3) green, close above a "
            "rising EMA 50, RSI ≥ 55, ≥ ₹1 cr/day, within 30% of the 52-week high → buy the next open. Stop = lowest low of "
            "the last 5 sessions (skip if > 12% away). Hold until Supertrend turns red, sell the next open. 1% risk per trade, "
            "max 10 positions, ≤ 20% of capital each. Backtest 2017–26 (all NSE incl. delisted): ~22–26%/yr, worst fall "
            "~−26%, 2022–26 ~14%/yr; 37% of trades win.\n"
            "- **🏔️ 52w-high base breakout**: today's high above the highest close of the prior 240 sessions, close up, "
            "≥ ₹2 cr/day, previous 52-week closing high ≥ 6 months ago, Supertrend green. Stop = 5-day low capped at 12%; "
            "same Supertrend exit. ~15%/yr, worst fall −29%, 2022–26 ~17.6%/yr. Run as a separate pot, not in the same slots.\n"
            "- **🟢 Pullback trigger**: RSI(14) crosses 60 on a bullish candle at EMA 21 — weak in backtests (5%/yr with an "
            "EMA 21 exit). Shown for reference.\n"
            "- **📈 Clear trend / 👀 Watchlist**: close > EMA 9 > EMA 21, EMA 21 rising, ≥ 85% (watch: 70%) of the last 60 "
            "closes above EMA 21, smooth 6-month staircase, near the 52-week high.\n"
            "- Short versions of these setups on F&O stocks lost money in backtests and are not shown.")

    views = {"🚀 Trend entries (new / open / exit)": "early", "🟢 Pullback triggers": "trig",
             "📈 Clear trends": "trend", "👀 Watchlist": "watch"}
    v1, v2, v3, v4 = st.columns([3, 1.1, 1.1, 1.3])
    cat = v1.radio("List", list(views), horizontal=True, key="ts_cat", label_visibility="collapsed")
    size_pick = v4.selectbox("Company size", ["All sizes", "Large", "Mid", "Small", "Micro"], key="ts_size",
                             help="By rank of daily traded value: Large = top 100, Mid = 101–250, Small = 251–500, "
                                  "Micro = the rest. Backtests: small caps were the best single group.")
    kind = views[cat]
    min_val = v2.select_slider(f"Min {unit}/day", options=[0, 1, 2, 5, 10, 25, 50], value=0, key="ts_minval")
    if kind == "early":
        opt = v3.selectbox("Show", ["New, open & exits", "Cross only", "Breakouts only", "All incl. closed"],
                           key="ts_early_show")
        x = early if opt == "All incl. closed" else live
        if opt == "Cross only" and len(x):
            x = x[x.setup.str.startswith("EMA")]
        if opt == "Breakouts only" and len(x):
            x = x[~x.setup.str.startswith("EMA")]
    elif kind == "trig":
        x = trig
    else:
        hide_ext = v3.toggle("Hide extended", value=False, key="ts_hide_ext",
                             help="Hide stocks > 8% above EMA 21 or with RSI > 75")
        x = trend if kind == "trend" else watch
        if hide_ext and len(x):
            x = x[x.tag != "extended"]
    if len(x) and "value_cr" in x:
        x = x[x.value_cr >= min_val]
    if len(x) and size_pick != "All sizes" and "size" in x:
        x = x[x["size"] == size_pick]
    x = x.reset_index(drop=True)

    def label(r) -> str:
        if kind == "early":
            st_ = (r["status"].split(" (")[0].replace(" - buy next open", " → buy next open")
                   .replace("NEW but stop > 12% away - skip unless it opens lower", "NEW, stop > 12% → skip"))
            icon = "🚀" if str(r.get("setup", "")).startswith("EMA") else "🏔️"
            g = "" if pd.isna(r.get("gain_pct")) else f" · {r['gain_pct']:+.1f}%"
            return (f"{icon} {r['symbol']} · {st_}{g} · stop {r['stop']:,.1f} · trail {r['supertrend']:,.1f} · "
                    f"signal {pd.Timestamp(r['signal_date']).strftime('%d %b')}" + (f" · {r['size']}" if isinstance(r.get('size'), str) else ""))
        if kind == "trig":
            return (f"{r['symbol']} · {pd.Timestamp(r['trigger_date']).strftime('%d %b')} · close {r['trigger_close']:,.1f} · "
                    f"stop {r['stop']:,.1f} ({r['risk_pct']}%) · now {r['close']:,.1f}")
        return (f"{r['symbol']} · {r['tag']} · close {r['close']:,.1f} · {r['dist21']:+.1f}% vs EMA21 · RSI {r['rsi']:.0f} · "
                f"3M {r['r3m']:+.0f}%")

    left, right = st.columns([38, 62], gap="medium")
    with left:
        st.markdown(f"##### {cat.split(' (')[0]} — {len(x)} stocks")
        if not len(x):
            st.info("Nothing in this list right now.")
            pick = None
        else:
            labels = [label(r) for _, r in x.iterrows()]
            pk = f"ts_row_{kind}"
            if st.session_state.get(pk, 0) >= len(labels):
                st.session_state[pk] = 0
            with st.container(height=560):
                idx = st.radio("Stocks", list(range(len(labels))), format_func=lambda i: labels[i], key=pk,
                               label_visibility="collapsed")
            pick = x.iloc[idx]
            dl = x.drop(columns=[c_ for c_ in ("spark",) if c_ in x])
            st.download_button(f"Download this list ({len(dl)} rows, CSV)", dl.to_csv(index=False).encode(),
                               file_name=f"trend_scan_{kind}_{d.get('asof')}.csv", mime="text/csv",
                               key=f"ts_dl_{kind}", width="stretch")
            with st.expander("Table view"):
                st.dataframe(dl, width="stretch", hide_index=True)
    with right:
        if pick is not None:
            sym = pick["symbol"]
            info = pick.to_dict() if kind in ("early", "trig") else None
            fig = trend_chart(sym, info, mkey)
            if fig is None:
                st.warning(f"Could not load prices for {sym} right now — try again in a minute.")
            else:
                h1, h2 = st.columns([4, 1])
                nm = pick.get("name") if isinstance(pick.get("name"), str) else ""
                h1.markdown(f"##### {sym} {('— ' + nm) if nm else ''}")
                if h2.button("⛶ Full screen", key=f"ts_fs_{sym}", width="stretch"):
                    _chart_fullscreen(fig, sym)
                fig.update_layout(height=560)
                st.plotly_chart(fig, width="stretch", key=f"ts_chart_{kind}_{sym}", config=CHART_CONFIG)
                if kind == "early":
                    st.caption(f"{pick['setup']} · {pick['status']} · signal {pick['signal_date']} at {pick['signal_close']:,.2f}"
                               f" · initial stop {pick['stop']:,.2f} ({pick['risk_pct']}% risk) · Supertrend trail "
                               f"{pick['supertrend']:,.2f} · {pick['value_cr']:,.1f} {unit}/day")
    st.caption(f"Scanned {d.get('generated', '')} UTC from Yahoo daily data (updates every trading evening ~8 pm IST). "
               "Signals are candidates, not recommendations.")

def main() -> None:
    configure_page()
    init_state()

    market, ticker = render_sidebar()

    # Fill any resting limit orders before drawing anything, so all panels agree.
    for note in process_open_orders(market):
        st.toast(note)

    render_header(market)

    tab_trend, tab_tb, tab_oi, tab_scan, tab1, tab_bt, tab2, tab3 = st.tabs(
        ["📈 Trend scan", "🔁 Top Bottom", "🧲 OI alerts", "🎯 Pattern scanner", "📊 Chart analysis", "🧪 Backtest",
         "🧾 Paper orders", "💼 Portfolio"])
    with tab1:
        render_analysis_tab(market, ticker)
    with tab_scan:
        render_scanner_tab(market)
    with tab_trend:
        render_trend_scan_tab(market)
    with tab_oi:
        render_oi_alerts_tab()
    with tab_bt:
        render_backtest_tab(market)
    with tab_tb:
        st.session_state["_nse_watchlist"] = tuple(MARKETS["India (NSE)"].watchlist)
        _sys.modules["topbottom_tab"].render_topbottom_tab()
    with tab2:
        render_trading_tab(market, ticker)
    with tab3:
        render_portfolio_tab(market)

    st.caption(f"Build {APP_BUILD}")
    st.caption("Simulation only — no orders are sent to any broker. Yahoo Finance data may be "
               "delayed and is for informational purposes.")


if __name__ == "__main__":
    main()
