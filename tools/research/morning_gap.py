"""Pre-market check on the entry day for 9/21 and ATH (22 Nov 2026, Amritpal: "true for all other systems too" - after the Pulse
rotation pre-market / first-hour test, tools/research/pulse_morning.py).

The NSE pre-open auction (09:00-09:08) sets the opening price, so "pre-market green" = the entry day's OPEN above the previous
CLOSE. Checks, decided at the open, buy at the open as now (skipped entries are simply not taken):
  baseline     no check (live)
  stock green  the stock opens above yesterday's close
  industry green  its NSE basic industry (equal weight of the panel's members, group_pulse NSE map) opens above yesterday's close
  no chase     skip a stock gapping up more than 2%
9/21: live engine (tools/research/morning_check.run = concentrated_921.run + entry-day gate), 10 positions, 1% risk, 3-month
strength ranking, NSE 2016-26 Yahoo survivors. ATH: tools/research/ath_red_skip events (live scanner rules), live sizing (2% risk
to the 30-week SMA, max 20%) and equal 10, 3 random orders. The first-hour check needs hourly bars (Yahoo keeps ~2 years) and
is only in the Pulse rotation test.
PILOT env = 150 stocks, 1 seed. Output data/research/morning_gap(_pilot).json"""
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

PILOT = bool(os.environ.get("PILOT"))
MK = os.environ.get("MARKET", "NSE")          # 22 Nov 2026 ("all triggers worldwide"): US / ASX / UK run the 9/21 part with their own groups
GP_PATH = {"NSE": None, "US": "data/scan/us/group_pulse.json", "ASX": "data/scan/asx/group_pulse.json", "UK": "data/scan/uk/group_pulse.json"}


def main():
    d, u = load(MK)
    if MK != "NSE":
        from global_universe import MARKETS
        MC.CFG = MARKETS[MK]
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"]).reset_index(drop=True)
    g = d.groupby("SYMBOL").CLOSE
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    d["gap"] = d.OPEN / g.shift(1) - 1
    if MK == "NSE":
        G = json.load(open("data/scan/group_pulse.json"))["nse"]["rows"]
        s2i = {m["symbol"]: r["basic"] for r in G for m in r["members"]}
    else:
        G = json.load(open(GP_PATH[MK]))["rows"]
        s2i = {m["symbol"]: r["group"] for r in G for m in r["members"]}
    d["industry"] = d.SYMBOL.str.replace(r"\.(NS|AX|L|BO)$", "", regex=True).map(s2i)
    ig = d.dropna(subset=["industry"]).groupby(["industry", "Date"]).gap.mean()
    d["ind_gap"] = [ig.get((i, dt), np.nan) if isinstance(i, str) else np.nan for i, dt in zip(d.industry, d.Date)]
    d["g_stock"] = d.gap > 0
    d["g_ind"] = d.ind_gap.isna() | (d.ind_gap > 0)                 # no industry mapped -> no veto
    d["g_chase"] = d.gap <= 0.02
    nif = yf.download({"NSE": "^NSEI", "US": "^GSPC", "ASX": "^AXJO", "UK": "^FTSE"}[MK], start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    res = dict(method=__doc__, coverage_industry_pct=round(float(d.industry.notna().mean() * 100), 1), t921={}, ath={})
    print("R| panel", d.SYMBOL.nunique(), "industry coverage", res["coverage_industry_pct"], flush=True)
    # ---------------- 9/21
    for name, gate in (("baseline (live)", None), ("stock opens green", "g_stock"), ("industry opens green", "g_ind"), ("no chase (gap <= 2%)", "g_chase")):
        eq, T = MC.run(d, 10, 0.01, "r63", gate=gate)
        rp = AR.report(eq, bull); rp["trades"] = len(T); rp["avg trade"] = round(float(T.ret.mean() * 100), 2) if len(T) else None
        res["t921"][name] = rp; print(f"R| 9/21 | {name} | {rp}", flush=True)
    if MK != "NSE":
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open(f"data/research/morning_gap_{MK}" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)
        return
    # ---------------- ATH (events as tools/research/ath_red_skip.py)
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
                for r in e_:
                    if r["main"] and pd.Timestamp(r["date"]) >= pd.Timestamp("2016-06-01"):
                        dt = pd.Timestamp(r["date"]).normalize(); i = x.index.searchsorted(dt)
                        gp = float(x.Open.iloc[i] / x.Close.iloc[i - 1] - 1) if 0 < i < len(x) else np.nan
                        evs.append(dict(sym=t, d=dt, entry=float(r["entry"]), sma=r.get("sma_entry"), gap=gp,
                                        xd=pd.Timestamp(r["exit_date"]).normalize() if r["exit_date"] is not None else None,
                                        xp=float(r["exit_price"]) if r["exit_price"] is not None else np.nan)); got = True
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
    E["ind"] = E.sym.str.replace(".NS", "", regex=False).map(s2i)
    E["ind_gap"] = [ig.get((i, dt), np.nan) if isinstance(i, str) else np.nan for i, dt in zip(E.ind, E.d)]
    E["d"] = [days[min(len(days) - 1, L.index.searchsorted(x))] for x in E.d]
    gates = {"baseline (live)": E, "stock opens green": E[E.gap > 0], "industry opens green": E[E.ind_gap.isna() | (E.ind_gap > 0)],
             "no chase (gap <= 2%)": E[~(E.gap > 0.02)]}
    seeds = (0,) if PILOT else (0, 1, 2)
    for sizing in ("live", "equal 10"):
        for gname, EE in gates.items():
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
    json.dump(res, open("data/research/morning_gap" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
