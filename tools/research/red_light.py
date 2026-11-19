"""Market traffic light for new swing entries (19 Nov 2026, Amritpal: "if market breadth is RED I need to be cautioned not to enter").

Light, decided at each close (all liquid NSE stocks, Yahoo 2016 -> today, survivors):
  breadth bad : over the last 10 sessions more stocks crossed EMA 9 BELOW EMA 21 than above (sells > buys)
  index bad   : Nifty's last weekly close below its 30-week SMA (known from the next session)
  RED = both bad, AMBER = one bad, GREEN = neither.  Also tested: share of stocks above their 50-day SMA < 40%.
Tests on the live 9/21 engine (buy next open, 5-day-low stop, Supertrend exit, 1% risk):
  1. no new buys on RED / on RED or AMBER / on index-bad / on <40% above 50-day
  2. 9/21 trades split by the light on their signal day: average trade, win rate, count
Output: data/research/red_light.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load, stats  # noqa: E402
import concentrated_921 as C  # noqa: E402
from signal_breadth import breadth  # noqa: E402


def main():
    d, _ = load("NSE")
    d = d.sort_values(["SYMBOL", "Date"])
    g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    d["a50"] = d.CLOSE > g.transform(lambda s: s.rolling(50).mean())
    B = breadth(d)
    B["p50"] = d.groupby("Date").a50.mean() * 100
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    w = nif.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = (w < w.rolling(30).mean())
    B["idx_bad"] = below.reindex(B.index, method="ffill").shift(1).fillna(False).astype(bool)
    B["br_bad"] = B.W1.fillna(False).astype(bool)
    B["light"] = np.where(B.br_bad & B.idx_bad, "RED", np.where(B.br_bad | B.idx_bad, "AMBER", "GREEN"))
    B = B[B.index >= "2016-06-01"]
    res = dict(method=__doc__, days={k: round(float((B.light == k).mean() * 100), 1) for k in ("GREEN", "AMBER", "RED")},
               by_year={str(y): {k: round(float((B.light[B.index.year == y] == k).mean() * 100)) for k in ("GREEN", "AMBER", "RED")} for y in sorted(set(B.index.year))})
    f20 = nif.shift(-20) / nif - 1
    res["nifty_next20d"] = {k: round(float(f20.reindex(B.index[B.light == k]).mean() * 100), 2) for k in ("GREEN", "AMBER", "RED")}
    gates = {"no filter": set(), "no new buys on RED": set(B.index[B.light == "RED"]),
             "no new buys on RED or AMBER": set(B.index[B.light != "GREEN"]), "no new buys when Nifty < 30-week": set(B.index[B.idx_bad]),
             "no new buys when < 40% of stocks above 50-day": set(B.index[B.p50 < 40])}
    port = {}
    for label, args in (("10 positions, 3-month strength", (10, 0.01, "r63", 0)), ("5 positions, 3-month strength", (5, 0.01, "r63", 0)),
                        ("10 positions, random", (10, 0.01, "random", 0))):
        for gname, gate in gates.items():
            d2 = d.copy(); d2.loc[d2.Date.isin(gate), "sig"] = False
            eq, T = C.run(d2, *args)
            a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
            k = f"{label} | {gname}"
            port[k] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T))
            print("R|", k, port[k], flush=True)
            if gname == "no filter":
                # trades split by the light on the session before entry (the signal day)
                days = sorted(B.index); pos = {dd: i for i, dd in enumerate(days)}
                def lt(e):
                    e = pd.Timestamp(e); i = pos.get(e)
                    return B.light.iloc[i - 1] if i else None
                T = T.assign(light=[lt(e) for e in T.entry])
                port[k]["by_light"] = {L: dict(n=int((T.light == L).sum()), avg=round(float(T.ret[T.light == L].mean() * 100), 2),
                                                win=round(float((T.ret[T.light == L] > 0).mean() * 100))) for L in ("GREEN", "AMBER", "RED")}
                print("T|", label, port[k]["by_light"], flush=True)
    res["portfolio"] = port
    res["latest"] = {str(k.date()): dict(light=v.light, buys10=int(v.buys10), sells10=int(v.sells10), p50=round(float(v.p50), 1), idx_bad=bool(v.idx_bad))
                     for k, v in B.tail(15).iterrows()}
    print("L|", res["days"], res["nifty_next20d"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/red_light.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
