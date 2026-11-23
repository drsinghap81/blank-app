"""Breakout candle 'taken out' entries (23 Nov 2026, Amritpal: "test if we take these trades with an intraday order what return they
give - do a pilot; I need similar testing for flag or other pattern breakout candle taken out entries too").

Signals (NSE stocks, Yahoo daily 2015-26, today's names -> survivors; point in time):
  dcup   day cup close (tools/cupclose.py rules: close above the highest high of the last 250 days, rim >= 20 days old, cup >= 15% deep,
         room to the next older peak >= the depth) - the app's 'Day cup close' list and the new server alert
  flag   flag / pennant / rectangle breakout (live rule: drying flag volume, 1.5x breakout volume, flag range <= 8%)
  bottom bottom-pattern breakout (tools/pattern_scan.py: W / tilted W / triple bottom / inverse H&S, first close above the neckline)
  tight  tight-base breakout;  base  first 52-week-high breakout after a 6-month base (live 9/21-family rules)
One event per stock per 20 sessions per system. Entry = buy-stop at the breakout candle's HIGH + 0.1% (and + 0.2%), valid 5
sessions; fill at that price or the open if it gaps above. SL = the breakout candle's LOW. Exits: intraday close (0.1% cost); hold
63 sessions; trail = first close below the 21-day EMA; target 2R (0.4% cost). Control: buy the next open regardless (63 sessions).
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
    """23 Nov 2026 (Amritpal: "buying only happens if the high is taken out, order 0.1-0.2% higher, SL below the breakout candle low"):
    buy-stop at the breakout candle's high + BUF (0.1% / 0.2%), valid WIN sessions; fill = that price, or the open if it gaps above.
    Stop = the breakout candle's low (a low at or under it exits at the stop / the open if it gaps under; on the entry day a low under
    the stop counts as stopped - conservative). Exits after entry: E1 intraday close; E2 hold 63 sessions; E3 trail = first close below
    the 21-day EMA (sell next open); E4 target 2R (risk = entry - stop) else 63 sessions."""
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index; n = len(c); rows = []; last = -999
    e21 = pd.Series(c).ewm(span=21, adjust=False).mean().to_numpy()
    for t in np.where(sig)[0]:
        if t - last < GAP or D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n or c[t] < 30:
            continue
        last = t; stop = l[t]
        r = dict(sys=name, sym=sym, d=D[t])
        for buf in (0.001, 0.002):
            trig = h[t] * (1 + buf); k = f"{int(buf * 1000)}"
            r[f"taken{k}"] = False
            for j in range(t + 1, min(n, t + 1 + WIN)):
                if h[j] >= trig:
                    e = o[j] if o[j] > trig else trig
                    risk = e - stop
                    r.update({f"taken{k}": True, f"gap{k}": bool(o[j] > trig), f"risk{k}": risk / e, f"intra{k}": c[j] / e - 1 - 0.001})
                    res = {}
                    for ex in ("hold", "trail", "2R"):
                        out = None
                        for q in range(j, min(n, j + 64)):
                            if l[q] <= stop:
                                out = (stop if q == j or o[q] > stop else o[q]) / e - 1; break
                            if ex == "2R" and h[q] >= e + 2 * risk and q > j:
                                out = max(e + 2 * risk, o[q]) / e - 1; break
                            if ex == "trail" and q > j and c[q] < e21[q] and q + 1 < n:
                                out = o[q + 1] / e - 1; break
                        if out is None:
                            qq = min(n - 1, j + 63); out = c[qq] / e - 1 if j + 63 < n else np.nan
                        res[ex] = out - 0.004 if np.isfinite(out) else np.nan
                    r.update({f"{ex}{k}": v for ex, v in res.items()}); break
        e0 = o[t + 1]; qq = t + 1 + 63
        r["nextopen63"] = c[qq] / e0 - 1 - 0.004 if qq < n else np.nan
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
        o = dict(signals=int(len(T)))
        for k in ("1", "2"):
            tk = T[T[f"taken{k}"] == True]  # noqa: E712
            o[f"buy-stop +0.{k}%"] = dict(taken_pct=round(float(T[f"taken{k}"].mean()) * 100), gap_pct=round(float(tk[f"gap{k}"].mean()) * 100) if len(tk) else None,
                                          risk_pct=round(float(tk[f"risk{k}"].median()) * 100, 1) if len(tk) else None,
                                          intraday=st(tk[f"intra{k}"]), hold63=st(tk[f"hold{k}"]), trail_ema21=st(tk[f"trail{k}"]), target_2R=st(tk[f"2R{k}"]))
        tk = T[T.taken1 == True]  # noqa: E712
        o["never taken out (buy next open, 63d)"] = st(T[T.taken1 != True].nextopen63)  # noqa: E712
        o["all signals (buy next open, 63d)"] = st(T.nextopen63)
        for y in (1, 2, 3, 5):
            W = tk[tk.d > end - pd.DateOffset(years=y)]
            o[f"last {y}y (+0.1%)"] = dict(n=int(len(W)), intraday=st(W.intra1), hold63=st(W.hold1), trail_ema21=st(W.trail1), target_2R=st(W["2R1"]))
        o["years (+0.1%)"] = {str(yy): dict(trail_ema21=st(g.trail1), target_2R=st(g["2R1"]), hold63=st(g.hold1)) for yy, g in sorted(tk.groupby(tk.d.dt.year), reverse=True)}
        res["systems"][nm] = o
        for k in ("1", "2"):
            b = o[f"buy-stop +0.{k}%"]
            print(f"R| {nm} | +0.{k}% | taken {b['taken_pct']}% gap {b['gap_pct']}% risk {b['risk_pct']}% | intraday {b['intraday']} | hold63 {b['hold63']} | trail EMA21 {b['trail_ema21']} | 2R {b['target_2R']}", flush=True)
        print(f"R| {nm} | never taken out {o['never taken out (buy next open, 63d)']} | all next-open {o['all signals (buy next open, 63d)']}", flush=True)
        for y in (1, 2, 3, 5):
            print(f"R| {nm} | last {y}y {o[f'last {y}y (+0.1%)']}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/candle_takeout" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
