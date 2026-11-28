"""Top Bottom traded on the CLOSE (28 Nov 2026, Amritpal aligned the markings with the course chart: tops/bottoms = 1-day turns of the
close line, trade when the CLOSE crosses the last top/bottom, SL trailed to the next V). Sheet rule, but booked at the signal-day close
(trade placed ~3:25 pm) instead of the top/bottom price. Compared with the live stop-order rules (honest entry-day stop) and the sheet
as written. Pilot: Bank Nifty and Nifty index (Yahoo), newest windows first. Points per unit and % a year (no compounding, 0.05% cost)."""
import os
import sys

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import topbottom_backtest as tbb  # noqa: E402


def load(t):
    d = yf.download(t, start="2010-01-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    return d[["Open", "High", "Low", "Close"]].dropna()


def pts(t, d, a, close_book=False):
    t = t[pd.to_datetime(t.EntryDate) >= a]
    if not len(t):
        return 0, 0, 0.0
    sg = t.Side.map({"BUY": 1, "SELL": -1})
    if close_book:
        p = (d.Close.reindex(pd.to_datetime(t.ExitDate)).values - d.Close.reindex(pd.to_datetime(t.EntryDate)).values) * sg
        e = d.Close.reindex(pd.to_datetime(t.EntryDate)).values
    else:
        p = (t.Exit - t.Entry) * sg; e = t.Entry.values
    pct = (p / e - 0.0005).sum() * 100
    return len(t), round(float(p.sum())), pct


def main():
    for nm, tk, buf in (("BANKNIFTY", "^NSEBANK", 25), ("NIFTY", "^NSEI", 0)):
        d = load(tk); end = d.index[-1]
        W = [("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)), ("2021+", pd.Timestamp("2021-01-01")),
             ("2015+", pd.Timestamp("2015-01-01"))]
        S = tbb.run_sheet(d, tbb.Params(mode="sheet"))
        L = tbb.run_live(d, tbb.Params(buffer_pts=buf, buffer_pct=None if buf else 0.05, event_exit=False, day_sl_fill="close"))
        print(f"R| ===== {nm} {d.index[0].date()} -> {end.date()}", flush=True)
        for lab, a in W:
            yrs = (end - a).days / 365.25
            row = []
            for k, t, cb in (("sheet as written", S, False), ("sheet traded at close", S, True), ("live stop orders", L, False)):
                n, p, pc = pts(t, d, a, cb); row.append(f"{k} n{n:4d} {p:+8d} pts {pc / yrs:+6.1f}%/yr")
            print(f"R| {nm} {lab:8s} | " + " | ".join(row), flush=True)
        S2 = S[pd.to_datetime(S.EntryDate) >= end - pd.DateOffset(years=1)]
        for r in S2.tail(8).to_dict("records"):
            print(f"R|   last trades: {r['Side']} {pd.Timestamp(r['EntryDate']).date()} level {r['Entry']:.0f} close {d.Close[pd.Timestamp(r['EntryDate'])]:.0f}"
                  f" -> {pd.Timestamp(r['ExitDate']).date()} level {r['Exit']:.0f} close {d.Close[pd.Timestamp(r['ExitDate'])]:.0f}", flush=True)


if __name__ == "__main__":
    main()
