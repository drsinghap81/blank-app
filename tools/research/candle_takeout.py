"""Breakout candle 'taken out' entries (23 Nov 2026, Amritpal: "test if we take these trades with an intraday order what return they
give - do a pilot; I need similar testing for flag or other pattern breakout candle taken out entries too").

Signals (NSE stocks, Yahoo daily 2015-26, today's names -> survivors; point in time):
  dcup   day cup close (tools/cupclose.py rules: close above the highest high of the last 250 days, rim >= 20 days old, cup >= 15% deep,
         room to the next older peak >= the depth) - the app's 'Day cup close' list and the new server alert
  flag   flag / pennant / rectangle breakout (live rule: drying flag volume, 1.5x breakout volume, flag range <= 8%)
  bottom bottom-pattern breakout (tools/pattern_scan.py: W / tilted W / triple bottom / inverse H&S, first close above the neckline)
  tight  tight-base breakout;  base  first 52-week-high breakout after a 6-month base (live 9/21-family rules)
One event per stock per 20 sessions per system. Trigger = the breakout candle's HIGH. Entry = a buy-stop: the first of the next
5 sessions whose high trades above the trigger; fill = the trigger + 0.1%, or the open if it gaps above.
Exits compared:
  intraday   sell at that day's close (0.10% cost)
  swing      stop = the breakout candle's low (an intraday low at or under it exits at the stop / the open if it gaps under),
             else the close after 21 / 63 sessions (0.40% cost)
  next-open  control: buy the next open after the breakout day regardless (same swing exits)
Newest first (last 1 / 2 / 3 / 5 years), each year. PILOT env = 150 stocks. Output data/research/candle_takeout(_pilot).json"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402
from confluence_test import sys_signals  # noqa: E402
from cupclose import cupclose, DY_K, DY_MIN, DY_DEP  # noqa: E402
import bottom_filters as BF  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
WIN, GAP = 5, 20


def dcup_days(x):
    h = x.HIGH.to_numpy(float); c = x.CLOSE.to_numpy(float); n = len(c); out = np.zeros(n, bool)
    for t in range(DY_K + 5, n):
        if c[t] <= np.nanmax(h[t - DY_K:t]):                 # quick reject: not above the 250-day high
            continue
        if cupclose(h[:t + 1], c[:t + 1], DY_K, DY_MIN, DY_DEP):
            out[t] = True
    return out


def bottom_days(sym, x):
    y = x.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})
    out = np.zeros(len(x), bool)
    for e in BF.events(sym, y):
        i = x.index.get_loc(e["d"]); out[i] = True
    return out


def trades(sym, x, sig, name):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index; n = len(c); rows = []; last = -999
    for t in np.where(sig)[0]:
        if t - last < GAP or D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n or c[t] < 30:
            continue
        last = t; trig, stop = h[t], l[t]
        r = dict(sys=name, sym=sym, d=D[t], taken=False)

        def swing(j0, e):
            out = {}
            for hz in (21, 63):
                res = None
                for j in range(j0, min(n, j0 + hz + 1)):
                    if l[j] <= stop and not (j == j0 and e <= stop):
                        res = (min(o[j], stop) if j > j0 else stop) / e - 1; break
                if res is None:
                    jj = j0 + hz
                    res = c[jj] / e - 1 if jj < n else np.nan
                out[hz] = res - 0.004 if np.isfinite(res) else np.nan
            return out
        for j in range(t + 1, min(n, t + 1 + WIN)):
            if h[j] > trig:
                e = max(o[j], trig * 1.001)
                if e > h[j]:
                    e = o[j]
                r.update(taken=True, lag=j - t, gap=bool(o[j] > trig), intraday=c[j] / e - 1 - 0.001, entry_vs_close=e / c[t] - 1)
                sw = swing(j, e); r.update(s21=sw[21], s63=sw[63]); break
        e0 = o[t + 1]; sw0 = swing(t + 1, e0); r.update(n21=sw0[21], n63=sw0[63])
        rows.append(r)
    return rows


def st(v):
    v = pd.Series(v).dropna()
    if not len(v):
        return None
    g, b = v[v > 0].sum(), -v[v < 0].sum()
    return dict(n=int(len(v)), avg=round(float(v.mean()) * 100, 2), med=round(float(v.median()) * 100, 2), win=round(float((v > 0).mean()) * 100),
                pf=round(float(g / b), 2) if b > 0 else None)


def main():
    P = FV.load(); rows = []
    for k_, (sym, x) in enumerate(P.items()):
        try:
            S = sys_signals(x)
            sig = {"dcup": dcup_days(x), "flag": S["flag"], "bottom": bottom_days(sym, x), "tight": S["tight"], "base": S["base"]}
            for nm, s_ in sig.items():
                rows += trades(sym, x, s_, nm)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, str(e)[:80])
        if k_ % 200 == 0:
            print("R| stocks", k_, "events", len(rows), flush=True)
    E = pd.DataFrame(rows); end = E.d.max(); res = dict(method=__doc__, systems={})
    for nm, T in E.groupby("sys"):
        tk = T[T.taken]
        o = dict(signals=int(len(T)), taken_pct=round(float(T.taken.mean()) * 100), gap_pct=round(float(tk.gap.mean()) * 100) if len(tk) else None,
                 entry_above_signal_close=round(float(tk.entry_vs_close.mean()) * 100, 2) if len(tk) else None,
                 intraday=st(tk.intraday), takeout_swing21=st(tk.s21), takeout_swing63=st(tk.s63), nextopen_swing21=st(T.n21), nextopen_swing63=st(T.n63),
                 not_taken_nextopen63=st(T[~T.taken].n63))
        for y in (1, 2, 3, 5):
            W = tk[tk.d > end - pd.DateOffset(years=y)]; W0 = T[T.d > end - pd.DateOffset(years=y)]
            o[f"last {y}y"] = dict(intraday=st(W.intraday), takeout63=st(W.s63), nextopen63=st(W0.n63))
        o["years"] = {str(yy): dict(intraday=st(g.intraday), takeout63=st(g.s63), nextopen63=st(T[T.d.dt.year == yy].n63))
                      for yy, g in sorted(tk.groupby(tk.d.dt.year), reverse=True)}
        res["systems"][nm] = o
        print(f"R| {nm} | signals {o['signals']} taken {o['taken_pct']}% (gap-ups {o['gap_pct']}%, entry {o['entry_above_signal_close']}% above signal close)", flush=True)
        print(f"R| {nm} | INTRADAY {o['intraday']} | take-out swing 21d {o['takeout_swing21']} 63d {o['takeout_swing63']} | next-open 21d {o['nextopen_swing21']} 63d {o['nextopen_swing63']} | never taken out -> next-open 63d {o['not_taken_nextopen63']}", flush=True)
        print(f"R| {nm} | last 1y {o['last 1y']} | last 3y {o['last 3y']}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/candle_takeout" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
