"""Streamlit tab: Nifty weekly 'conclave' ratio system (plan, paper trades, live alerts, backtest)."""
import io
import json
import urllib.request

import pandas as pd
import streamlit as st

RAW = "https://raw.githubusercontent.com/drsinghap81/blank-app"


@st.cache_data(ttl=600, show_spinner=False)
def _get(path: str, branch: str = "main"):
    try:
        with urllib.request.urlopen(f"{RAW}/{branch}/{path}", timeout=8) as r:
            b = r.read().decode()
        return json.loads(b) if path.endswith(".json") else pd.read_csv(io.StringIO(b))
    except Exception:  # noqa: BLE001
        return None


def _f(x, d=0):
    return "-" if x is None else f"{x:,.{d}f}"


def render_ratio_tab() -> None:
    st.markdown("#### 🦋 Nifty weekly ratio (Options Conclave 2022 structure)")
    st.caption("Each weekly series, both sides, held to expiry: call side +1 call ~150 pts ITM, −2 calls ~1.44% OTM, −4 calls ~1.71% OTM; "
               "put side the mirror. Skip the week when the ATM straddle is in the top 20% of its history. Paper-tracked; nothing places orders.")
    p = _get("data/ratio/ratio_weekly.json")
    live = _get("data/live/ratio_live.json", "live")
    if not p:
        st.info("No plan yet - it is published after the first expiry evening the daily job (17:00 IST) runs.")
    else:
        dec = p.get("decision", "?")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Expiry", p["expiry"], f"{p.get('days_to_expiry', '')} days from {p['asof']}")
        c2.metric("This week", dec, "enter on the first day after expiry, near the close" if dec == "TRADE" else "premium unusually high")
        c3.metric("ATM straddle", f"{p['straddle']:.0f} pts", f"{p['straddle_pct_of_future']:.2f}% of Nifty")
        c4.metric("Percentile (skip above)", f"{p.get('percentile', '-')} ({p.get('skip_above_pct', 80)})")
        if p.get("late"):
            st.caption("Plan created late (the job missed the expiry evening).")
        rows = []
        for side, name in (("CE", "Call ratio"), ("PE", "Put ratio")):
            lg = p["legs"][side]; t = "CE" if side == "CE" else "PE"
            pr = lg.get("prices") or [None] * 3
            net = lg.get("net_debit")
            near = "none (net credit kept)" if net is not None and net <= 0 else _f(lg.get("breakeven_near"))
            rows.append({"Side": name, "Buy 1": f"{lg['long']:.0f}{t} @ {_f(pr[0], 1)}", "Sell 2": f"{lg['short2']:.0f}{t} @ {_f(pr[1], 1)}",
                         "Sell 4": f"{lg['short4']:.0f}{t} @ {_f(pr[2], 1)}", "Net (pts, + = debit)": _f(net, 1),
                         "Best at": _f(lg["best_at"]), "Best (₹/set)": _f(lg["best_pts"] * p.get("lot", 65)),
                         "Breakeven (near)": near, "Danger beyond": _f(lg["breakeven_far"])})
        st.markdown(f"**Plan from the {p['asof']} close (Nifty future {p['future']:,.0f})** — strikes re-centre on the entry day:")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if live and live.get("expiry") == p["expiry"]:
            ls = live["live_strikes"]
            st.markdown(f"**Live (Nifty {live['nifty']:,.0f}, {live['time']}, ~15 min delayed)** — strikes at the live index: "
                        f"call +1 {ls['CE'][0]} / −2 {ls['CE'][1]} / −4 {ls['CE'][2]}; put +1 {ls['PE'][0]} / −2 {ls['PE'][1]} / −4 {ls['PE'][2]}. "
                        f"Shift triggers: call long {live['long_strikes']['CE']:.0f}, put long {live['long_strikes']['PE']:.0f}. "
                        f"Danger beyond {live['far_breakevens'][0]:.0f} / {live['far_breakevens'][1]:.0f}.")
            if live.get("alerts_sent"):
                st.caption("Alerts sent this week: " + ", ".join(live["alerts_sent"]))
        if p.get("entered"):
            e = p["entered"]; m = p.get("paper_mtm") or {}
            st.markdown(f"**Paper position** entered {e['date']} at Nifty {e['future']:,.0f}: "
                        f"call {e['legs']['CE']['long']:.0f}/{e['legs']['CE']['short2']:.0f}/{e['legs']['CE']['short4']:.0f}, "
                        f"put {e['legs']['PE']['long']:.0f}/{e['legs']['PE']['short2']:.0f}/{e['legs']['PE']['short4']:.0f}"
                        + (f" — marked {m['date']}: **{m['pts']:+,.0f} pts = ₹{m['rs']:+,.0f}** per set" if m else ""))
        st.caption(f"Lot {p.get('lot', 65)}. Margin {p.get('margin', '')}. Updated {p.get('updated', '')}.")

    paper = _get("data/ratio/paper.csv")
    if paper is not None and len(paper):
        st.markdown("**Paper results (live since Oct 2026)**")
        st.metric("Total", f"₹{paper.pnl_rs.sum():+,.0f}", f"{len(paper)} weeks, {100 * (paper.pnl_rs > 0).mean():.0f}% won")
        st.dataframe(paper.iloc[::-1], hide_index=True, width="stretch")

    bt = _get("data/ratio/backtest.csv")
    if bt is not None and len(bt):
        st.markdown("**Backtest (Mar 2019 – Oct 2026, ₹ per set at lot 65, costs included, entry at the close of the day after expiry)**")
        bt["year"] = pd.to_datetime(bt.expiry).dt.year
        tr = bt[bt.decision == "TRADE"]
        y = tr.groupby("year").agg(weeks=("pnl_rs", "size"), won=("pnl_rs", lambda s: f"{100 * (s > 0).mean():.0f}%"),
                                   total=("pnl_rs", "sum"), worst=("pnl_rs", "min")).reset_index()
        y["skipped"] = bt[bt.decision == "SKIP"].groupby("year").size().reindex(y.year).fillna(0).astype(int).values
        y["total"] = y.total.map(lambda v: f"₹{v:+,.0f}"); y["worst"] = y.worst.map(lambda v: f"₹{v:+,.0f}")
        st.dataframe(y, hide_index=True, width="stretch")
        st.caption(f"Traded weeks {len(tr)}, total ₹{tr.pnl_rs.sum():+,.0f}; the filter skipped {int((bt.decision == 'SKIP').sum())} weeks "
                   f"whose result would have been ₹{bt[bt.decision == 'SKIP'].pnl_rs.sum():+,.0f}.")
    with st.expander("Rules, risks and how the numbers were tested"):
        st.markdown(
            "- **Entry:** first trading day after a weekly expiry, near the close. Both sides, 1 set = 1 + 2 + 4 lots per side.\n"
            "- **Skip filter:** next expiry's ATM straddle on the expiry evening, ÷ √days, above the 80th percentile of its history → no trade that week "
            "(70th–90th all worked; 80th best).\n"
            "- **Exit:** hold to expiry. Optional shift rule: when a side's long goes ATM/OTM, re-set that side 150 pts ITM "
            "(backtest: ~₹2.0L/yr vs ₹2.7L/yr holding over 2019–26; better in 2025–26).\n"
            "- **Backtest with the filter:** ~₹2.5 lakh/yr per set, every year positive since 2019, worst week −₹1.65L, worst losing run −₹1.8L.\n"
            "- **Risk:** it is net short ~5 calls and ~5 puts. A 4%+ week can cost ₹1–3.5L per set (Mar 2020 −₹3.5L without the filter). "
            "Size so that is bearable; margin ≈ ₹8–10L per set.\n"
            "- **Not adopted after testing:** STBT weekend version, monthly/quarterly/December versions, wings, stop-losses.\n"
            "- Source: project note conclave-2022.md; scripts in tools/ratio_weekly.py (daily job) and tools/ratio_alerts.py (15-min alerts).")
