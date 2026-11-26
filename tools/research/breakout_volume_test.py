"""Breakout-candle volume filter (26 Nov 2026, Amritpal: "breakout candle volume should be extraordinary").
Live Cup 9/21 (wick close) and Momentum (close confirm) entries, NSE 2017-26, 0.4% costs, 10-slot portfolio (ath_confirm_test.port).
Breakout candle = the session before the fill (the close-confirm day). Volume ratio = its volume / the average of the 50 sessions
before it. Buckets and minimum-ratio filters, with and without the live industry lane."""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import combo_compare as CC  # noqa: E402
import yfinance as yf  # noqa: E402


def main():
    nif = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index(); V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, V = C[ok], V[ok]
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    LN = CC.lanes(C, V, nif.reindex(C.index).ffill(), IND)
    T = []
    for s, x in P.items():
        try:
            tr = AC.trades_for(s, x, reg)
        except Exception as e:  # noqa: BLE001
            print("err", s, e); continue
        v50 = x.V.rolling(50).mean().shift(1)
        for t in tr:
            if not ((t["sys"] == "tf" and t["v"] == "B") or (t["sys"] == "mom" and t["v"] == "C")) or t["d"] < pd.Timestamp("2017-01-01"):
                continue
            i = x.index.searchsorted(t["d"]) - 1                    # breakout (close-confirm) candle
            if i < 51:
                continue
            vr = float(x.V.iloc[i] / v50.iloc[i]) if v50.iloc[i] > 0 else np.nan
            g = ind_of.get(s)
            ln = LN[g].iloc[max(LN.index.searchsorted(t["d"]) - 1, 0)] if g and g in LN.columns else "none"
            T.append(dict(t, vr=vr, lane=ln))
    T = pd.DataFrame(T).dropna(subset=["vr"])
    print(f"R| trades {len(T)}; median breakout volume {T.vr.median():.2f}x the 50-day average", flush=True)
    lane_ok = ~T.lane.isin(["weak", "fade", "bounce"])
    for sysk, lab in (("tf", "CUP 9/21"), ("mom", "MOMENTUM")):
        print(f"R| ===== {lab} =====", flush=True)
        X0 = T[T.sys == sysk]
        for lo, hi in ((0, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 99)):
            X = X0[(X0.vr >= lo) & (X0.vr < hi)]
            if len(X):
                print(f"R| bucket {lo:>3}-{hi:<3}x  n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {X[X.d >= '2024-01-01'].ret.mean() * 100:+6.2f}%", flush=True)
        for nm, m in [("all", X0.index == X0.index), ("lane (live)", lane_ok[X0.index])] + [(f"volume >= {k}x", X0.vr >= k) for k in (1.5, 2, 3, 5)] + \
                     [(f"lane + volume >= {k}x", lane_ok[X0.index] & (X0.vr >= k)) for k in (1.5, 2, 3, 5)]:
            X = X0[m]
            if len(X) < 20:
                print(f"R| {nm:24s} n {len(X)}", flush=True); continue
            cg, dd = AC.port(X); xr = X[X.d >= "2024-01-01"]; xb = X[X.d >= "2021-07-01"]
            print(f"R| {nm:24s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {xr.ret.mean() * 100:+6.2f}% (n {len(xr)}) | Jul21+ {xb.ret.mean() * 100:+6.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)


if __name__ == "__main__":
    main()
