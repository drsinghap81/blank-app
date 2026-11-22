"""Live systems vs regular FII buying (22 Nov 2026, Amritpal: "test all systems against regular FII buying").

Gates from tools/research/fii_gate.py (NSDL daily FPI equity net, used from the next session): new buys only while the 20-day
(or 60-day) FII net is positive, or skip only while FII sell heavily. Open positions are kept and exit by their own rules.
Here: 9/21 (live engine tools/research/morning_check.run, 10 positions, 1% risk, 3-month ranking), Monthly ATH stocks (events and
book as tools/research/ath_red_skip: live sizing 2% risk to the 30-week SMA / max 20%, and equal 10; 3 random orders), and Nifty 50
held only while the gate is on (cash otherwise, a timing check). Pulse rotation, ETF month-close ATH and flags run in their own
scripts with FII=1. NSE 2016-26 Yahoo survivors. PILOT env = 150 stocks, 1 seed. Output data/research/fii_systems(_pilot).json"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from trend_bt_global import load  # noqa: E402
import morning_check as MC  # noqa: E402
import ath_red_skip as AR  # noqa: E402
import light_distribution as LD  # noqa: E402
import fii_gate as FG  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def main():
    d, u = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"]).reset_index(drop=True)
    d["r63"] = d.groupby("SYMBOL").CLOSE.transform(lambda s: s / s.shift(63) - 1)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    G = FG.gates(nif.index)
    res = dict(method=__doc__, gates=FG.NAMES, share_allowed={k: round(float(G[k].loc["2016-06-01":].mean()) * 100) for k in FG.NAMES},
               t921={}, ath={}, nifty={})
    # ---------------- Nifty timing
    r = nif.pct_change().fillna(0)
    for nm, col in [("Nifty 50 always", None)] + [(FG.NAMES[k], k) for k in FG.NAMES]:
        on = G[col].astype(float) if col else pd.Series(1.0, index=nif.index)
        eq = (1 + r * on.shift(1).fillna(0) - on.diff().abs().fillna(0) * 0.001).loc["2016-06-01":].cumprod()
        res["nifty"][nm] = AR.report(eq, bull); print(f"R| Nifty | {nm} | {res['nifty'][nm]}", flush=True)
    # ---------------- 9/21
    for k in FG.NAMES:
        d["g_" + k] = G[k].reindex(d.Date.values).fillna(True).astype(bool).values
    for nm, gate in [("baseline (live)", None)] + [(FG.NAMES[k], "g_" + k) for k in FG.NAMES]:
        eq, T = MC.run(d, 10, 0.01, "r63", gate=gate)
        rp = AR.report(eq, bull); rp["trades"] = len(T); rp["avg trade"] = round(float(T.ret.mean() * 100), 2) if len(T) else None
        res["t921"][nm] = rp; print(f"R| 9/21 | {nm} | {rp}", flush=True)
    # ---------------- Monthly ATH (as tools/research/ath_red_skip.py)
    L = LD.light_series(d); days = list(L.index)
    import ath_scan as A
    tick = sorted(d.SYMBOL.unique()) if PILOT else list(u.ticker)
    today = date.today(); evs = []; C = {}
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x.index = pd.to_datetime(x.index).tz_localize(None)
                if len(x) < 300 or float(x.Close.iloc[-1]) < A.MIN_CLOSE:
                    continue
                e_, _, _ = A.analyse(t, x, today, lookback_days=0)
                got = False
                for rr in e_:
                    if rr["main"] and pd.Timestamp(rr["date"]) >= pd.Timestamp("2016-06-01"):
                        evs.append(dict(sym=t, d=pd.Timestamp(rr["date"]).normalize(), entry=float(rr["entry"]), sma=rr.get("sma_entry"),
                                        xd=pd.Timestamp(rr["exit_date"]).normalize() if rr["exit_date"] is not None else None,
                                        xp=float(rr["exit_price"]) if rr["exit_price"] is not None else np.nan)); got = True
                if got:
                    from adjust import fix_gaps
                    from session import drop_partial
                    xx = drop_partial(x, "NSE"); xx = xx[(xx.Close > 0) & (xx.High > 0)]
                    cc = fix_gaps(xx.Open, xx.High, xx.Low, xx.Close, xx.Volume)[3]
                    C[t] = pd.Series(cc, index=xx.index).loc["2016-01-01":].to_dict()
            except Exception as ex:  # noqa: BLE001
                print("ath skip", t, str(ex)[:80], flush=True)
        print("R| ath", a + len(chunk), "events", len(evs), flush=True)
        time.sleep(2)
    E = pd.DataFrame(evs); E["sma"] = pd.to_numeric(E.sma, errors="coerce")
    E["d"] = [days[min(len(days) - 1, L.index.searchsorted(x))] for x in E.d]
    for k in FG.NAMES:
        E[k] = G[k].reindex(E.d.values).fillna(True).astype(bool).values
    E["ret"] = E.xp / E.entry - 1
    res["ath_events"] = {"all": [len(E), round(float(E.ret.mean() * 100), 2)]}
    for k in FG.NAMES:
        res["ath_events"][FG.NAMES[k] + " - allowed"] = [int(E[k].sum()), round(float(E.ret[E[k]].mean() * 100), 2)]
        res["ath_events"][FG.NAMES[k] + " - blocked"] = [int((~E[k]).sum()), round(float(E.ret[~E[k]].mean() * 100), 2) if (~E[k]).any() else None]
    print("R| ATH events avg trade by gate", res["ath_events"], flush=True)
    seeds = (0,) if PILOT else (0, 1, 2)
    for sizing in ("live", "equal 10"):
        for gname, EE in [("baseline (live)", E)] + [(FG.NAMES[k], E[E[k]]) for k in FG.NAMES]:
            reps = []
            for sd in seeds:
                eq, T, _ = AR.sim(EE, C, days, "live" if sizing == "live" else "eq", None, sd)
                rp = AR.report(eq, bull); rp["trades"] = len(T); rp["avg trade"] = round(float(np.mean(T)) * 100, 2) if T else None
                reps.append(rp)
            m = {kk: round(float(np.mean([r_[kk] for r_ in reps if r_.get(kk) is not None])), 1) for kk in reps[0] if not isinstance(reps[0][kk], (dict, list)) and reps[0][kk] is not None}
            m["years"] = reps[0]["years"]
            res["ath"][f"{sizing} | {gname}"] = m
            print(f"R| ATH {sizing} | {gname} | {m}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/fii_systems" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
