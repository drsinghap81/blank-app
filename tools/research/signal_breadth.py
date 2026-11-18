"""Signal breadth as a caution light (19 Nov 2026, Amritpal: "if across all systems the sells outnumber the buys, that's a
warning sign for me - investment, momentum, trend systems").

Across all liquid NSE stocks (Yahoo, 2016 -> today, survivors only), each day:
  trend breadth  : stocks whose EMA 9 crossed ABOVE EMA 21 (buys) vs crossed BELOW (sells), summed over the last 10 sessions
  momentum/invest: stocks whose WEEKLY close crossed above vs below their 30-week SMA (the Monthly ATH exit line), last 2 weeks
  warning        : W1 trend sells > buys; W2 weekly sells > buys; W3 both
Tests:
  1. Nifty 50 after a warning day vs other days: next 20 / 60-day return, worst fall within 60 days
  2. the live 9/21 engine (10 positions, 1% risk, random pick; and the 5-position 3-month-strength version) with NO NEW BUYS
     while the warning is on (open positions keep their own stops) vs no filter
Output: data/research/signal_breadth.json (+ the daily breadth series for the app)"""
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


def breadth(d):
    d = d.sort_values(["SYMBOL", "Date"]).copy()
    g = d.groupby("SYMBOL").CLOSE
    e9 = g.transform(lambda s: s.ewm(span=9, adjust=False).mean()); e21 = g.transform(lambda s: s.ewm(span=21, adjust=False).mean())
    up = (e9 > e21); prev = up.groupby(d.SYMBOL).shift(1)
    d["xu"] = up & (prev == False); d["xd"] = (~up) & (prev == True)          # noqa: E712
    daily = d.groupby("Date")[["xu", "xd"]].sum()
    # weekly 30-week SMA crosses
    rows = []
    for sym, x in d.groupby("SYMBOL"):
        w = x.set_index("Date").CLOSE.groupby(pd.Grouper(freq="W-FRI")).last().dropna()
        if len(w) < 32:
            continue
        sm = w.rolling(30).mean(); ab = w > sm; pa = ab.shift(1)
        rows.append(pd.DataFrame({"wu": ab & (pa == False), "wd": (~ab) & (pa == True)}))   # noqa: E712
    W = pd.concat(rows).groupby(level=0).sum()
    B = daily.copy()
    B["buys10"] = daily.xu.rolling(10).sum(); B["sells10"] = daily.xd.rolling(10).sum()
    Wr = W.rolling(2).sum()
    B["wbuys"] = Wr.wu.reindex(B.index, method="ffill"); B["wsells"] = Wr.wd.reindex(B.index, method="ffill")
    # weekly figures are known only after the Friday close -> use them from the next session
    B[["wbuys", "wsells"]] = B[["wbuys", "wsells"]].shift(1)
    B["W1"] = B.sells10 > B.buys10; B["W2"] = B.wsells > B.wbuys; B["W3"] = B.W1 & B.W2
    return B


def run_gated(d, maxpos, risk, rank, seed, gate):
    """concentrated_921.run with new entries blocked on dates in `gate` (decided on the signal day's close)."""
    d2 = d.copy(); d2.loc[d2.Date.isin(gate), "sig"] = False
    return C.run(d2, maxpos, risk, rank, seed)


def main():
    d, _ = load("NSE")
    d = d.sort_values(["SYMBOL", "Date"])
    g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    B = breadth(d)
    nif = yf.download("^NSEI", start="2015-06-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    B = B[B.index >= "2016-06-01"]
    f20 = nif.shift(-20) / nif - 1; f60 = nif.shift(-60) / nif - 1
    dd60 = pd.Series([(nif.iloc[i:i + 61].min() / nif.iloc[i] - 1) if i + 1 < len(nif) else np.nan for i in range(len(nif))], index=nif.index)
    res = dict(method=__doc__, days=len(B))
    for w in ("W1", "W2", "W3"):
        on = B.index[B[w].fillna(False)]
        off = B.index[~B[w].fillna(False)]
        def m(ix, s):
            v = s.reindex(ix).dropna()
            return round(float(v.mean()) * 100, 2) if len(v) else None
        res[w] = dict(share_of_days=round(len(on) / len(B) * 100, 1),
                      nifty_20d_on=m(on, f20), nifty_20d_off=m(off, f20), nifty_60d_on=m(on, f60), nifty_60d_off=m(off, f60),
                      worst_fall_60d_on=m(on, dd60), worst_fall_60d_off=m(off, dd60),
                      by_year={str(y): round(float(B[w][B.index.year == y].mean()) * 100) for y in sorted(set(B.index.year))})
    port = {}
    for label, args in (("10 positions, 1% risk, random", (10, 0.01, "random", 0)), ("5 positions, 1% risk, 3-month strength", (5, 0.01, "r63", 0))):
        for w in (None, "W1", "W2", "W3"):
            gate = set() if w is None else set(B.index[B[w].fillna(False)])
            eq, T = run_gated(d, *args, gate)
            a, b, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2017-01-01", "2021-12-31"), stats(eq, "2022-01-01", "2030-01-01")
            port[f"{label} | {'no filter' if w is None else 'no new buys while ' + w}"] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"],
                                                                                                cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T))
            print(label, w, port[list(port)[-1]], flush=True)
    res["portfolio"] = port
    last = B.tail(30)
    res["latest"] = {str(k.date()): dict(buys10=int(v.buys10), sells10=int(v.sells10), wbuys=None if pd.isna(v.wbuys) else int(v.wbuys),
                                          wsells=None if pd.isna(v.wsells) else int(v.wsells)) for k, v in last.iterrows()}
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/signal_breadth.json", "w"), indent=1, default=str)
    for k, v in res.items():
        if k not in ("method", "latest"):
            print(k, v)


if __name__ == "__main__":
    main()
