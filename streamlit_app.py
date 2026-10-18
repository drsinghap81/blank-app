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

try:  # yfinance is optional at import time so the app still loads without it
    import yfinance as yf
except Exception:  # pragma: no cover - handled gracefully at runtime
    yf = None


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

STARTING_CASH = 100_000.0     # paper cash per market, in that market's currency
DISPLAY_BARS = 60             # bars shown on the chart (spec: last 60 days)
LOOKBACK_PERIOD = "6mo"       # fetch extra history so SMA/RSI are warmed up
SMA_WINDOW = 20
RSI_WINDOW = 14
CACHE_TTL_SECONDS = 300       # re-fetch prices at most every 5 minutes


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
        watchlist=("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
                   "JPM", "V", "AVGO", "SPY", "QQQ"),
    ),
    "Australia (ASX)": MarketConfig(
        key="ASX", label="Australia (ASX)", suffix=".AX", currency="AUD", symbol="A$",
        benchmark="^AXJO", benchmark_name="S&P/ASX 200",
        watchlist=("CBA.AX", "BHP.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
                   "WES.AX", "MQG.AX", "FMG.AX", "RIO.AX", "WDS.AX", "TLS.AX"),
    ),
    "India (NSE)": MarketConfig(
        key="NSE", label="India (NSE)", suffix=".NS", currency="INR", symbol="₹",
        benchmark="^NSEI", benchmark_name="Nifty 50",
        watchlist=("RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "TCS.NS", "INFY.NS",
                   "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "ITC.NS", "KOTAKBANK.NS",
                   "AXISBANK.NS", "HCLTECH.NS"),
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
        /* ---- base dark surfaces ---- */
        .stApp { background-color: #0b0e14; color: #d7dce5; }
        section[data-testid="stSidebar"] { background-color: #11151d; border-right: 1px solid #1f2633; }
        h1, h2, h3, h4 { color: #e8ecf3 !important; font-weight: 600; }
        /* ---- metric cards ---- */
        .card { background:#121722; border:1px solid #1f2633; border-radius:10px;
                padding:14px 16px; height:100%; }
        .card .lbl { font-size:12px; color:#8a94a6; text-transform:uppercase; letter-spacing:.06em; }
        .card .val { font-size:22px; font-weight:600; color:#f1f4f9; margin-top:4px;
                     font-variant-numeric: tabular-nums; }
        .card .sub { font-size:12px; margin-top:2px; }
        .up { color:#22c55e; } .down { color:#ef4444; } .flat { color:#8a94a6; }
        /* ---- mode badge ---- */
        .mode-badge { display:inline-block; background:#3b2a05; color:#fbbf24;
                      border:1px solid #f59e0b; border-radius:6px; padding:6px 12px;
                      font-weight:700; font-size:13px; letter-spacing:.05em; }
        .data-badge-live { color:#22c55e; font-weight:600; }
        .data-badge-synth { color:#f59e0b; font-weight:600; }
        /* ---- tabs ---- */
        .stTabs [data-baseweb="tab-list"] { gap: 4px; }
        .stTabs [data-baseweb="tab"] { background:#121722; border-radius:6px 6px 0 0;
                                        padding:8px 16px; color:#a6b0c3; }
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
        st.caption(f"{market.label} · prices in {market.currency} · data via Yahoo Finance (delayed)")
    with right:
        st.markdown('<div style="text-align:right;margin-top:10px;">'
                    '<span class="mode-badge">MODE: INTERACTIVE DATA TERMINAL / SIMULATION</span></div>',
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


def build_price_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """Candles + SMA on top, volume in the middle, RSI with 70/30 bands below."""
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

    fig.update_layout(template="plotly_dark", height=640, paper_bgcolor="#0b0e14",
                      plot_bgcolor="#0f131b", margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.04, x=0), xaxis_rangeslider_visible=False,
                      hovermode="x unified")
    fig.update_yaxes(gridcolor="#1f2633")
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_xaxes(gridcolor="#1f2633", rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


def render_analysis_tab(market: MarketConfig, ticker: str) -> None:
    """Tab 1: chart + key stats for the selected instrument."""
    raw, live, msg = fetch_ohlcv(ticker)
    if not live:
        st.warning(f"⚠️ Live data unavailable for **{ticker}** — showing a SYNTHETIC dataset "
                   f"so the terminal keeps working.\n\nReason: {msg}")

    df = add_indicators(raw).tail(DISPLAY_BARS)
    last = df.iloc[-1]
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
    k4.metric("60-day high", f"{sym}{df['High'].max():,.2f}")
    k5.metric("60-day low", f"{sym}{df['Low'].min():,.2f}")

    st.plotly_chart(build_price_chart(df, ticker), width="stretch")

    with st.expander("Raw data (last 60 bars)"):
        show = df[["Open", "High", "Low", "Close", "Volume", f"SMA{SMA_WINDOW}", f"RSI{RSI_WINDOW}"]]
        st.dataframe(show.iloc[::-1].round(2), width="stretch")


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

def main() -> None:
    configure_page()
    init_state()

    market, ticker = render_sidebar()

    # Fill any resting limit orders before drawing anything, so all panels agree.
    for note in process_open_orders(market):
        st.toast(note)

    render_header(market)

    tab1, tab2, tab3 = st.tabs(["📊 Market Analysis", "🧾 Order Execution (Paper)",
                                "💼 Portfolio Tracker"])
    with tab1:
        render_analysis_tab(market, ticker)
    with tab2:
        render_trading_tab(market, ticker)
    with tab3:
        render_portfolio_tab(market)

    st.caption("Simulation only — no orders are sent to any broker. Yahoo Finance data may be "
               "delayed and is for informational purposes.")


if __name__ == "__main__":
    main()
