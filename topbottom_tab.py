"""Streamlit tab: Top Bottom System lab (validation vs the user's sheet + live status)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from topbottom import (TBParams, compare_to_reference, confirmed_swings, match_2017,
                       monthly_points, ref_monthly_series, run_topbottom, tune)

MODES = {
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

SYMBOLS = {"Bank Nifty (^NSEBANK)": "^NSEBANK", "Nifty 50 (^NSEI)": "^NSEI",
           "Fin Nifty (NIFTY_FIN_SERVICE.NS)": "NIFTY_FIN_SERVICE.NS"}


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol: str) -> tuple[pd.DataFrame, str]:
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


def render_topbottom_tab() -> None:
    st.markdown("#### Top Bottom System — closing-line tops & bottoms (stop-and-reverse)")
    st.caption("Tops/bottoms = turning points of the daily close. Buy when price is above the last top, "
               "sell when below the last bottom; the opposite point is the trailing stop. "
               "Results in index points per 1 unit (no lot size).")

    c1, c2, c3 = st.columns([2, 2, 1])
    choice = c1.selectbox("Instrument", list(SYMBOLS) + ["Custom…"], key="tb_sym")
    symbol = SYMBOLS.get(choice) or c1.text_input("Yahoo symbol", "^NSEBANK", key="tb_custom")
    mode = c2.selectbox("Execution model", list(MODES), key="tb_mode",
                        help="\n\n".join(f"**{k}** — {v['help']}" for k, v in MODES.items()))
    kind = c3.radio("Type", ["Index", "Stock"], key="tb_kind", horizontal=False)

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

    tr = run_topbottom(df, p)
    _status(df, tr, p)

    bars = st.radio("Chart window", {"3 months": 63, "6 months": 126, "1 year": 252, "3 years": 756}.keys(),
                    index=1, horizontal=True, key="tb_win")
    nb = {"3 months": 63, "6 months": 126, "1 year": 252, "3 years": 756}[bars]
    st.plotly_chart(_chart(df, tr, p, nb), width="stretch")

    s = _stats(tr)
    if s:
        cols = st.columns(len(s))
        for col, (k, v) in zip(cols, s.items()):
            col.metric(k, v)

    t1, t2, t3 = st.tabs(["📅 Yearly", "✅ Validate vs sheet", "📜 Trades"])
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
        if symbol != "^NSEBANK":
            st.info("The reference sheet is for Bank Nifty — choose Bank Nifty to validate.")
        else:
            st.caption("Sheet = Bank Nifty futures; here = Bank Nifty spot, so prices sit ~25–75 points "
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
