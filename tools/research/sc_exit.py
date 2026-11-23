"""Book profit on a long when SHORT COVERING shows up? (23 Nov 2026, Amritpal: "when I am long in something and short covering
starts, tell me to book profit").
Data: NSE F&O bhavcopy (UDiFF) Jul 2024 -> today: futures OI (all expiries) + underlying close per symbol (fo_squeeze.one).
Short covering at a close:  SC1 = 1-day futures OI -3% or more while price +1% or more;  SC3 = 3-day OI -5% or more, price +3% or more.
A) Top Bottom Bank Nifty and Nifty LONGS (bot rules, near-month futures from bhavcopy, tools/topbottom_backtest.run_live):
   on the first SC day while the trade is >= P% in profit (P = 0 / 1 / 2), exit at the NEXT OPEN instead of the system exit.
   (The system's later trades are left as they were - an approximation.) Points per unit, newest first by half-year.
B) Any F&O stock in an uptrend (EMA9 > EMA21, close above EMA21, 20-day gain >= 5% = "long and in profit"): next 5 / 10 / 20 sessions
   after a short-covering day vs other uptrend days (stock minus the average F&O stock). If SC days are followed by weaker returns,
   booking on them helps.
PILOT env = last 9 months only. Output data/research/sc_exit(_pilot).json"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
from fo_squeeze import one  # noqa: E402
import topbottom_backtest as tbb  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def main():
    start = pd.Timestamp.today() - pd.DateOffset(months=9) if PILOT else pd.Timestamp("2024-07-08")
    days = pd.bdate_range(start, pd.Timestamp.today())
    with ThreadPoolExecutor(6) as ex:
        parts = [p for p in ex.map(one, days) if p is not None]
    A = pd.concat(parts, ignore_index=True)
    P = A.pivot_table(index="Date", columns="sym", values="price"); OI = A.pivot_table(index="Date", columns="sym", values="fut_oi")
    print("R| data", P.index.min().date(), "->", P.index.max().date(), "days", len(P), "symbols", P.shape[1], flush=True)
    r1, r3 = P / P.shift(1) - 1, P / P.shift(3) - 1
    o1, o3 = OI / OI.shift(1).replace(0, np.nan) - 1, OI / OI.shift(3).replace(0, np.nan) - 1
    for sym in ("BANKNIFTY", "NIFTY"):          # the recent rally day by day (Amritpal: "short covering from the start, or just Friday?")
        x = pd.DataFrame({"px": P[sym], "oi": OI[sym]}).dropna().iloc[-25:]
        x["px1"] = (x.px.pct_change() * 100).round(2); x["oi1"] = (x.oi.pct_change() * 100).round(1)
        lab = lambda r: "" if abs(r.oi1) < 2 else ("long build-up" if r.px1 > 0 and r.oi1 > 0 else "short build-up" if r.oi1 > 0 else "SHORT COVERING" if r.px1 > 0 else "long unwinding")  # noqa: E731
        for d, r in x.iloc[1:].iterrows():
            print(f"R| DAY {sym} {d:%a %d %b} | close {r.px:,.0f} ({r.px1:+.2f}%) | fut OI {r.oi / 1e5:,.2f} L ({r.oi1:+.1f}%) | {lab(r)}", flush=True)
    SIG = {"SC1 (1-day OI -3%, price +1%)": (o1 <= -0.03) & (r1 >= 0.01), "SC3 (3-day OI -5%, price +3%)": (o3 <= -0.05) & (r3 >= 0.03)}
    # expiry-day roll distorts OI: drop days where any near expiry happened (OI collapses as the month rolls) - flag the last weekday of each month crudely
    res = {"method": __doc__, "A": {}, "B": {}}
    for sym, csv in (("BANKNIFTY", "data/futures/BANKNIFTY.csv"), ("NIFTY", "data/futures/NIFTY.csv")):
        if not os.path.exists(csv) or sym not in P:
            continue
        df = pd.read_csv(csv, parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]]
        p = tbb.Params(buffer_pts=25 if sym == "BANKNIFTY" else 10, gap_pct=1.0, event_exit=True, cost_pts=2, long_only=(sym == "NIFTY"))
        t = tbb.run_live(df, p); t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ExitDate"] = pd.to_datetime(t.ExitDate)
        t = t[(t.Side == "BUY") & (t.EntryDate >= P.index.min() + pd.Timedelta(days=5))]
        for sn, S in SIG.items():
            s = S[sym].fillna(False)
            for pf in (0, 1, 2):
                new, n_ex = [], 0
                for _, tr in t.iterrows():
                    pts = tr.Points
                    win = df.loc[(df.index > tr.EntryDate) & (df.index < tr.ExitDate)]
                    for d in win.index:
                        if d in s.index and s.at[d] and (df.at[d, "Close"] - tr.Entry) / tr.Entry * 100 >= pf:
                            nx = df.index[df.index > d]
                            if len(nx) and nx[0] <= tr.ExitDate:
                                pts = df.at[nx[0], "Open"] - tr.Entry - 2; n_ex += 1
                            break
                    new.append((tr.ExitDate, pts, tr.Points))
                N = pd.DataFrame(new, columns=["d", "new", "old"])
                halves = {f"{y}H{h}": (round(g.new.sum()), round(g.old.sum())) for (y, h), g in
                          sorted(N.groupby([N.d.dt.year, (N.d.dt.month > 6).astype(int) + 1]), reverse=True)}
                r = dict(trades=len(N), exits_changed=n_ex, new_pts=round(N.new.sum()), system_pts=round(N.old.sum()), by_half_new_vs_system=halves)
                res["A"][f"{sym} | {sn} | profit >= {pf}%"] = r
                print(f"R| A {sym} | {sn} | profit>={pf}% | {r}", flush=True)
    # B: stocks
    stk = [c for c in P.columns if c not in ("BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")]
    C = P[stk]; e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean()
    up = (e9 > e21) & (C > e21) & (C / C.shift(20) - 1 >= 0.05)
    mkt = C.pct_change().mean(axis=1)
    for h in (5, 10, 20):
        fwd = (C.shift(-h) / C - 1).sub((1 + mkt).rolling(h).apply(np.prod, raw=True).shift(-h) - 1, axis=0)
        for sn, S in SIG.items():
            a = fwd[up & S[stk].fillna(False)].stack().dropna(); b = fwd[up & ~S[stk].fillna(False)].stack().dropna()
            o = dict(sc_n=len(a), sc_avg=round(a.mean() * 100, 2), sc_med=round(a.median() * 100, 2), sc_beat=round((a > 0).mean() * 100),
                     other_n=len(b), other_avg=round(b.mean() * 100, 2), other_med=round(b.median() * 100, 2), other_beat=round((b > 0).mean() * 100))
            yrs = {}
            for y in sorted({d.year for d in a.index.get_level_values(0)}, reverse=True):
                aa = a[a.index.get_level_values(0).year == y]; bb = b[b.index.get_level_values(0).year == y]
                yrs[y] = (round(aa.mean() * 100, 2), round(bb.mean() * 100, 2), len(aa))
            o["by_year_sc_vs_other_n"] = yrs
            res["B"][f"{sn} | next {h}d"] = o
            print(f"R| B stocks in uptrend | {sn} | next {h}d | {o}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    pd.Series(res).to_json("data/research/sc_exit" + ("_pilot" if PILOT else "") + ".json", indent=1, default_handler=str)


if __name__ == "__main__":
    main()
