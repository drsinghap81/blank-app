"""Paper portfolio: Rs 20 lakh run by every system that is live, from 9 Nov 2026 (26 Nov 2026, Amritpal: "create a section where you
are paper trading with 20 lacs with all winning systems including hedge and without hedge baskets automatically. Factor in pledging.
Start from when we finalised all systems. I want to see how you allocate capital and how it has progressed").

Two books, both Rs 20 L on Mon 9 Nov 2026 (the India mix was finalised on 9 Nov; tested mix "C" in portfolio-mix-pulse-ath-921-tb.md):
  plain  : Pulse rotation 50% + Momentum / Cup 9/21 50% of the investable money
  hedged : Pulse rotation 40% + Momentum / Cup 9/21 40% + gold (GOLDBEES) 10% + US dollar (USD/INR) 10%   (hedging-backtest.md)
  both   : + Top Bottom, 1 lot each of the six live bots - Bank Nifty (buy + sell), Nifty, BEL, L&T, Tata Motors PV, TCS (buy only) -
             on margin from PLEDGED holdings (no capital of their own)
           + the 5-minute option trader (its paper P&L at the lots set in the app)
  reserves (kept in cash, not invested): Rs 3 L for Top Bottom (exchanges want half the margin in cash; the rest comes from the
           pledge) and its daily losses, Rs 1 L for option premiums. Investable = Rs 16 L.
Sleeves (forward record only - nothing here is a backtest):
  Momentum / Cup 9/21 : the setups the app logged night by night (data/scan/setup_log.json, systems 'Monthly ATH' and 'Trend 9/21'),
           at the logged entry, stop and exit; size = 1% of the book's value at risk to the stop, max 10% of the book a stock, max
           10 open, only while the sleeve has cash (else 'skipped: sleeve full'). 0.2% cost a side.
  Pulse rotation : the live rule replayed each Friday from 6 Nov (top-10% Pulse industries that are Leading / Improving, the 10
           strongest trending stocks by 3-month return, kept while in the top 20), equal weight, bought / sold at Monday's open,
           0.2% a side. (The traffic-light RED skip is not replayed; the light was not RED in this period.)
  Top Bottom : each live bot's rules replayed tick-path on its daily near-month future (tools/angel/sim_check.py, real 1% entry-day
           stop), started flat on 9 Nov, 1 lot (the lot size in data/futures), 0.03% of notional a round trip. Margin ~12% of the
           notional for index futures, ~20% for stock futures.
  Option trader : its paper result per day from the server's public summary (/api/public/opt_paper); started 19 Nov.
  Gold / USD : bought on 9 Nov, held (rebalanced to 10% each at the start of each month).
Pledge: stock holdings count at 80% of value, GOLDBEES at 90% (typical haircuts); half of the Top Bottom margin must be cash (the reserve plus
Top Bottom's own gains), the other half from the pledge. A shortfall is flagged.
Output: data/scan/paper20.json (equity per day, sleeves, positions, closed trades, a log of what was done and why). Nightly."""
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "angel"))
import nse_bhav; nse_bhav.install()  # noqa: E402,E702

OUT = "data/scan/paper20.json"
START = pd.Timestamp("2026-11-09"); CAP = 2_000_000.0
RES_TB, RES_OPT = 300_000.0, 100_000.0
COST = 0.002; TB_COST = 0.0003; HAIR = {"stock": 0.8, "gold": 0.9}
BOOKS = {"plain": {"pulse": 0.5, "ath": 0.5}, "hedged": {"pulse": 0.4, "ath": 0.4, "gold": 0.1, "usd": 0.1}}
OPT_URL = os.environ.get("OPT_PAPER_URL", "https://13-126-118-48.sslip.io/api/public/opt_paper")
MINVAL, MINPX, N, BUF = 1e7, 50, 10, 20
SYS_OK = {"Monthly ATH": "Momentum", "Trend 9/21": "Cup 9/21"}


def load(p, d=None):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def download(syms):
    C, O, V = {}, {}, {}
    for a in range(0, len(syms), 100):
        ch = syms[a:a + 100]
        for k in range(3):
            try:
                d = yf.download(ch, period="2y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
                for t in ch:
                    if t in d["Close"].columns and d["Close"][t].notna().sum() > 20:
                        C[t] = d["Close"][t]; O[t] = d["Open"][t]; V[t] = d["Volume"][t]
                break
            except Exception as e:  # noqa: BLE001
                print("retry", e)
    C = pd.DataFrame(C); O = pd.DataFrame(O).reindex(C.index); V = pd.DataFrame(V).reindex(C.index)
    C.index = pd.to_datetime(C.index).tz_localize(None); O.index = C.index; V.index = C.index
    return C.sort_index(), O.sort_index(), V.sort_index()


# ---------------------------------------------------------------- Pulse rotation (same formulas as tools/pulse_rot.py)
def pulse_picks(C, V, nifty, IND, since=None):
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    liq = ((C * V).rolling(60, min_periods=40).median() >= MINVAL) & (C >= MINPX)
    rpi = lambda k: 100 * (C / C.shift(k)).div(nifty / nifty.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = (w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52) & liq
    r63 = C / C.shift(63) - 1
    idx, pul, mem = {}, {}, {}
    for k, v in IND.items():
        m = [s for s in v if s in C.columns]
        if len(m) < 3:
            continue
        mem[k] = m
        idx[k] = (1 + ret[m].mean(axis=1).fillna(0)).cumprod()
        pul[k] = (tr[m].astype(float).where(C[m].notna()).where(liq[m])).mean(axis=1).mul(100).rolling(21, min_periods=15).mean()
    idx = pd.DataFrame(idx); pul = pd.DataFrame(pul)
    fri = sorted({C.index[C.index.get_indexer([d], method="pad")[0]] for d in idx.resample("W-FRI").last().index if d >= C.index[0]})
    W = idx.loc[fri]; NW = nifty.loc[fri]; PW = pul.loc[fri]
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    out, held = {}, []
    for d in [f for f in fri if f >= (since or START) - pd.Timedelta(days=4) and f.weekday() == 4]:
        pct = PW.loc[d].rank(pct=True)
        sel = [k for k in PW.columns if pct.get(k, 0) >= 0.9 and np.isfinite(mom.loc[d, k]) and mom.loc[d, k] >= 100]
        cand = [s for k in sel for s in mem[k] if bool(tr.loc[d, s])]
        rk = sorted(set(cand), key=lambda s: -(r63.loc[d, s] if np.isfinite(r63.loc[d, s]) else -9))
        keep = [s for s in held if s in set(rk[:BUF])]
        for s in rk:
            if len(keep) >= N:
                break
            if s not in keep:
                keep.append(s)
        held = keep; out[d] = dict(picks=list(keep), inds=sel)
    return out


# ---------------------------------------------------------------- Top Bottom Bank Nifty (live bot logic, tick paths)
TB_SET = [("BANKNIFTY", {}, 0.12), ("NIFTY", dict(buffer_pts=12, long_only=True), 0.12)] + \
    [(x, dict(long_only=True, buffer_pts=0, buffer_pct=0.05, glitch_pts=0, use_once=True, gap_pct=1.5), 0.20) for x in ("BEL", "LT", "TMPV", "TCS")]


def top_bottom(sym, over, start=None):
    """one Top Bottom bot (the live settings: Bank Nifty buy + sell; Nifty and the stock futures buy only) replayed from START"""
    import sim_check as sc
    import tb_live as tl
    raw = pd.read_csv(os.path.join(f"data/futures/{sym}.csv"), index_col=0, parse_dates=True)
    lot = int(float(raw["Lot"].dropna().iloc[-1])) if "Lot" in raw and raw["Lot"].notna().any() else 30
    df = raw[["Open", "High", "Low", "Close"]].dropna()
    cfg = dict(tl.DEFAULT_CFG, entry_day_sl="intraday", dry_run=True, lots=1, **over)
    start = start or START
    st = tl.init_flat_state(df[df.index < start], cfg); br = sc.FakeBroker(); daily = {}; log = []
    for d in df.index[df.index >= start]:
        bar = df.loc[d]
        day = tl.TradingDay(d.date(), df[df.index < d], st, cfg, br, sc.Quiet(), sc.AutoYes(), log=lambda *a: None)
        day.start(); hi = lo = None; first = True
        for px in sc.path(bar.Open, bar.High, bar.Low, bar.Close):
            br.px = px; hi = px if hi is None else max(hi, px); lo = px if lo is None else min(lo, px)
            q = dict(ltp=px, open=bar.Open, high=hi, low=lo)
            if first:
                day.on_open(q); first = False
            else:
                day.tick(q)
        day.before_close(dict(ltp=bar.Close, open=bar.Open, high=bar.High, low=bar.Low))
        day.end_of_day(dict(Open=bar.Open, High=bar.High, Low=bar.Low, Close=bar.Close))
        cl = [t for t in st.trades if t.get("ExitDate")]
        real = sum((t.get("Points") or 0) for t in cl) * lot - sum(TB_COST * (t.get("Exit") or bar.Close) * lot for t in cl)
        opn = (st.pos * (bar.Close - st.entry) * lot) if st.pos else 0.0
        daily[d.normalize()] = dict(pnl=real + opn, pos=int(st.pos), entry=float(st.entry or 0), close=float(bar.Close), lot=lot)
    nm = {"BANKNIFTY": "Bank Nifty", "NIFTY": "Nifty"}.get(sym, sym)
    for t in st.trades:
        log.append((str(t["EntryDate"])[:10], f"Top Bottom {nm}: {'bought' if t.get('Side') == 'BUY' else 'sold short'} 1 lot ({lot}) at {t.get('Entry', 0):,.2f} - {t.get('Signal', '')}"))
        if t.get("ExitDate"):
            log.append((str(t["ExitDate"])[:10], f"Top Bottom {nm}: closed {t.get('Points', 0):+,.2f} pts (Rs {(t.get('Points') or 0) * lot:+,.0f}) - {t.get('Reason', '')}"))
    trades = [dict(t, sym=sym, lot=lot) for t in st.trades if t.get("ExitDate")]
    return daily, trades, log, dict(pos=int(st.pos), entry=float(st.entry or 0), lot=lot)


def opt_paper(prev):
    try:
        j = requests.get(OPT_URL, timeout=40).json()
        if "days" not in j:
            raise RuntimeError(f"no days in the answer: {str(j)[:120]}")
        days = {d["day"]: d for d in j.get("days") or [] if d.get("day") >= str(START.date())}
        return days, j.get("lots"), True
    except Exception as ex:  # noqa: BLE001
        print("option paper summary not reachable:", ex)
        return {d["day"]: d for d in (prev.get("opt_days") or [])}, prev.get("opt_lots"), False


REC = {"momcup": 0.40, "flags": 0.20, "pulse": 0.10, "gold": 0.10, "us_rsi2": 0.10, "us_tb_etf": 0.10}
REC_NM = {"momcup": "Momentum + Cup 9/21", "flags": "Flags", "pulse": "Pulse rotation", "gold": "Gold", "us_rsi2": "US RSI(2)", "us_tb_etf": "US Top Bottom ETFs"}


def rec_book(days, PP, Cp, Op, gold, TBd, OPd, TBtr, TBopen, TBlog, nifty):
    """26 Nov 2026 (Amritpal: "Yes" to switching the paper book to the tested split): Momentum + Cup with TODAY's rules (close
    confirmation + industry-lane skip), Flags (live rule), Pulse rotation, gold, US RSI(2) dip-buys and US Top Bottom ETFs (both in Rupees,
    as sleeve values), plus the six Top Bottom bots on pledge and the option trader. Equal slots: a sleeve's money / 10 a stock, max 10.
    Tested in tools/research/combo_compare.py (claude/system-combinations-and-allocation.md): since 2017 35.7%/yr, worst fall -14%;
    since 2025 31.0%/yr, -24% (fresh Rs 20 L each window, with Top Bottom)."""
    sys.path.insert(0, os.path.join(HERE, "research"))
    import combo_compare as CC
    AC = CC.AC; AC.KEEP_OPEN = True
    nif = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze(); nif.index = pd.to_datetime(nif.index).tz_localize(None)
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index(); V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, V = C[ok], V[ok]
    G = load("data/scan/group_pulse.json"); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    LN = CC.lanes(C, V, nif.reindex(C.index).ffill(), IND)
    T = []
    since = START - pd.Timedelta(days=400)
    for sym, x in P.items():
        try:
            for t in AC.trades_for(sym, x, reg):
                if t["d"] >= START and ((t["sys"] == "tf" and t["v"] == "B") or (t["sys"] == "mom" and t["v"] == "C")):
                    g = ind_of.get(sym); i = LN.index.searchsorted(t["d"]) - 1
                    lane = LN[g].iloc[i] if g in LN.columns and i >= 0 else "none"
                    T.append(dict(sym=sym, sl="momcup", sys="Momentum" if t["sys"] == "mom" else "Cup 9/21", d=t["d"], dx=t["dx"], e=t["e"], x=t["x"], open=t["open"],
                                  skip=lane in ("weak", "fade", "bounce"), lane=lane))
            for t in CC.flags(sym, x):
                if t["d"] >= START:
                    T.append(dict(sym=sym, sl="flags", sys="Flag", d=t["d"], dx=t["dx"], e=t["e"], x=t["x"], open=t["open"], skip=False, lane=None))
        except Exception as ex:  # noqa: BLE001
            print("rec err", sym, ex)
    # Pulse rotation holdings as trades
    cur = {}
    for f in sorted(PP):
        nxt = [d for d in days if d > f]
        if not nxt:
            break
        dd = nxt[0]; want = set(PP[f]["picks"])
        for s_ in list(cur):
            if s_ not in want:
                e, d0 = cur.pop(s_); xp = Op.at[dd, s_] if s_ in Op.columns and np.isfinite(Op.at[dd, s_]) else Cp.at[dd, s_]
                T.append(dict(sym=s_, sl="pulse", sys="Pulse rotation", d=d0, dx=dd, e=e * (1 + COST), x=float(xp) * (1 - COST), open=False, skip=False, lane=None))
        for s_ in want:
            if s_ not in cur and s_ in Op.columns and np.isfinite(Op.at[dd, s_]):
                cur[s_] = (float(Op.at[dd, s_]), dd)
    for s_, (e, d0) in cur.items():
        T.append(dict(sym=s_, sl="pulse", sys="Pulse rotation", d=d0, dx=days[-1] + pd.Timedelta(days=1), e=e * (1 + COST), x=None, open=True, skip=False, lane=None))
    try:
        ru, tu = CC.us_curves()
    except Exception as ex:  # noqa: BLE001
        print("us curves", ex); ru = tu = None
    inv = CAP - RES_TB - RES_OPT
    cash = {k: REC[k] * inv for k in ("momcup", "flags", "pulse")}; cash["reserve"] = RES_TB + RES_OPT
    ext = {}
    for k, ser in (("gold", gold), ("us_rsi2", ru), ("us_tb_etf", tu)):
        if ser is None:
            cash[k] = REC[k] * inv; continue
        ser = ser.copy(); ser.index = pd.to_datetime(ser.index).tz_localize(None) if getattr(ser.index, "tz", None) else pd.to_datetime(ser.index)
        base = ser[ser.index <= days[0]].dropna()
        ext[k] = (REC[k] * inv / float(base.iloc[-1]), ser) if len(base) else None
        if not ext[k]:
            cash[k] = REC[k] * inv
    hold, closed, log, eq = {}, [], [], []; nif0 = None; opt_cum = 0.0
    for k in ("gold", "us_rsi2", "us_tb_etf"):
        if ext.get(k):
            log.append((str(days[0].date()), f"{REC_NM[k]}: put Rs {REC[k] * inv:,.0f} in ({REC[k] * 100:.0f}%)"))
    T = sorted(T, key=lambda t: (pd.Timestamp(t["d"]), t["sl"], t["sym"]))
    for d in days:
        ds = str(d.date())
        def px(s_):
            v = C.at[d, s_] if s_ in C.columns and d in C.index else (Cp.at[d, s_] if s_ in Cp.columns and d in Cp.index else np.nan)
            return float(v) if v is not None and np.isfinite(v) else None
        for k_ in [k_ for k_, h in hold.items() if h["dx"] <= d and not h["open"]]:
            h = hold.pop(k_); cash[h["sl"]] += h["q"] * h["x"]
            closed.append(dict(sym=h["sym"], sleeve=h["sl"], sys=h["sys"], d=h["d"], dx=ds, e=round(h["e"], 2), x=round(h["x"], 2), qty=h["q"], pnl=round(h["q"] * (h["x"] - h["e"])),
                               why="system exit"))
            log.append((ds, f"{h['sys']}: sold {h['sym']} ({(h['x'] / h['e'] - 1) * 100:+.1f}%)"))
        val = sum(cash.values()) + sum(h["q"] * h["last"] for h in hold.values()) + sum(u * float(sr.reindex([d], method="ffill").iloc[0]) for u, sr in [ext[k] for k in ext if ext[k]]) \
            + TBd.get(d, {}).get("pnl", 0.0) + opt_cum
        for t in [t for t in T if pd.Timestamp(t["d"]).normalize() == d]:
            if t["skip"]:
                log.append((ds, f"{t['sys']}: {t['sym']} skipped - industry lane {t['lane']}")); continue
            sl = t["sl"]; key = f"{sl}:{t['sym']}"
            if key in hold:
                continue
            if len([1 for h in hold.values() if h["sl"] == sl]) >= 10:
                log.append((ds, f"{t['sys']}: {t['sym']} skipped - 10 positions open")); continue
            amt = min(REC[sl] * val / 10, cash[sl])
            if amt < 0.5 * REC[sl] * val / 10:
                log.append((ds, f"{t['sys']}: {t['sym']} skipped - sleeve full (no cash)")); continue
            q = math.floor(amt / t["e"])
            if q <= 0:
                continue
            cash[sl] -= q * t["e"]
            hold[key] = dict(sym=t["sym"], sl=sl, sys=t["sys"], q=q, e=t["e"], x=t["x"] if t["x"] is not None else t["e"], dx=pd.Timestamp(t["dx"]).normalize(), d=ds, last=t["e"],
                             open=bool(t["open"]))
            log.append((ds, f"{t['sys']}: bought {q} {t['sym']} at {t['e']:,.2f} ({amt / val * 100:.1f}% of the book)"))
        for h in hold.values():
            v = px(h["sym"])
            if v:
                h["last"] = v
        if ds in OPd:
            opt_cum += OPd[ds]["pnl"]
        sv = {k: cash.get(k, 0) + sum(h["q"] * h["last"] for h in hold.values() if h["sl"] == k) for k in ("momcup", "flags", "pulse")}
        for k in ("gold", "us_rsi2", "us_tb_etf"):
            sv[k] = (ext[k][0] * float(ext[k][1].reindex([d], method="ffill").iloc[0])) if ext.get(k) else cash.get(k, 0.0)
        sv["top_bottom"] = TBd.get(d, {}).get("pnl", 0.0); sv["options"] = opt_cum; sv["reserve"] = cash["reserve"]
        tot = sum(sv.values()); nif0 = nif0 or float(nifty[d])
        stocks = sum(h["q"] * h["last"] for h in hold.values()); pledge = HAIR["stock"] * stocks + HAIR["gold"] * sv["gold"]
        need = TBd.get(d, {}).get("margin", 0.0)
        eq.append(dict(d=ds, v=round(tot), nifty=round(CAP * float(nifty[d]) / nif0), sleeves={k: round(v) for k, v in sv.items()},
                       pledge=round(pledge), margin=round(need), margin_ok=bool(need / 2 <= cash["reserve"] - RES_OPT + max(0, sv["top_bottom"]) and need / 2 <= pledge)))
    log += TBlog
    for t in TBtr:
        closed.append(dict(sym=f"{t['sym']} FUT", sleeve="top_bottom", sys="Top Bottom", d=str(t.get("EntryDate"))[:10], dx=str(t.get("ExitDate"))[:10],
                           e=t.get("Entry"), x=t.get("Exit"), qty=t["lot"], pnl=round((t.get("Points") or 0) * t["lot"]), why=t.get("Reason") or ""))
    pos = [dict(sym=h["sym"], sleeve=h["sl"], sys=h["sys"], qty=h["q"], e=round(h["e"], 2), last=round(h["last"], 2), d=h["d"], value=round(h["q"] * h["last"]),
                pnl=round(h["q"] * (h["last"] - h["e"])), pct=round((h["last"] / h["e"] - 1) * 100, 2), stop=None) for h in hold.values()] + TBopen
    V0 = eq[-1]["v"]; peak = 0; dd = 0.0
    for x in eq:
        peak = max(peak, x["v"]); dd = min(dd, x["v"] / peak - 1)
    start_alloc = dict(**{k: round(REC[k] * inv) for k in REC}, reserve_top_bottom=RES_TB, reserve_options=RES_OPT)
    return dict(weights=REC, start_alloc=start_alloc, equity=eq, positions=sorted(pos, key=lambda p: (p["sleeve"], -(p["value"] or 0))),
                closed=sorted(closed, key=lambda c_: c_.get("dx") or ""), log=[dict(d=a, t=b) for a, b in sorted(log, key=lambda x: x[0], reverse=True)][:250],
                summary=dict(value=V0, ret_pct=round((V0 / CAP - 1) * 100, 2), nifty_pct=round((eq[-1]["nifty"] / CAP - 1) * 100, 2), max_dd_pct=round(dd * 100, 2), days=len(eq),
                             sleeve_pnl={k: round(eq[-1]["sleeves"][k] - (start_alloc.get(k, 0) if k in REC else (RES_TB + RES_OPT if k == "reserve" else 0))) for k in eq[-1]["sleeves"]}))


def main():
    G = load("data/scan/group_pulse.json"); SL = load("data/scan/setup_log.json"); prev = load(OUT)
    IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
        if len(liq) >= 3:
            IND[r["basic"]] = liq
    rows = [r for r in SL.get("rows") or [] if r.get("sys") in SYS_OK and r.get("d0") and r.get("e")]
    syms = sorted({s for v in IND.values() for s in v} | {r["sym"] for r in rows})
    C, O, V = download([s + ".NS" for s in syms] + ["GOLDBEES.NS", "INR=X", "^NSEI"])
    C.columns = [c.replace(".NS", "") for c in C.columns]; O.columns = C.columns; V.columns = [c.replace(".NS", "") for c in V.columns]
    stk = [c for c in C.columns if c not in ("^NSEI", "INR=X", "GOLDBEES")]
    ok = C[stk].notna().mean(axis=1) > 0.5; C, O, V = C[ok], O[ok], V[ok]   # Indian sessions only (FX rows on NSE holidays break the rolling windows)
    try:                                                                       # Yahoo's Nifty can lag a day: NSE's own close fills it
        ix = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"]); ix = ix[ix.INDEX == "NIFTY 50"].set_index("Date").Close
        C["^NSEI"] = C["^NSEI"].fillna(ix.reindex(C.index))
    except Exception as ex:  # noqa: BLE001
        print("nifty fill", ex)
    nifty = C["^NSEI"].ffill(); days = list(C.index[C.index >= START])
    if not days:
        raise SystemExit("no trading days since the start")
    stock_cols = [s for s in syms if s in C.columns]
    PP = pulse_picks(C[stock_cols], V.reindex(columns=stock_cols), nifty, IND)
    print("pulse industries", len(IND), "stocks", len(stock_cols), "decisions", {str(k.date()): v["picks"] for k, v in PP.items()})
    TBall = {}
    for sym, over, mpct in TB_SET:
        try:
            dly, trs, lg, now = top_bottom(sym, over)
            TBall[sym] = (dly, trs, lg, now, mpct)
        except Exception as ex:  # noqa: BLE001
            print("top bottom", sym, ex)
    TBd = {}; TBtr = []; TBlog = []; TBopen = []
    for sym, (dly, trs, lg, now, mpct) in TBall.items():
        TBtr += trs; TBlog += lg
        for d in days:                                 # the futures file can lag a session: carry the last known mark forward
            k_ = max([x for x in dly if x <= d], default=None); x = dly.get(k_, {}) if k_ is not None else {}
            agg = TBd.setdefault(d, dict(pnl=0.0, margin=0.0))
            agg["pnl"] += x.get("pnl", 0.0)
            if x.get("pos"):
                agg["margin"] += mpct * x["close"] * x["lot"]
        if now["pos"]:
            last = [dly[k] for k in sorted(dly)][-1]
            TBopen.append(dict(sym=f"{sym} FUT", sleeve="top_bottom", sys="Top Bottom", qty=now["lot"] * now["pos"], e=now["entry"], last=last["close"], value=None,
                               pnl=round(now["pos"] * (last["close"] - now["entry"]) * now["lot"]), pct=round(now["pos"] * (last["close"] / now["entry"] - 1) * 100, 2), d=None, stop=None))
    OPd, OPlots, OPok = opt_paper(prev)
    usd = C["INR=X"].ffill(); gold = C["GOLDBEES"].ffill()
    res = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=str(days[-1].date()), start=str(START.date()),
               capital=CAP, reserves=dict(top_bottom=RES_TB, options=RES_OPT), method=__doc__, opt_days=list(OPd.values()), opt_lots=OPlots,
               opt_live=OPok, books={})
    for bk, Wt in BOOKS.items():
        inv = CAP - RES_TB - RES_OPT
        cash = {k: Wt[k] * inv for k in Wt}; cash["reserve"] = RES_TB + RES_OPT
        hold = {}                     # sym -> dict(sleeve, qty, e, d, s, sys)
        closed, log, eq, nif0 = [], [], [], None
        units = {"gold": 0.0, "usd": 0.0}
        pulse_next = None
        opt_cum = 0.0
        for di, d in enumerate(days):
            ds = str(d.date()); px = C.loc[d]; op = O.loc[d]

            def val(k_):                                     # holdings are keyed "sleeve:SYMBOL" (a stock can sit in two sleeves)
                v = px.get(k_.split(":", 1)[-1])
                return float(v) if v is not None and np.isfinite(v) else hold[k_]["last"]
            # gold / usd: buy on day one at the open
            if di == 0:
                for k, ser in (("gold", gold), ("usd", usd)):
                    if k in Wt and np.isfinite(ser.get(d, np.nan)):
                        units[k] = cash[k] / float(ser[d]); cash[k] = 0.0          # at the day's close (the open of ETFs / FX is unreliable on Yahoo)
                        log.append((ds, f"{'Gold (GOLDBEES)' if k == 'gold' else 'US dollar'}: put Rs {Wt[k] * inv:,.0f} in ({Wt[k] * 100:.0f}% hedge)"))
            # Pulse rotation: trade at this open the picks decided at the previous Friday
            dec = [f for f in PP if f < d]
            if dec and (pulse_next is None or dec[-1] != pulse_next):
                pulse_next = dec[-1]; want = PP[pulse_next]["picks"]
                cur = [k_[6:] for k_, h in hold.items() if h["sleeve"] == "pulse"]
                for s in cur:
                    if s not in want:
                        h = hold.pop("pulse:" + s); p = float(op.get(s) or val("pulse:" + s)) * (1 - COST); cash["pulse"] += h["qty"] * p
                        closed.append(dict(sym=s, sleeve="pulse", sys="Pulse rotation", d=h["d"], dx=ds, e=h["e"], x=round(p, 2), qty=h["qty"],
                                           pnl=round(h["qty"] * (p - h["e"])), why="left the top 20 / its industry dropped out"))
                        log.append((ds, f"Pulse rotation: sold {s} at the open ({(p / h['e'] - 1) * 100:+.1f}%) - left the weekly list"))
                new = [s for s in want if "pulse:" + s not in hold]
                if new:
                    slot = (cash["pulse"] + sum(hold[k_]["qty"] * val(k_) for k_ in hold if hold[k_]["sleeve"] == "pulse")) / N
                    for s in new:
                        p = float(op.get(s)) if op.get(s) is not None and np.isfinite(op.get(s)) else None
                        if not p:
                            continue
                        q = math.floor(min(slot, cash["pulse"]) / (p * (1 + COST)))
                        if q <= 0:
                            log.append((ds, f"Pulse rotation: no cash left for {s}")); continue
                        cash["pulse"] -= q * p * (1 + COST)
                        hold["pulse:" + s] = dict(sleeve="pulse", sys="Pulse rotation", qty=q, e=round(p * (1 + COST), 2), d=ds, s=None, last=p)
                    log.append((ds, f"Pulse rotation (decided {pulse_next.date()}): bought {', '.join(new)}; holding {len([1 for h in hold.values() if h['sleeve'] == 'pulse'])}"))
            # Momentum / Cup 9/21 from the forward log
            book_val = sum(cash.values()) + sum(h["qty"] * val(s) for s, h in hold.items()) + units["gold"] * float(gold.get(d, 0) or 0) \
                + units["usd"] * float(usd.get(d, 0) or 0) + (TBd.get(d, {}).get("pnl", 0)) + opt_cum
            for r in rows:
                key = r["sym"]
                if r["d0"] == ds and "ath:" + key not in hold and not any(c_["sym"] == key and c_["sleeve"] == "ath" and c_["d"] == ds for c_ in closed):
                    e, s_ = float(r["e"]), float(r["s"])
                    nopen = len([1 for h in hold.values() if h["sleeve"] == "ath"])
                    if e <= s_ or nopen >= 10:
                        log.append((ds, f"{SYS_OK[r['sys']]}: {key} skipped - {'10 positions open' if nopen >= 10 else 'bad stop'}")); continue
                    q = math.floor(min(0.01 * book_val / (e - s_), 0.10 * book_val / e, cash["ath"] / (e * (1 + COST))))
                    if q <= 0 or q * e < 0.03 * book_val:            # no token positions: at least 3% of the book
                        log.append((ds, f"{SYS_OK[r['sys']]}: {key} skipped - sleeve full (no cash)")); continue
                    cash["ath"] -= q * e * (1 + COST)
                    hold["ath:" + key] = dict(sleeve="ath", sys=SYS_OK[r["sys"]], qty=q, e=round(e * (1 + COST), 2), d=ds, s=s_, last=e, row=r["id"])
                    log.append((ds, f"{SYS_OK[r['sys']]}: bought {q} {key} at {e:,.2f}, stop {s_:,.2f} (risk {q * (e - s_) / book_val * 100:.2f}% of the book)"))
            for k_, h in list(hold.items()):
                if h["sleeve"] != "ath":
                    continue
                s = k_[4:]
                r = next((x for x in rows if x["id"] == h.get("row")), None)
                if r and r.get("st") in ("stop", "exit", "target") and r.get("end") == ds:
                    p = float(r["e"]) * (1 + float(r.get("ret") or 0) / 100) * (1 - COST); cash["ath"] += h["qty"] * p; hold.pop(k_)
                    closed.append(dict(sym=s, sleeve="ath", sys=h["sys"], d=h["d"], dx=ds, e=h["e"], x=round(p, 2), qty=h["qty"],
                                       pnl=round(h["qty"] * (p - h["e"])), why={"stop": "stop hit", "exit": "system exit", "target": "target"}[r["st"]]))
                    log.append((ds, f"{h['sys']}: sold {s} ({(p / h['e'] - 1) * 100:+.1f}%) - {closed[-1]['why']}"))
            # options: that day's paper P&L
            if ds in OPd:
                opt_cum += OPd[ds]["pnl"]
                if OPd[ds]["n"]:
                    log.append((ds, f"Option trader: {OPd[ds]['n']} trade{'s' if OPd[ds]['n'] > 1 else ''}, paper Rs {OPd[ds]['pnl']:+,.0f}"))
            for s, h in hold.items():
                h["last"] = val(s)
            sv = {k: cash.get(k, 0) + sum(h["qty"] * h["last"] for h in hold.values() if h["sleeve"] == k) for k in ("pulse", "ath")}
            sv["gold"] = units["gold"] * float(gold.get(d, 0) or 0); sv["usd"] = units["usd"] * float(usd.get(d, 0) or 0)
            sv["top_bottom"] = TBd.get(d, {}).get("pnl", 0.0); sv["options"] = opt_cum; sv["reserve"] = cash["reserve"]
            tot = sum(sv.values()); nif0 = nif0 or float(nifty[d])
            stocks = sum(h["qty"] * h["last"] for h in hold.values())
            pledge = HAIR["stock"] * stocks + HAIR["gold"] * sv["gold"]
            need = TBd.get(d, {}).get("margin", 0.0)
            eq.append(dict(d=ds, v=round(tot), nifty=round(CAP * float(nifty[d]) / nif0), sleeves={k: round(v) for k, v in sv.items()},
                           pledge=round(pledge), margin=round(need), margin_ok=bool(need / 2 <= cash["reserve"] - RES_OPT + max(0, sv["top_bottom"]) and need / 2 <= pledge)))
        for x in TBlog:
            log.append(x)
        for t in TBtr:
            closed.append(dict(sym=f"{t['sym']} FUT", sleeve="top_bottom", sys="Top Bottom", d=str(t.get("EntryDate"))[:10], dx=str(t.get("ExitDate"))[:10],
                               e=t.get("Entry"), x=t.get("Exit"), qty=t["lot"], pnl=round((t.get("Points") or 0) * t["lot"]), why=t.get("Reason") or ""))
        pos = [dict(sym=s, sleeve=h["sleeve"], sys=h["sys"], qty=h["qty"], e=h["e"], last=round(h["last"], 2), d=h["d"], value=round(h["qty"] * h["last"]),
                    pnl=round(h["qty"] * (h["last"] - h["e"])), pct=round((h["last"] / h["e"] - 1) * 100, 2), stop=h.get("s")) for s, h in ((k_.split(":", 1)[1], h) for k_, h in hold.items())] + TBopen
        V0 = eq[-1]["v"]; peak = 0; dd = 0.0
        for x in eq:
            peak = max(peak, x["v"]); dd = min(dd, x["v"] / peak - 1)
        start_alloc = dict(**{k: round(Wt[k] * (CAP - RES_TB - RES_OPT)) for k in Wt}, reserve_top_bottom=RES_TB, reserve_options=RES_OPT)
        res["books"][bk] = dict(weights=Wt, start_alloc=start_alloc, equity=eq, positions=sorted(pos, key=lambda p: (p["sleeve"], -(p["value"] or 0))),
                                closed=sorted(closed, key=lambda c_: c_.get("dx") or ""), log=[dict(d=a, t=b) for a, b in sorted(log, key=lambda x: x[0], reverse=True)][:200],
                                summary=dict(value=V0, ret_pct=round((V0 / CAP - 1) * 100, 2), nifty_pct=round((eq[-1]["nifty"] / CAP - 1) * 100, 2),
                                             max_dd_pct=round(dd * 100, 2), days=len(eq),
                                             sleeve_pnl={k: round(eq[-1]["sleeves"][k] - (start_alloc.get(k, 0) if k in Wt else (RES_TB + RES_OPT if k == "reserve" else 0)))
                                                         for k in eq[-1]["sleeves"]}))
    try:
        res["books"]["recommended"] = rec_book(days, PP, C, O, gold, TBd, OPd, TBtr, TBopen, TBlog, nifty)
        res["default_book"] = "recommended"
    except Exception as ex:  # noqa: BLE001
        import traceback; traceback.print_exc(); print("recommended book failed:", ex)
    json.dump(res, open(OUT, "w"), separators=(",", ":"), default=str)
    for bk, B in res["books"].items():
        print(bk, B["summary"])


if __name__ == "__main__":
    main()
