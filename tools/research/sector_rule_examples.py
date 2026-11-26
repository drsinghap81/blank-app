"""Example trades for the narrow-index 9/21 rule (26 Nov 2026, Amritpal: "give me examples and charts from the pilot").
Live Cup 9/21 and Momentum entries; the stock's narrow NSE index (size_index_trend_test.NARROW, else its sector index) must be
9/21 up at entry; the rule's exit = next day's close after that index closes with EMA 9 < EMA 21. Picks the trades where the rule
changed the result most (both ways) and prints, as R| JSON lines, daily closes of the stock and the index around the trade."""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import yfinance as yf  # noqa: E402

NARROW = {"Private Sector Bank": "NIFTY PRIVATE BANK", "Public Sector Bank": "NIFTY PSU BANK", "Pharmaceuticals": "NIFTY PHARMA",
          "Computers - Software & Consulting": "NIFTY IT", "Iron & Steel": "NIFTY METAL", "Diversified Metals": "NIFTY METAL",
          "Cement & Cement Products": "NIFTY COMMODITIES", "Diversified FMCG": "NIFTY FMCG", "Residential, Commercial Projects": "NIFTY REALTY",
          "Passenger Cars & Utility Vehicles": "NIFTY AUTO", "Auto Components & Equipments": "NIFTY AUTO", "2/3 Wheelers": "NIFTY AUTO",
          "Depositories Clearing Houses and Other Intermediaries": "NIFTY CAPITAL MARKETS", "Stockbroking & Allied": "NIFTY CAPITAL MARKETS",
          "Aerospace & Defense": "NIFTY INDIA DEFENCE", "Oil Exploration & Production": "NIFTY OIL & GAS", "Refineries & Marketing": "NIFTY OIL & GAS"}
FORCE = ["ICICIBANK", "HDFCBANK", "AXISBANK", "KOTAKBANK", "SBIN", "BANKBARODA", "FEDERALBNK", "INDUSINDBK", "INFY", "TCS", "SUNPHARMA", "TATASTEEL"]


def main():
    nif = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    # the pilot is the first 150 symbols A-Z; add a few banks / IT / pharma names so the Pvt Bank example is in
    try:
        d = yf.download([s + ".NS" for s in FORCE], start="2000-01-01", auto_adjust=True, progress=False, group_by="column", threads=True)
        for s in FORCE:
            t = s + ".NS"
            x = pd.DataFrame({"O": d["Open"][t], "H": d["High"][t], "L": d["Low"][t], "C": d["Close"][t], "V": d["Volume"][t]}).dropna()
            x = x[(x.C > 0) & (x.O > 0)]
            if len(x) > 400:
                x.index = pd.to_datetime(x.index).tz_localize(None); P[s] = x
    except Exception as e:  # noqa: BLE001
        print("force load", e)
    H = pd.read_csv("data/scan/sector_hist.csv.gz", parse_dates=["Date"]).pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index().ffill()
    SEC = json.load(open("data/scan/sectors.json")); ind_ix = SEC.get("industries") or {}
    G = json.load(open("data/scan/group_pulse.json"))
    ind_of = {m["symbol"]: r["basic"] for r in (G.get("nse") or {}).get("rows") or [] for m in r["members"]}
    T = []
    for s, x in P.items():
        nar = NARROW.get(ind_of.get(s)) if NARROW.get(ind_of.get(s)) in H.columns else ind_ix.get((SEC.get("symbols") or {}).get(s))
        if nar not in H.columns:
            continue
        ix = H[nar]; e9 = ix.ewm(span=9, adjust=False).mean(); e21 = ix.ewm(span=21, adjust=False).mean(); up = e9 > e21
        try:
            tr = AC.trades_for(s, x, reg)
        except Exception:  # noqa: BLE001
            continue
        for t in tr:
            if not ((t["sys"] == "tf" and t["v"] == "B") or (t["sys"] == "mom" and t["v"] == "C")) or t["d"] < pd.Timestamp("2017-01-01"):
                continue
            i0 = up.index.searchsorted(t["d"]) - 1
            if i0 < 0 or not bool(up.iloc[i0]):
                continue                                     # rule: index must be 9/21 up at entry
            seg = up[(up.index > t["d"]) & (up.index < t["dx"])]
            bad = seg[~seg]
            C = x.C
            if len(bad):
                k = C.index.searchsorted(bad.index[0]) + 1
                dn = C.index[min(k, len(C) - 1)]
                if dn >= t["dx"]:
                    dn = t["dx"]
            else:
                dn = t["dx"]
            c0 = C.asof(t["dx"]); c1 = C.asof(dn)
            r2 = (1 + t["ret"] + AC.COST) * c1 / c0 - 1 - AC.COST if dn < t["dx"] else t["ret"]
            T.append(dict(sym=s, sys=t["sys"], ix=nar, d=t["d"], dx=t["dx"], dn=dn, ret=t["ret"], ret_rule=r2, x=x, ixs=ix))
    print("R| trades", len(T), flush=True)
    T.sort(key=lambda z: z["ret_rule"] - z["ret"])
    pick = T[:3] + T[-3:]                                            # rule hurt most, rule helped most
    pick += [z for z in T if z["sym"] in FORCE[:8] and z not in pick][:3]  # bank examples
    for z in pick:
        x, ix = z["x"], z["ixs"]
        a = z["d"] - pd.Timedelta(days=120); b = max(z["dx"], z["dn"]) + pd.Timedelta(days=30)
        xs = x.loc[a:b]; ii = ix.loc[a:b]
        e9 = ix.ewm(span=9, adjust=False).mean().loc[a:b]; e21 = ix.ewm(span=21, adjust=False).mean().loc[a:b]
        out = dict(sym=z["sym"], sys={"tf": "Cup 9/21", "mom": "Momentum"}[z["sys"]], index=z["ix"], entry=str(z["d"].date()), own_exit=str(z["dx"].date()),
                   rule_exit=str(z["dn"].date()), ret_own=round(z["ret"] * 100, 1), ret_rule=round(z["ret_rule"] * 100, 1),
                   t=[str(d_.date()) for d_ in xs.index], o=xs.O.round(2).tolist(), h=xs.H.round(2).tolist(), l=xs.L.round(2).tolist(), c=xs.C.round(2).tolist(),
                   it=[str(d_.date()) for d_ in ii.index], ic=ii.round(1).tolist(), e9=e9.round(1).tolist(), e21=e21.round(1).tolist())
        print("R|EX " + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
