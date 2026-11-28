"""Check Amritpal's 'TFT Banknifty New' sample (Dec 2020 - Jul 2021, lot 25) against the Bank Nifty INDEX (Yahoo ^NSEBANK)."""
import os
import sys
import json
import pandas as pd
import yfinance as yf
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import topbottom_backtest as tbb  # noqa: E402
TR = [("2020-12-18","S",30552,30857),("2020-12-21","S",30552,29475),("2020-12-28","B",30902,31950),("2021-01-12","B",32333,31935),("2021-01-18","S",31935,32848),("2021-01-21","B",32917,32587),("2021-01-22","S",31842,30440),("2021-02-11","B",36046,35684),("2021-02-12","B",36225,36300),("2021-02-19","S",35893,34900),("2021-03-03","B",36555,35111),("2021-03-15","S",35111,33800),("2021-03-22","S",34049,34522),("2021-03-23","B",34522,34177),("2021-03-24","S",33872,32700),("2021-04-01","B",34047,33310),("2021-04-05","S",33310,31300),("2021-04-19","S",30869,31205),("2021-04-22","S",30869,31178),("2021-04-26","B",32314,33880),("2021-05-14","S",32259,33462),("2021-05-17","B",33462,34763),("2021-05-26","B",35093,35330),("2021-06-08","S",35330,35445),("2021-06-16","B",35445,35090),("2021-06-17","S",34714,34714),("2021-06-24","B",35018,35800),("2021-07-19","S",35270,34650),("2021-07-28","S",34640,35215)]
d = yf.download("^NSEBANK", start="2020-06-01", end="2021-09-01", progress=False, auto_adjust=False)
d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
d = d[["Open", "High", "Low", "Close"]].dropna()
c = d.Close.to_numpy(); T, B, piv = tbb.confirmed_swings(c, 0.0)
P = [(d.index[pi], d.index[ci], k, v) for ci, pi, k, v in piv]
for dt, s, e, x in TR:
    t = pd.Timestamp(dt); kind = "T" if s == "B" else "B"
    cand = [p for p in P if p[2] == kind and p[1] < t]; lp = cand[-1]
    ne = min(P, key=lambda p: abs(p[3] - e)); nx = min(P, key=lambda p: abs(p[3] - x))
    r = d.loc[t] if t in d.index else None
    print(f"R| {dt} {s} {e} | last {kind} {lp[3]:.1f} ({lp[0].date()}) diff {e - lp[3]:+.1f} | nearest {ne[2]} {ne[3]:.1f} {ne[0].date()} | exit {x} nearest {nx[2]} {nx[3]:.1f} {nx[0].date()}"
          + (f" | day H {r.High:.0f} L {r.Low:.0f} C {r.Close:.0f}" if r is not None else " | no bar"), flush=True)
for nm, f in (("sheet", lambda: tbb.run_sheet(d, tbb.Params(mode="sheet"))), ("live0", lambda: tbb.run_live(d, tbb.Params(buffer_pts=0, event_exit=False, start_flat_on="2020-12-01"))),
              ("live25", lambda: tbb.run_live(d, tbb.Params(buffer_pts=25, event_exit=False, start_flat_on="2020-12-01")))):
    t = f(); t = t[(pd.to_datetime(t.EntryDate) >= "2020-12-15") & (pd.to_datetime(t.EntryDate) <= "2021-07-31")]
    sg = t.Side.map({"BUY": 1, "SELL": -1}); print(f"R| {nm}: n {len(t)} pts {((t.Exit - t.Entry) * sg).sum():.0f}", flush=True)
    for r in t.itertuples():
        print(f"R|   {nm} {pd.Timestamp(r.EntryDate).date()} {r.Side[0]} {r.Entry:.1f} -> {pd.Timestamp(r.ExitDate).date()} {r.Exit:.1f} {r.Reason}", flush=True)
