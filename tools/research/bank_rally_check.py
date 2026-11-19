"""Bank / financials rally of Nov 2026: did our 9/21 entry rule see it? (19 Nov 2026, Amritpal)
For every Financial Services stock (NSE classification) + Bank Nifty: return from the 27 Oct close to the latest close, every EMA 9/21
cross-up since 20 Oct, and which of the live early-entry conditions passed or failed on that day:
  close > EMA50, EMA50 above its level 10 sessions ago, RSI14 >= 55, Supertrend(10,3) green, close >= 70% of 52w high, >= Rs 1 cr/day."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from trend_scan import rsi, supertrend  # noqa: E402


def main():
    S = json.load(open("data/scan/sectors.json"))["symbols"]
    syms = sorted(s for s, g in S.items() if g == "Financial Services")
    D = yf.download([s + ".NS" for s in syms] + ["^NSEBANK", "^NSEI"], start="2025-09-01", auto_adjust=True, progress=False, group_by="ticker")
    out = []
    for t in [s + ".NS" for s in syms] + ["^NSEBANK", "^NSEI"]:
        try:
            x = D[t].dropna()
        except KeyError:
            continue
        if len(x) < 130:
            continue
        o, h, l, c, v = x.Open, x.High, x.Low, x.Close, x.Volume
        e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
        r = rsi(c); hi = c.rolling(250, min_periods=60).max(); val = (c * v).rolling(20).mean() / 1e7
        sd, _ = supertrend(h.values, l.values, c.values); sd = pd.Series(sd, index=c.index)
        val_ok = (val >= 1) if t.endswith(".NS") else pd.Series(True, index=c.index)
        base = c.loc[:"2026-10-27"].iloc[-1]
        rec = dict(sym=t.replace(".NS", ""), ret_since_27oct=round(float(c.iloc[-1] / base - 1) * 100, 1), value_cr=round(float(val.iloc[-1]), 1), crosses=[])
        cross = (e9 > e21) & (e9.shift(1) <= e21.shift(1))
        for dt in cross[cross & (cross.index >= "2026-10-20")].index:
            fails = [k for k, ok in (("close<EMA50", c[dt] > e50[dt]), ("EMA50 falling", e50[dt] > e50.shift(10)[dt]), (f"RSI {r[dt]:.0f}<55", r[dt] >= 55),
                                     ("Supertrend red", sd[dt] == 1), ("far from high", c[dt] >= 0.7 * hi[dt]), ("illiquid", bool(val_ok[dt]))) if not ok]
            rec["crosses"].append(dict(date=str(dt.date()), ret_after=round(float(c.iloc[-1] / c[dt] - 1) * 100, 1), fails=fails))
        # when would it have passed later (first day after 27 Oct with e9>e21 and all other conditions true)
        ok = (e9 > e21) & (c > e50) & (e50 > e50.shift(10)) & (r >= 55) & (sd == 1) & (c >= 0.7 * hi) & val_ok
        okd = ok[ok.index > "2026-10-27"]
        rec["first_all_ok"] = str(okd[okd].index[0].date()) if okd.any() else None
        rec["ret_after_first_ok"] = round(float(c.iloc[-1] / c[okd[okd].index[0]] - 1) * 100, 1) if okd.any() else None
        out.append(rec)
    out.sort(key=lambda z: -z["ret_since_27oct"])
    for z in out[:45]:
        print("B|", json.dumps(z), flush=True)
    liq = [z for z in out if z["value_cr"] >= 1 and z["sym"][0] != "^"]
    print("S|", json.dumps(dict(stocks=len(liq), median_ret=float(np.median([z["ret_since_27oct"] for z in liq])),
                                 any_cross=sum(1 for z in liq if z["crosses"]),
                                 cross_passed=sum(1 for z in liq if any(not k["fails"] for k in z["crosses"])),
                                 fail_counts=pd.Series([f.split(" ")[0] + (" " + f.split(" ")[1] if f.startswith("EMA50") else "") for z in liq for k in z["crosses"] for f in k["fails"]]).value_counts().to_dict())))


if __name__ == "__main__":
    main()
