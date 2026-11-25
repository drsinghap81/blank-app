"""Size-index trend filter (26 Nov 2026, Amritpal: "if Nifty itself is not trending I won't trade its stocks, or similarly if Midcap
is not in trend as per our filters then I won't trade").

Live entries (Cup 9/21 wick close, Momentum close confirm, next day + 0.15%), NSE 2007-26, 0.4% costs, 10-slot portfolio
(ath_confirm_test.port). Point-in-time size by 60-day traded value: large = top 100, mid = 101-250, small = rest.
Size indices: equal-weight daily returns of each size group that day (no survivor index list needed), plus the real Nifty 50
(^NSEI) for large caps. "Trending" = the Pulse rules applied to the index: EMA 9 > EMA 21, above a rising 150-day average
(Stage 2) and within 25% of its 52-week high; mid / small also tested with "and beating the Nifty over 3 months".
Also with the live industry lane (skip Weak / Fading / Turning)."""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import combo_compare as CC  # noqa: E402
import yfinance as yf  # noqa: E402


def trend(ix):
    e9 = ix.ewm(span=9, adjust=False).mean(); e21 = ix.ewm(span=21, adjust=False).mean(); s150 = ix.rolling(150).mean()
    hi = ix.rolling(250, min_periods=120).max()
    return (e9 > e21) & (ix > s150) & (s150 > s150.shift(20)) & (ix >= 0.75 * hi), (ix > s150) & (s150 > s150.shift(20))


def main():
    nif = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index()
    Vv = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, Vv = C[ok], Vv[ok]
    V = (C * Vv).rolling(60, min_periods=40).mean()
    rank = V.rank(axis=1, ascending=False)
    R1 = (C / C.shift(1) - 1).clip(-0.3, 0.3)
    grp = {"large": rank <= 100, "mid": (rank > 100) & (rank <= 250), "small": rank > 250}
    IX = {k: (1 + R1.where(m.shift(1, fill_value=False)).mean(axis=1).fillna(0)).cumprod() for k, m in grp.items()}
    n_ = nif.reindex(C.index).ffill()
    TR, ST = {}, {}
    for k, ix in IX.items():
        TR[k], ST[k] = trend(ix)
    TR["nifty"], ST["nifty"] = trend(n_)
    beat = {k: (IX[k] / IX[k].shift(63)) > (n_ / n_.shift(63)) for k in ("mid", "small")}
    for k in TR:
        print(f"R| {k} index trending on {TR[k].mean() * 100:.0f}% of days (Stage 2 only {ST[k].mean() * 100:.0f}%)", flush=True)
    # industry lanes (live rule)
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    LN = CC.lanes(C, Vv, n_, IND)
    T = []
    for s, x in P.items():
        try:
            T += AC.trades_for(s, x, reg)
        except Exception as e:  # noqa: BLE001
            print("err", s, e)
    T = pd.DataFrame(T); T = T[(T.d >= "2007-01-01") & (((T.sys == "tf") & (T.v == "B")) | ((T.sys == "mom") & (T.v == "C")))].copy()

    def prev(S, d):
        i = S.index.searchsorted(d) - 1
        return S.iloc[i] if i >= 0 else np.nan
    T["rk"] = [prev(rank[s], d) if s in rank.columns else np.nan for d, s in zip(T.d, T.sym)]
    T["size"] = np.where(T.rk <= 100, "large", np.where(T.rk <= 250, "mid", "small"))
    for k in TR:
        T["tr_" + k] = [bool(prev(TR[k], d)) for d in T.d]; T["st_" + k] = [bool(prev(ST[k], d)) for d in T.d]
    for k in beat:
        T["bt_" + k] = [bool(prev(beat[k], d)) for d in T.d]
    T["lane"] = [(LN[ind_of[s]].iloc[max(LN.index.searchsorted(d) - 1, 0)] if s in ind_of and ind_of[s] in LN.columns else "none") for d, s in zip(T.d, T.sym)]
    own = np.select([T["size"] == "large", T["size"] == "mid"], [T.tr_large, T.tr_mid], T.tr_small).astype(bool)
    own_n = np.select([T["size"] == "large", T["size"] == "mid"], [T.tr_nifty, T.tr_mid], T.tr_small).astype(bool)
    own_st = np.select([T["size"] == "large", T["size"] == "mid"], [T.st_large, T.st_mid], T.st_small).astype(bool)
    own_bt = np.select([T["size"] == "large", T["size"] == "mid"], [T.tr_nifty, T.tr_mid & T.bt_mid], T.tr_small & T.bt_small).astype(bool)
    T["own_n"] = own_n
    lane_ok = ~T.lane.isin(["weak", "fade", "bounce"])
    F = {"all (old rules)": T.index == T.index,
         "lane (LIVE now)": lane_ok,
         "own size index trending (equal-weight)": own,
         "own size index trending (Nifty 50 for large)": own_n,
         "own size index Stage 2 only": own_st,
         "own size index trending and beating Nifty": own_bt,
         "Nifty 50 trending (all sizes)": T.tr_nifty,
         "lane + own size index trending": lane_ok & own_n,
         "lane + own size index Stage 2": lane_ok & own_st,
         "own size index NOT trending (the skipped ones)": ~own_n}
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 20:
                print(f"R| {nm:48s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; xr = X[X.d >= "2024-01-01"]; xc = X[~X.d.between(*AC.COVID)]; cg, dd = AC.port(X)
            print(f"R| {nm:48s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {xr.ret.mean() * 100:+6.2f}% (n {len(xr)})"
                  f" | Jul21+ {xb.ret.mean() * 100:+6.2f}% | ex-Covid {xc.ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        X = T[T.sys == sysk]
        y = X.groupby(X.d.dt.year).apply(lambda g: f"{len(g)} lane {g[~g.lane.isin(['weak', 'fade', 'bounce'])].ret.mean() * 100:+.1f}% / lane+size {g[(~g.lane.isin(['weak', 'fade', 'bounce'])) & g.own_n].ret.mean() * 100:+.1f}%")
        print(f"R| {sysk} by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:10]), flush=True)


if __name__ == "__main__":
    main()
