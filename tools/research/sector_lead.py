"""Can we see money flowing into an industry BEFORE it moves? (19 Nov 2026, Amritpal: "we should know in advance").
Equal-weight industry series from member stocks (NSE, Yahoo 2016 -> today; industry = today's NSE classification in
data/scan/sectors.json; liquid >= Rs 2 cr/day). Daily signals per industry, known at the close:
  S1 quiet accumulation : share of the last 10 days' traded value that traded on up days (up-value ratio), high = buying
  S2 money-flow index   : 10-day sum of value x close-location ((C-L)-(H-C))/(H-L), / 10-day value
  S3 breadth thrust     : share of members above their 20-day average rose from < 40% to > 60% within 10 days (event)
  S4 RS turn            : the industry's 20-day return minus Nifty's turned from negative to positive today (event)
  S5 volume surge, quiet price: 5-day value / 50-day value >= 1.3 while the industry's 5-day return is within +/-2%
Targets: the industry's next 5 and 20 trading days' return minus Nifty's. For S1/S2: top fifth of industries that day vs bottom
fifth (average excess return) and rank correlation (IC); for events: average excess return after the event vs all days.
Output: data/research/sector_lead.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402


def main():
    S = json.load(open("data/scan/sectors.json")); ind = S["symbols"]
    u = symbols("NSE"); tick = [t for t in u.ticker if ind.get(t[:-3])]
    O, H, L, Cl, V = [], [], [], [], []
    for i in range(0, len(tick), 200):
        for _ in range(3):
            try:
                D = yf.download(tick[i:i + 200], start="2015-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20); D = None
        if D is None or D.empty:
            continue
        O.append(D["Open"]); H.append(D["High"]); L.append(D["Low"]); Cl.append(D["Close"]); V.append(D["Volume"])
        print("downloaded", i + 200, flush=True); time.sleep(2)
    H, L, Cl, V = (pd.concat(x, axis=1) for x in (H, L, Cl, V))
    nif = yf.download("^NSEI", start="2015-06-01", auto_adjust=True, progress=False)["Close"].squeeze().reindex(Cl.index).ffill()
    val = Cl * V; liq = val.rolling(20).mean() >= 2e7
    ret = Cl.pct_change().where(liq)
    clv = (((Cl - L) - (H - Cl)) / (H - L)).replace([np.inf, -np.inf], np.nan)
    a20 = (Cl > Cl.rolling(20).mean()).where(liq)
    groups = {}
    for t in Cl.columns:
        groups.setdefault(ind[t[:-3]], []).append(t)
    groups = {g: m for g, m in groups.items() if len(m) >= 8}
    R, S1, S2, S3, S4, S5 = {}, {}, {}, {}, {}, {}
    nr = nif.pct_change()
    for g, m in groups.items():
        r = ret[m].mean(axis=1); idx = (1 + r.fillna(0)).cumprod(); R[g] = idx
        vv = val[m].where(liq[m])
        upv = vv.where(ret[m] > 0, 0).sum(axis=1).rolling(10).sum(); tot = vv.sum(axis=1).rolling(10).sum()
        S1[g] = upv / tot
        S2[g] = (vv * clv[m]).sum(axis=1).rolling(10).sum() / tot
        br = a20[m].mean(axis=1); S3[g] = (br > 0.6) & (br.rolling(10).min() < 0.4) & ~((br.shift(1) > 0.6) & (br.shift(1).rolling(10).min() < 0.4))
        rs = idx.pct_change(20) - nif.pct_change(20); S4[g] = (rs > 0) & (rs.shift(1) <= 0)
        tv = vv.sum(axis=1); S5[g] = ((tv.rolling(5).mean() / tv.rolling(50).mean()) >= 1.3) & (idx.pct_change(5).abs() <= 0.02)
    R = pd.DataFrame(R)
    res = dict(method=__doc__, industries=len(groups))
    for h in (5, 20):
        fwd = R.shift(-h) / R - 1
        fx = fwd.sub(nif.shift(-h) / nif - 1, axis=0)
        fx = fx[fx.index >= "2016-06-01"].iloc[:-h]
        for name, Sg in (("S1 up-value ratio", S1), ("S2 money-flow index", S2)):
            X = pd.DataFrame(Sg).reindex(fx.index)
            ic = X.rank(axis=1).corrwith(fx.rank(axis=1), axis=1).mean()
            q = X.rank(axis=1, pct=True)
            top, bot = fx[q >= 0.8].stack().mean(), fx[q <= 0.2].stack().mean()
            yrs = {}
            for y in sorted(set(fx.index.year)):
                m_ = fx.index.year == y
                yrs[str(y)] = round(float((fx[m_][q[m_] >= 0.8].stack().mean() - fx[m_][q[m_] <= 0.2].stack().mean()) * 100), 2)
            res[f"{name} | next {h} d"] = dict(ic=round(float(ic), 3), top_fifth=round(float(top) * 100, 2), bottom_fifth=round(float(bot) * 100, 2),
                                                 spread=round(float(top - bot) * 100, 2), spread_by_year=yrs)
            print("R|", name, h, res[f"{name} | next {h} d"], flush=True)
        allm = fx.stack().mean()
        for name, Sg in (("S3 breadth thrust", S3), ("S4 RS turns positive", S4), ("S5 volume surge, quiet price", S5)):
            X = pd.DataFrame(Sg).reindex(fx.index).fillna(False).astype(bool)
            ev = fx[X].stack()
            res[f"{name} | next {h} d"] = dict(events=int(len(ev)), after_event=round(float(ev.mean()) * 100, 2), all_days=round(float(allm) * 100, 2),
                                                 win=round(float((ev > 0).mean()) * 100))
            print("R|", name, h, res[f"{name} | next {h} d"], flush=True)
    # today's readings (for the app card if any signal works)
    last = {g: dict(S1=round(float(S1[g].iloc[-1]), 3), S2=round(float(S2[g].iloc[-1]), 3), S3=bool(S3[g].iloc[-10:].any()),
                    S4=bool(S4[g].iloc[-5:].any()), S5=bool(S5[g].iloc[-1])) for g in groups}
    res["latest"] = last
    for g, v in sorted(last.items(), key=lambda kv: -kv[1]["S1"]):
        print("T|", g, v)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/sector_lead.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
