"""ASX Materials clue as a filter for Indian METAL stocks intraday (20 Nov 2026, Amritpal: "Yes" - test it for the 5-minute option
trader). The option trader's own history is only ~3 weeks of 5-minute candles, so this uses daily open->close of the metal F&O
stocks 2016-26 as the proxy for "is today a CE day or a PE day".
Clue = ASX 200 Materials (^AXMJ) minus ASX 200 (^AXJO), same date (full ASX day; at 09:15 IST ~80% of it is known).
  strong  > +1%   weak  < -1%   (also +-0.5%)
Per stock: open->close (absolute: what a CE / PE trader gets) and minus Nifty open->close. Filter: CE only when not weak, PE only
when not strong. Output: data/research/asx_metal_filter.json"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

METALS = ["TATASTEEL", "HINDALCO", "JSWSTEEL", "SAIL", "VEDL", "NMDC", "NATIONALUM", "JINDALSTEL", "HINDZINC", "COALINDIA", "JSL", "HINDCOPPER"]


def main():
    t = [m + ".NS" for m in METALS] + ["^NSEI", "^AXMJ", "^AXJO"]
    D = yf.download(t, start="2015-06-01", auto_adjust=False, progress=False)
    O, C = D["Open"], D["Close"]
    O.index = C.index = pd.to_datetime(C.index).tz_localize(None)
    ax = C["^AXMJ"].pct_change() - C["^AXJO"].pct_change()
    ax = ax.dropna()
    oc = (C / O - 1).where(O > 0)
    nif = oc["^NSEI"]
    res = {"method": __doc__}
    rows = []
    for m in METALS:
        s = m + ".NS"
        if s not in oc:
            continue
        z = pd.DataFrame({"oc": oc[s], "ex": oc[s] - nif, "ax": ax.reindex(oc.index)}).dropna()
        z = z[z.oc.abs() < 0.2]
        z["m"] = m
        rows.append(z)
    Z = pd.concat(rows)
    print("stock-days", len(Z), "stocks", Z.m.nunique(), flush=True)
    def st(x):
        return dict(n=len(x), avg=round(float(x.mean() * 100), 3), up=round(float((x > 0).mean() * 100)))
    for th in (0.005, 0.01):
        for lab, msk in (("strong", Z.ax > th), ("weak", Z.ax < -th), ("neutral", Z.ax.abs() <= th)):
            r = dict(oc=st(Z.oc[msk]), vs_nifty=st(Z.ex[msk]))
            for half, hm in (("2016-20", Z.index < "2021-01-01"), ("2021-26", Z.index >= "2021-01-01")):
                r[half] = st(Z.oc[msk & hm])
            res[f"{lab} {th * 100:g}%"] = r
            print("R|", f"{lab} {th * 100:g}%", r, flush=True)
    res["all days"] = dict(oc=st(Z.oc), vs_nifty=st(Z.ex))
    print("R| all days", res["all days"], flush=True)
    # filter on a simple directional day trader: CE = long open->close, PE = short open->close
    for th in (0.005, 0.01):
        ce_all, pe_all = Z.oc, -Z.oc
        ce_f, pe_f = Z.oc[Z.ax >= -th], -Z.oc[Z.ax <= th]
        res[f"filter {th * 100:g}%"] = dict(CE_all=st(ce_all), CE_skip_weak=st(ce_f), PE_all=st(pe_all), PE_skip_strong=st(pe_f),
                                           CE_only_strong=st(Z.oc[Z.ax > th]), PE_only_weak=st(-Z.oc[Z.ax < -th]))
        print("F|", th, res[f"filter {th * 100:g}%"], flush=True)
    by = {m: dict(strong=st(g.oc[g.ax > 0.01]), weak=st(g.oc[g.ax < -0.01])) for m, g in Z.groupby("m")}
    res["by_stock"] = by
    for m, v in by.items():
        print("S|", m, v, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/asx_metal_filter.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
