"""Streamlit tab: Top Bottom System lab (validation vs the user's sheet + live status)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from topbottom import (TBParams, run_tuned, run_live, compare_to_reference, confirmed_swings, match_2017,
                       monthly_points, ref_monthly_series, run_topbottom, tune)

MODES = {
    "Live rules — stop orders ±buffer, 1% day SL, levels used once": dict(trigger="intraday", fill="level",
        safety=True, live=True,
        help="Exactly how the daily calls are traded: buy-stop at prev top + buffer, sell-stop at prev "
             "bottom − buffer, 1% SL on entry day, then SL at the opposite system point (max 2%), "
             "breakeven after +2%, each top/bottom triggers once, >2% gap = no new trade."),
    "Tuned — long only, 0.25% buffer, 2% stop": dict(trigger="intraday", fill="level", safety=True, tuned=True,
        help="Tradable version found by walk-forward testing (tuned on 2007–16, tested on 2017–26): "
             "buy-stop 0.25% above the last top, sell-stop 0.25% below the last bottom or 2% max "
             "stop, no shorts. Bank Nifty spot: profit factor ~1.7 in both periods."),
    "Sheet replication": dict(trigger="close", fill="level", safety=False,
                              help="Signal on the close, booked at the system point — exactly how the "
                                   "sheet was built. Not achievable live (the price is known only after "
                                   "the close has already moved past it)."),
    "Realistic — trade at close": dict(trigger="close", fill="close", safety=False,
                                       help="Signal on the close and you trade at ~3:25 pm at that close."),
    "Realistic — stop orders": dict(trigger="intraday", fill="level", safety=True,
                                    help="Resting stop orders at the system points; fills intraday "
                                         "(or at the open on a gap)."),
}

LOCAL = {"Bank Nifty FUTURES 2017 (NSE bhavcopy)": "data/banknifty_fut_near_2016-2018.csv",
         "Bank Nifty FUTURES 2007–2022 (NSE bhavcopy)": "data/banknifty_fut_near_2007-2022.csv"}
SYMBOLS = {"Bank Nifty — live (^NSEBANK)": "^NSEBANK", "Nifty 50 — live (^NSEI)": "^NSEI",
           "Fin Nifty — live (NIFTY_FIN_SERVICE.NS)": "NIFTY_FIN_SERVICE.NS",
           "Bank Nifty FUTURES 2007–2022 (NSE bhavcopy)": "BNF_FUT_ALL",
           "Bank Nifty FUTURES 2017 (NSE bhavcopy)": "BNF_FUT"}
DEFAULT_BUFFER = {"^NSEBANK": 25.0, "BNF_FUT_ALL": 25.0, "BNF_FUT": 25.0, "^NSEI": 10.0,
                  "NIFTY_FIN_SERVICE.NS": 10.0}

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tools"))
import topbottom_backtest as tbb  # noqa: E402  (single source of truth for the live rules)


LINE_STYLE = {  # name -> (colour, dash)
    "Buy above": ("#00e676", "solid"), "Buy SL (1st day)": ("#00e676", "dot"),
    "Sell below": ("#ff5252", "solid"), "Sell SL (1st day)": ("#ff5252", "dot"),
    "Entry": ("#90caf9", "dash"), "Stop-loss": ("#ffb300", "solid"),
    "Stop-loss (reverse)": ("#ffb300", "solid"), "Breakeven trigger": ("#b39ddb", "dot"),
    "Buy entry": ("#00e676", "dash"), "Sell entry": ("#ff5252", "dash"),
}


def _add_level_lines(fig: go.Figure, lines: dict) -> None:
    for name, y in lines.items():
        if y is None or np.isnan(y):
            continue
        col, dash = LINE_STYLE.get(name, ("#bbbbbb", "dot"))
        fig.add_hline(y=y, line=dict(color=col, dash=dash, width=1.6 if dash == "solid" else 1.1),
                      annotation_text=f"{name}  {y:,.0f}", annotation_position="right",
                      annotation_font=dict(color=col, size=11))


def _next_session_panel(df: pd.DataFrame, tr: pd.DataFrame, lp, name: str) -> dict:
    o = tbb.next_orders(df, tr, lp)
    nxt = (df.index[-1] + pd.offsets.BDay(1)).date()
    st.markdown(f"##### 🧭 Next session ({nxt}) — {name}")
    c = st.columns(4)
    c[0].metric("Last close", f"{o['close']:,.2f}", str(o['date'].date()), delta_color="off")
    c[1].metric("Position", o["position"].split(" ")[0], o["position"].partition(" ")[2] or None,
                delta_color="off")
    c[2].metric("Prev top", f"{o['prev_top']:,.2f}")
    c[3].metric("Prev bottom", f"{o['prev_bottom']:,.2f}")
    box = "\n".join(f"- {x}" for x in o["orders"])
    if o["position"] == "FLAT":
        st.info(box)
    else:
        st.success(f"Open P/L: {o['open_pnl']:+,.0f} points" + ("  •  breakeven SL active" if o.get("breakeven_active") else "") + "\n\n" + box)
    st.session_state["_tb_lines"] = o["lines"]
    st.caption("Levels come from the daily close line of the selected series. Live = Yahoo index (spot) data, "
               "updated after each close; your futures levels differ by the futures premium, so apply the same "
               "logic to the futures chart or add the premium. Not investment advice.")


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol: str) -> tuple[pd.DataFrame, str]:
    if symbol in ("BNF_FUT", "BNF_FUT_ALL"):
        import os
        key = "Bank Nifty FUTURES 2017 (NSE bhavcopy)" if symbol == "BNF_FUT" else "Bank Nifty FUTURES 2007–2022 (NSE bhavcopy)"
        path = os.path.join(os.path.dirname(__file__), LOCAL[key])
        return pd.read_csv(path, index_col=0, parse_dates=True), ""
    try:
        df = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
        if df is None or df.empty:
            return pd.DataFrame(), f"No data for {symbol}"
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close"]].dropna()
        df = df[(df["Close"] > 0)]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df, ""
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), str(exc)


def _stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {}
    pts = tr["Points"]
    pct = pts / tr["Entry"] * 100
    eq = pts.cumsum()
    eqp = pct.cumsum()
    wins, losses = pts[pts > 0], pts[pts <= 0]
    return {
        "Trades": len(tr),
        "Hit rate": f"{100 * len(wins) / len(tr):.0f}%",
        "Total points": f"{pts.sum():,.0f}",
        "Avg win / loss": f"{wins.mean():,.0f} / {losses.mean():,.0f}" if len(losses) else f"{wins.mean():,.0f} / –",
        "Profit factor": f"{wins.sum() / -losses.sum():.2f}" if losses.sum() < 0 else "∞",
        "Max DD (points)": f"{(eq - eq.cummax()).min():,.0f}",
        "Max DD (sum of %)": f"{(eqp - eqp.cummax()).min():.1f}%",
    }


def _chart(df: pd.DataFrame, tr: pd.DataFrame, p: TBParams, bars: int) -> go.Figure:
    c = df["Close"].to_numpy(float)
    _, _, piv = confirmed_swings(c, p.swing_pct)
    view = df.iloc[-bars:]
    start = view.index[0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=view.index, y=view["Close"], mode="lines", name="Close",
                             line=dict(color="#e6e6e6", width=1.4)))
    tops = [(df.index[pi], v) for ci, pi, k, v in piv if k == "T" and df.index[pi] >= start]
    bots = [(df.index[pi], v) for ci, pi, k, v in piv if k == "B" and df.index[pi] >= start]
    if tops:
        fig.add_trace(go.Scatter(x=[t for t, _ in tops], y=[v for _, v in tops], mode="markers",
                                 name="Top", marker=dict(symbol="triangle-down", size=7, color="#ef5350")))
    if bots:
        fig.add_trace(go.Scatter(x=[t for t, _ in bots], y=[v for _, v in bots], mode="markers",
                                 name="Bottom", marker=dict(symbol="triangle-up", size=7, color="#26a69a")))
    if not tr.empty:
        t = tr[pd.to_datetime(tr["EntryDate"]) >= start]
        for side, color, sym in (("BUY", "#00e676", "star"), ("SELL", "#ff1744", "star")):
            s = t[t["Side"] == side]
            fig.add_trace(go.Scatter(x=s["EntryDate"], y=s["Entry"], mode="markers", name=side,
                                     marker=dict(symbol=sym, size=12, color=color,
                                                 line=dict(width=1, color="#000"))))
    fig.update_layout(template="plotly_dark", height=460, margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.08), hovermode="x unified")
    return fig


def _status(df: pd.DataFrame, tr: pd.DataFrame, p: TBParams) -> None:
    c = df["Close"].to_numpy(float)
    T, B, _ = confirmed_swings(c, p.swing_pct)
    last = df.iloc[-1]
    top, bot = T[-1], B[-1]
    pos = "FLAT"
    if not tr.empty and tr.iloc[-1]["Open"]:
        r = tr.iloc[-1]
        pos = f"{'LONG' if r['Side'] == 'BUY' else 'SHORT'} from {r['Entry']:,.2f} ({pd.Timestamp(r['EntryDate']).date()})"
    cols = st.columns(4)
    cols[0].metric("Last close", f"{last['Close']:,.2f}", str(df.index[-1].date()))
    cols[1].metric("Position", pos.split(" ")[0], pos.partition(" ")[2] or None, delta_color="off")
    cols[2].metric("Buy above (top)", f"{top:,.2f}" if not np.isnan(top) else "–",
                   f"{(top / last['Close'] - 1) * 100:+.2f}%" if not np.isnan(top) else None, delta_color="off")
    cols[3].metric("Sell below (bottom)", f"{bot:,.2f}" if not np.isnan(bot) else "–",
                   f"{(bot / last['Close'] - 1) * 100:+.2f}%" if not np.isnan(bot) else None, delta_color="off")


def _ref_grid(tr: pd.DataFrame) -> pd.DataFrame:
    ref = ref_monthly_series()
    mine = monthly_points(tr).reindex(ref.index).fillna(0)
    rows = []
    for y in sorted({p.year for p in ref.index}):
        r = {"Year": y}
        for m in range(1, 13):
            per = pd.Period(f"{y}-{m:02d}", "M")
            if per in ref.index:
                r[per.strftime("%b")] = f"{ref[per]:,.0f} | {mine[per]:,.0f}"
        rows.append(r)
    return pd.DataFrame(rows).set_index("Year")


def _paper_panel() -> None:
    import json
    base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "paper")
    sp, lp_, op = (_os.path.join(base, f) for f in ("summary.json", "ledger.csv", "next_orders.json"))
    if not _os.path.exists(sp):
        st.info("Paper trading starts with the first evening run after the 19 Oct 2026 session "
                "(GitHub job at ~7:10 pm IST). Results will appear here automatically.")
        return
    s = json.load(open(sp))
    st.caption(f"Bank Nifty & Nifty near-month futures, 1 lot each, live rules, est. costs included. "
               f"Started {s['start_date']} • updated {s['updated_ist']} IST • no real orders are placed.")
    k = st.columns(4)
    k[0].metric("Realised P&L", f"₹{s['realised_net']:,.0f}")
    k[1].metric("Open P&L (MTM)", f"₹{s['open_mtm_net']:,.0f}")
    k[2].metric("Trades", s["trades"], f"{s['winners']} W / {s['losers']} L", delta_color="off")
    k[3].metric("Total", f"₹{s['realised_net'] + s['open_mtm_net']:,.0f}")
    if _os.path.exists(op):
        o = json.load(open(op))
        for sym, v in o.items():
            with st.container(border=True):
                st.markdown(f"**{sym} FUT** ({v.get('futures_contract_expiry')} expiry, lot {v.get('lot_size')}) — "
                            f"close {float(v['close']):,.2f} • {v['position']}")
                st.markdown("\n".join(f"- {x}" for x in v["orders"]))
    if _os.path.exists(lp_):
        led = pd.read_csv(lp_)
        if len(led):
            cols = [c for c in ["Instrument", "EntryDate", "Side", "Entry", "ExitDate", "Exit", "Reason",
                                "Points", "Qty", "Gross", "Costs", "Net", "Status"] if c in led]
            st.dataframe(led[cols].iloc[::-1], width="stretch", hide_index=True)


def render_topbottom_tab(stocks: tuple[str, ...] = ()) -> None:
    st.markdown("#### Top Bottom System — closing-line tops & bottoms (stop-and-reverse)")
    st.caption("Tops/bottoms = turning points of the daily close. Buy when price is above the last top, "
               "sell when below the last bottom; the opposite point is the trailing stop. "
               "Results in index points per 1 unit (no lot size).")

    c1, c2, c3 = st.columns([2, 2, 1])
    extra = ("AXISBANK.NS", "TATASTEEL.NS", "RELINFRA.NS", "SHRIRAMFIN.NS", "MANAPPURAM.NS")
    stock_list = sorted(set(stocks) | set(extra))
    stock_labels = {f"{s_.replace('.NS', '')} (stock)": s_ for s_ in stock_list}
    group = c1.radio("Show", ["Indices", "Nifty 50 stocks", "Custom symbol"], horizontal=True, key="tb_group")
    if group == "Indices":
        choice = c1.selectbox("Instrument", list(SYMBOLS), key="tb_sym")
        symbol = SYMBOLS[choice]
    elif group == "Nifty 50 stocks":
        choice = c1.selectbox(f"Stock ({len(stock_labels)})", list(stock_labels), key="tb_stock")
        symbol = stock_labels[choice]
    else:
        symbol = c1.text_input("Yahoo symbol (NSE stocks end in .NS)", "RELIANCE.NS", key="tb_custom").strip()
        choice = symbol
    mode = c2.selectbox("Execution model", list(MODES), key="tb_mode",
                        help="\n\n".join(f"**{k}** — {v['help']}" for k, v in MODES.items()))
    is_stock = not symbol.startswith("^") and symbol not in ("BNF_FUT", "BNF_FUT_ALL", "NIFTY_FIN_SERVICE.NS")
    kind = c3.radio("Rules", ["Index", "Stock"], index=1 if is_stock else 0, key=f"tb_kind_{is_stock}",
                    help="Stock = 1.5% entry-day SL, 3% max SL, 3% breakeven.")

    with st.expander("Fine-tune rules", expanded=False):
        m = MODES[mode]
        f1, f2, f3, f4 = st.columns(4)
        swing = f1.number_input("Glitch filter (min swing %)", 0.0, 5.0, 0.0, 0.1, key="tb_swing",
                                help="0 = every 1-day turn counts (matches the sheet best).")
        trail = f2.selectbox("Stop trailing", ["every", "dow"], key="tb_trail",
                             help="every: stop moves to each new bottom/top. dow: only after a higher top "
                                  "(long) / lower bottom (short) — ignores failed bounces.")
        safety = f3.checkbox("Safety stops", value=m["safety"], key=f"tb_safety_{mode}",
                             help="Max stop, entry-day stop, breakeven.")
        cost = f4.number_input("Cost per trade (points)", 0.0, 200.0, 0.0, 5.0, key="tb_cost")
        idx = kind == "Index"
        g1, g2, g3, g4 = st.columns(4)
        max_stop = g1.number_input("Max stop %", 0.5, 10.0, 2.0 if idx else 3.0, 0.5, key=f"tb_ms_{kind}")
        day_stop = g2.number_input("Entry-day stop %", 0.25, 5.0, 1.0 if idx else 1.5, 0.25, key=f"tb_ds_{kind}")
        be = g3.number_input("Breakeven after %", 0.5, 10.0, 2.0 if idx else 3.0, 0.5, key=f"tb_be_{kind}")
        gap = g4.number_input("Gap rule %", 0.5, 10.0, 2.0, 0.5, key="tb_gap")

    p = TBParams(swing_pct=swing, trigger=m["trigger"], fill=m["fill"], safety=safety,
                 max_stop_pct=max_stop, entry_day_pct=day_stop, breakeven_pct=be, gap_pct=gap,
                 cost_pts=cost, trail_rule=trail)

    with st.spinner(f"Loading full daily history for {symbol}…"):
        df, err = load_history(symbol)
    if df.empty:
        st.error(f"Could not load {symbol}. {err}")
        return

    if m.get("live"):
        if kind == "Index":
            buf = st.number_input("Entry buffer (points beyond top/bottom)", 0.0, 500.0,
                                  DEFAULT_BUFFER.get(symbol, 25.0), 5.0, key=f"tb_buf_{symbol}",
                                  help="Bank Nifty calls use +25 / -25.")
            buf_pct = None
        else:
            buf_pct = st.number_input("Entry buffer (% beyond top/bottom)", 0.0, 2.0, 0.1, 0.05,
                                      key=f"tb_bufpct_{symbol}", help="For stocks a % buffer scales with price.")
            buf = 0.0
        lp = tbb.Params(buffer_pts=buf, buffer_pct=buf_pct, day_sl_pct=day_stop, max_sl_pct=max_stop, be_pct=be,
                        gap_pct=gap, swing_pct=swing, cost_pts=cost)
        tr = tbb.run_live(df, lp)
        _next_session_panel(df, tr, lp, choice)
    elif m.get("tuned"):
        st.caption(f"Tuned mode uses: buffer 0.25%, max stop {max_stop}%, long only, glitch filter {swing}%.")
        tr = run_tuned(df, buffer_pct=0.25, max_stop_pct=max_stop, long_only=True, swing_pct=swing)
    else:
        tr = run_topbottom(df, p)
    st.session_state.setdefault("_tb_lines", {})
    if not m.get("live"):
        st.session_state["_tb_lines"] = {}
        _status(df, tr, p)

    bars = st.radio("Chart window", {"3 months": 63, "6 months": 126, "1 year": 252, "3 years": 756}.keys(),
                    index=1, horizontal=True, key="tb_win")
    nb = {"3 months": 63, "6 months": 126, "1 year": 252, "3 years": 756}[bars]
    fig = _chart(df, tr, p, nb)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    _add_level_lines(fig, st.session_state.get("_tb_lines", {}))
    fig.update_layout(margin=dict(l=10, r=150, t=30, b=10))
    st.plotly_chart(fig, width="stretch")

    s = _stats(tr)
    if s:
        cols = st.columns(len(s))
        for col, (k, v) in zip(cols, s.items()):
            col.metric(k, v)

    t0, t1, t2, t3 = st.tabs(["📒 Paper trading", "📅 Yearly", "✅ Validate vs sheet", "📜 Trades"])
    with t0:
        _paper_panel()
    with t1:
        if not tr.empty:
            y = tr.assign(Year=pd.to_datetime(tr["EntryDate"]).dt.year,
                          Pct=tr["Points"] / tr["Entry"] * 100)
            g = y.groupby("Year").agg(Trades=("Points", "size"), Points=("Points", "sum"),
                                      Pct=("Pct", "sum"), Hit=("Points", lambda s: (s > 0).mean() * 100))
            g = g.round({"Points": 0, "Pct": 1, "Hit": 0})
            g.columns = ["Trades", "Points", "Sum of %", "Hit %"]
            st.dataframe(g, width="stretch")
            st.bar_chart(g["Points"])
    with t2:
        if symbol not in ("^NSEBANK", "BNF_FUT", "BNF_FUT_ALL"):
            st.info("The reference sheet is for Bank Nifty — choose Bank Nifty to validate.")
        else:
            st.caption("Near-month futures from NSE bhavcopies (Nov 2016–Jan 2018): should match the sheet "
                       "to the point. Only differs on 10/11 May 2017, where two near-equal closes form the "
                       "top and the sheet picked the later one." if symbol == "BNF_FUT" else
                       "Sheet = Bank Nifty futures; here = Bank Nifty spot, so prices sit ~25–75 points "
                       "lower and a few borderline days can differ. Monthly P/L is booked by entry month, "
                       "as in the sheet.")
            st.markdown("**2017 trade log — sheet vs this run**")
            st.dataframe(match_2017(tr), width="stretch", hide_index=True)
            cmp_ = compare_to_reference(tr)
            if cmp_.get("months"):
                k = st.columns(4)
                k[0].metric("Months compared", cmp_["months"])
                k[1].metric("Sheet total", f"{cmp_['ref_total']:,.0f}")
                k[2].metric("This run", f"{cmp_['my_total']:,.0f}")
                k[3].metric("Monthly correlation", f"{cmp_['corr']:.2f}")
            st.markdown("**Monthly points — `sheet | this run`**")
            st.dataframe(_ref_grid(tr), width="stretch")
            if st.button("Auto-tune glitch filter & trigger vs sheet", key="tb_tune"):
                with st.spinner("Testing combinations…"):
                    res = tune(df, TBParams(safety=safety, fill="level"), grid=(0, 0.1, 0.2, 0.3, 0.5, 1.0))
                st.dataframe(res.sort_values(["exact_2017", "corr"], ascending=False).round(3),
                             width="stretch", hide_index=True)
    with t3:
        if not tr.empty:
            show = tr.copy()
            show["EntryDate"] = pd.to_datetime(show["EntryDate"]).dt.date
            show["ExitDate"] = pd.to_datetime(show["ExitDate"]).dt.date
            st.dataframe(show.iloc[::-1], width="stretch", hide_index=True)
            st.download_button("Download trades CSV", tr.to_csv(index=False).encode(),
                               f"topbottom_{symbol.strip('^')}.csv", "text/csv")
