"""Tighter flags with volume (22 Nov 2026, Amritpal: "These patterns should be tighter ones with volumes drying out and only the
breakout candle volume should be high. Then trade when the next day's high crosses the breakout candle's high, with a trailing SL").

Base detection = the live flag scanner (flag_stops.signals, no look-ahead). Added filters, each tested alone and together:
  DRY   volume dries up in the flag: average volume over the flag < 0.75 x the pole's average AND < the 50-day average
        (measured before the pole)
  BOVOL breakout candle volume >= 1.5 x the 50-day average, and the highest volume of the whole flag
  TIGHT flag range (highest high - lowest low of the flag) <= 8% of the pole top (scanner allows a 12% pullback)
Entry: NEXT = buy-stop one tick above the breakout candle's high, valid the next session only (gap -> fill at the open); if it
       is not crossed the trade is skipped.  CLOSE = buy at the breakout close (the earlier test).
Stop = flag low (incl. the breakout day). Exit = trailing: first daily close below the 21-day EMA, sold next open (the winner of
the stop test); stop hit intraday -> out at the stop (or the open on a gap). 0.2% cost a round trip.
Same portfolio and reporting as flag_stops (Rs 20 L, 1% risk, 10 slots). NSE via Yahoo + bhavcopy, survivors only.
PILOT env = 150 stocks. Output data/research/flag_volume.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
from global_universe import symbols  # noqa: E402
from holy_grail import portfolio, report  # noqa: E402
from flag_stops import signals, tst  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002
MINVAL = 2e7


def load():
    u = symbols("NSE"); tick = list(u.ticker)
    if PILOT:
        tick = sorted(tick)[:150]
    out = {}
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]; d = None
        for _ in range(3):
            try:
                d = yf.download(ch, start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({"OPEN": d["Open"][t], "HIGH": d["High"][t], "LOW": d["Low"][t], "CLOSE": d["Close"][t], "VOL": d["Volume"][t]}).dropna()
            except Exception:  # noqa: BLE001
                continue
            x = x[(x.CLOSE > 0) & (x.OPEN > 0)]
            if len(x) < 300 or (x.CLOSE * x.VOL).rolling(20).mean().max() < MINVAL:
                continue
            x.index = pd.to_datetime(x.index).tz_localize(None); out[t.replace(".NS", "")] = x
        print("R| loaded", i + len(ch), len(out), flush=True); time.sleep(2)
    return out


def trail(o, h, l, c, e21, j0, e, stop, same_day=True):
    """in at index j0 (price e); exit on a close below EMA21 (next open) or the stop -> (exit idx, return, stopped)"""
    n = len(c)
    if same_day and l[j0] <= stop:                                   # stopped the same day it was bought (conservative)
        return j0, stop / e - 1, True
    j = j0 + 1
    while j < n:
        if o[j] <= stop: return j, o[j] / e - 1, True
        if l[j] <= stop: return j, stop / e - 1, True
        if c[j] < e21[j] and j + 1 < n: return j + 1, o[j + 1] / e - 1, False
        if j - j0 >= 250: return j, c[j] / e - 1, False
        j += 1
    return n - 1, c[n - 1] / e - 1, False


VARS = ["1 scanner now, buy at breakout close", "2 scanner now, buy above breakout high next day", "3 + volume dries up in flag",
        "4 + breakout volume high", "5 + dry + breakout volume (your rule)", "6 + dry + breakout volume + tight <= 8% (your rule, tight)",
        "7 your rule, tight, but buy at breakout close"]


def main():
    P = load()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    C = {s: x.CLOSE.astype(float).to_dict() for s, x in P.items()}
    days = sorted({d for x in P.values() for d in x.index if d >= pd.Timestamp("2016-06-01")})
    rows = {v: [] for v in VARS}; nsig = 0
    for sym, x in P.items():
        o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); D = x.index; n = len(c)
        e21 = pd.Series(c).ewm(span=21, adjust=False).mean().to_numpy(); v50 = pd.Series(v).rolling(50).mean().shift(1).to_numpy()
        for s in signals(x):
            t = s["t"]
            if D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n:
                continue
            nsig += 1; a, b, pk, lo_i = s["a"], s["b"], s["pk"], s["lo_i"]; stop = s["fl"]
            fv = v[a:b].mean(); pv = v[lo_i:pk + 1].mean(); base50 = v50[lo_i] if np.isfinite(v50[lo_i]) else v50[t]
            dry = bool(fv < 0.75 * pv and fv < base50)
            bvol = bool(v[t] >= 1.5 * v50[t] and v[t] >= v[a:b].max())
            tight = bool((h[a:b].max() - l[a:b].min()) / h[pk] <= 0.08)
            nxt = None
            if h[t + 1] > h[t]:
                nxt = max(o[t + 1], h[t] * 1.0005)
            ok = {VARS[0]: True, VARS[1]: True, VARS[2]: dry, VARS[3]: bvol, VARS[4]: dry and bvol, VARS[5]: dry and bvol and tight, VARS[6]: dry and bvol and tight}
            for vn, good in ok.items():
                if not good:
                    continue
                if vn.startswith("1") or vn.startswith("7"):
                    e, j0 = c[t], t
                    if not stop < e: continue
                    j, r, sp = trail(o, h, l, c, e21, t, e, stop, same_day=False)
                else:
                    if nxt is None or not stop < nxt: continue
                    e, j0 = nxt, t + 1
                    j, r, sp = trail(o, h, l, c, e21, j0, e, stop)
                risk = 1 - stop / e; ret = r - COST
                rows[vn].append(dict(sym=sym, side=1, entry=D[j0], exit=D[j], e=e, risk=risk, ret=ret, r_mult=ret / risk, half=False, days=j - j0,
                                     adx=s["pole"], stopped=sp, hit=bool(h[j0:j + 1].max(initial=0) >= s["tgt"]), shape=s["shape"], lane=s["lane"], year=D[t].year))
    print("R| panel", len(P), "stocks,", nsig, "breakouts since Jun 2016", flush=True)
    res = dict(method=__doc__, stocks=len(P), signals=nsig, nifty=report(pd.Series({dd: float(nif.asof(dd)) for dd in days}), bull), runs={})
    for vn, L in rows.items():
        T = pd.DataFrame(L)
        if not len(T):
            print("R|", vn, "no trades"); continue
        end = T.entry.max()
        tr = dict(all=tst(T), **{f"last {y}y": tst(T[T.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)},
                  ex_covid=tst(T[~((T.entry >= "2020-02-15") & (T.entry <= "2020-12-31"))]))
        rp = report(portfolio(T, C, days), bull)
        res["runs"][vn] = dict(trades=tr, port=rp, by_shape={sh: tst(T[T["shape"] == sh]) for sh in ("Flag", "Pennant", "Rectangle")},
                               by_lane={ln: tst(T[T["lane"] == ln]) for ln in ("early", "established")},
                               by_year={str(y): tst(T[T.year == y]) for y in sorted(T.year.unique(), reverse=True)}, per_year=round(len(T) / 10.4))
        print(f"R| {vn} | trades {tr['all']} | 1y {tr['last 1y']} | 2y {tr['last 2y']} | 5y {tr['last 5y']}", flush=True)
        print(f"R| {vn} | portfolio {rp}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/flag_volume" + ("_high" if os.environ.get("BO") == "high" else "") + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
