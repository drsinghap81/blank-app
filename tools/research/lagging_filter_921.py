"""Rotation as a filter on the live Trend 9/21 swing system (20 Nov 2026, Amritpal: "Yes" to "block new buys in Lagging industries").
Signals / entry / stop / exit exactly as the live 9/21 (tools/trend_bt_global.py via tools/research/concentrated_921.run):
10 positions, 1% risk, random fill order (3 seeds), NSE stocks 2016 -> today from Yahoo (survivorship bias flatters every row equally).
Industry = NSE official basic industry (server map via data/scan/group_pulse.json 'nse' rows; stocks without one always pass).
Industry index = equal-weight of its stocks in the panel (3+ that day); weekly relative rotation vs Nifty 50 exactly as the app
(RS-ratio = 100 x RS / 10-week avg; momentum = 3-week avg of 100 x ratio / last week's) - the quadrant known at the signal day's close.
Variants: no filter | block Lagging | block Lagging + Weakening | only Improving + Leading. Plus every unfiltered trade tagged by
its industry's quadrant at entry. PILOT env = 400 stocks, 1 seed."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load, stats  # noqa: E402
import concentrated_921 as K  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
G = json.load(open("data/scan/group_pulse.json"))
IND_OF = {m["symbol"]: r["basic"] for r in G["nse"]["rows"] for m in r["members"]}

d, _ = load("NSE")
if PILOT:
    keep = sorted(d.SYMBOL.unique())[:400]; d = d[d.SYMBOL.isin(keep)]
d = d.sort_values(["SYMBOL", "Date"])
d["ind"] = d.SYMBOL.astype(str).str.replace(r"\.(NS|BO)$", "", regex=True).map(IND_OF)
print("R| sample symbols", list(d.SYMBOL.unique()[:5]), flush=True)
print("R| panel", d.SYMBOL.nunique(), "stocks;", int(d.ind.notna().groupby(d.SYMBOL).first().sum()), "with an NSE industry; signals", int(d.sig.sum()), flush=True)

C = d.pivot(index="Date", columns="SYMBOL", values="CLOSE").sort_index()
ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
nifty = yf.download("^NSEI", start="2015-06-01", progress=False, auto_adjust=True)["Close"]
nifty = (nifty.iloc[:, 0] if isinstance(nifty, pd.DataFrame) else nifty).reindex(C.index).ffill()
members = {}
for s, k in d.groupby("SYMBOL").ind.first().dropna().items():
    if s in ret.columns:
        members.setdefault(k, []).append(s)
idx = {}
for k, ss in members.items():
    r = ret[ss]; n = r.notna().sum(axis=1)
    idx[k] = (1 + r.mean(axis=1).where(n >= 3).fillna(0)).cumprod()
I = pd.DataFrame(idx)
W = I.resample("W-FRI").last(); NW = nifty.resample("W-FRI").last()
RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "Leading", "Weakening"), np.where(mom >= 100, "Improving", "Lagging")),
                 index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
Qd = Q.reindex(C.index, method="ffill")                 # a Friday's quadrant applies from that Friday's close on
st = Qd.stack(future_stack=True).rename("quad").reset_index().rename(columns={"level_1": "ind"})
st.columns = ["Date", "ind", "quad"]
d = d.merge(st, on=["Date", "ind"], how="left")
print("R| signals by industry quadrant:", d[d.sig].quad.fillna("none").value_counts().to_dict(), flush=True)

VAR = {"no filter": None, "block Lagging": {"Lagging"}, "block Lagging + Weakening": {"Lagging", "Weakening"},
       "only Improving + Leading": {"Lagging", "Weakening", "none"}}
seeds = (0,) if PILOT else (0, 1, 2)
for nm, block in (VAR.items() if not os.environ.get("NO_RUN") else []):
    x = d.copy()
    if block:
        q = x.quad.fillna("none")
        bad = q.isin(block) if "none" in block else (q.isin(block) & x.quad.notna())
        x["sig"] = x.sig & ~bad
    rs = []
    for sd in seeds:
        eq, T = K.run(x, 10, 0.01, "random", sd)
        a = stats(eq, "2017-01-01", "2030-01-01"); b = stats(eq, "2017-01-01", "2021-12-31"); c = stats(eq, "2022-01-01", "2030-01-01")
        rs.append((a["cagr"], a["maxdd"], b["cagr"], c["cagr"], len(T), T.ret.mean() * 100 if len(T) else 0))
        if nm == "no filter" and sd == 0 and len(T):
            T["entry"] = pd.to_datetime(T.entry)
            tq = T.merge(d[["SYMBOL", "Date", "quad"]].rename(columns={"SYMBOL": "sym", "Date": "entry"}), on=["sym", "entry"], how="left")
            for qq, g in tq.groupby(tq.quad.fillna("no industry")):
                print(f"R|   trades entered while industry {qq}: {len(g)}, avg {g.ret.mean() * 100:+.2f}%, win {np.mean(g.ret > 0) * 100:.0f}%", flush=True)
    m = np.array(rs)
    print(f"R| {nm}: CAGR {m[:, 0].mean():.1f}% (seeds {', '.join(f'{v:.1f}' for v in m[:, 0])}), max drawdown {m[:, 1].mean():.1f}%, "
          f"2017-21 {m[:, 2].mean():.1f}%, 2022-26 {m[:, 3].mean():.1f}%, trades {m[:, 4].mean():.0f}, avg trade {m[:, 5].mean():+.2f}%", flush=True)
