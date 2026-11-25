"""Index trend filters - market, size, sector, industry, theme (Size-index trend filter (26 Nov 2026, Amritpal: "if Nifty itself is not trending I won't trade its stocks, or similarly if Midcap
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
    # 26 Nov 2026 (Amritpal: "ideally market, index, sector, industry, theme should all be trending as per our filter"): real NSE
    # indices (data/scan/sector_hist.csv.gz, Nov 2015 on) - Nifty 500 market, Nifty 50 / Midcap 150 / Smallcap 250 by size,
    # the stock's sector index and its theme indices (sectors.json, today's membership); industry = the live Pulse lane
    H = pd.read_csv("data/scan/sector_hist.csv.gz", parse_dates=["Date"]).pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index().ffill()
    n500 = H["NIFTY 500"]
    TRI, STI = {}, {}
    for k in H.columns:
        TRI[k], STI[k] = trend(H[k])
    RS = {k: (H[k] / H[k].shift(63)) > (n500 / n500.shift(63)) for k in H.columns}         # beating the market over 3 months
    SEC = json.load(open("data/scan/sectors.json")); ind_ix = SEC.get("industries") or {}
    sec_of = {s: ind_ix.get(i) for s, i in (SEC.get("symbols") or {}).items()}
    th_of = {s: [t for t in v if t in H.columns] for s, v in (SEC.get("themes") or {}).items()}
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index()
    Vv = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, Vv = C[ok], Vv[ok]
    V = (C * Vv).rolling(60, min_periods=40).mean()
    rank = V.rank(axis=1, ascending=False)
    n_ = nif.reindex(C.index).ffill()
    for k in ("NIFTY 500", "NIFTY 50", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"):
        print(f"R| {k} trending on {TRI[k][TRI[k].index >= '2016-11-01'].mean() * 100:.0f}% of days since Nov 2016 (Stage 2 only {STI[k][STI[k].index >= '2016-11-01'].mean() * 100:.0f}%)", flush=True)
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
    T = pd.DataFrame(T); T = T[(T.d >= "2017-01-01") & (((T.sys == "tf") & (T.v == "B")) | ((T.sys == "mom") & (T.v == "C")))].copy().reset_index(drop=True)

    def prev(S, d):
        i = S.index.searchsorted(d) - 1
        return S.iloc[i] if i >= 0 else np.nan

    def on(D_, k, d):
        return bool(prev(D_[k], d)) if k in D_ else None
    T["rk"] = [prev(rank[s], d) if s in rank.columns else np.nan for d, s in zip(T.d, T.sym)]
    T["size"] = np.where(T.rk <= 100, "large", np.where(T.rk <= 250, "mid", "small"))
    SZ = {"large": "NIFTY 50", "mid": "NIFTY MIDCAP 150", "small": "NIFTY SMALLCAP 250"}
    T["mkt"] = [on(TRI, "NIFTY 500", d) for d in T.d]; T["mkt_s2"] = [on(STI, "NIFTY 500", d) for d in T.d]
    T["size_tr"] = [on(TRI, SZ[z], d) for z, d in zip(T["size"], T.d)]; T["size_s2"] = [on(STI, SZ[z], d) for z, d in zip(T["size"], T.d)]
    T["size_rs"] = [bool(on(TRI, SZ[z], d)) and (z == "large" or bool(on(RS, SZ[z], d))) for z, d in zip(T["size"], T.d)]
    T["has_sec"] = [sec_of.get(s) in H.columns for s in T.sym]
    T["sec_tr"] = [on(TRI, sec_of[s], d) if h else None for s, d, h in zip(T.sym, T.d, T.has_sec)]
    T["sec_s2"] = [on(STI, sec_of[s], d) if h else None for s, d, h in zip(T.sym, T.d, T.has_sec)]
    T["sec_rs"] = [bool(on(TRI, sec_of[s], d)) and bool(on(RS, sec_of[s], d)) if h else None for s, d, h in zip(T.sym, T.d, T.has_sec)]
    T["has_th"] = [bool(th_of.get(s)) for s in T.sym]
    T["th_tr"] = [any(on(TRI, t, d) for t in th_of[s]) if h else None for s, d, h in zip(T.sym, T.d, T.has_th)]
    T["lane"] = [(LN[ind_of[s]].iloc[max(LN.index.searchsorted(d) - 1, 0)] if s in ind_of and ind_of[s] in LN.columns else "none") for d, s in zip(T.d, T.sym)]
    lane_ok = ~T.lane.isin(["weak", "fade", "bounce"]); lane_strong = T.lane.isin(["build", "hold"])
    yes = lambda c: T[c].fillna(True).astype(bool)          # noqa: E731  no sector / theme index known -> not blocked
    F = {"all (old rules)": T.index == T.index,
         "1 industry lane OK (LIVE now)": lane_ok,
         "2 market (Nifty 500) trending": yes("mkt"),
         "3 own size index trending": yes("size_tr"),
         "4 sector index trending": yes("sec_tr"),
         "5 any theme index trending": yes("th_tr"),
         "6 industry lane Building/Holding only": lane_strong,
         "lane + market": lane_ok & yes("mkt"),
         "lane + market + size": lane_ok & yes("mkt") & yes("size_tr"),
         "lane + market + size + sector": lane_ok & yes("mkt") & yes("size_tr") & yes("sec_tr"),
         "ALL: lane + market + size + sector + theme": lane_ok & yes("mkt") & yes("size_tr") & yes("sec_tr") & yes("th_tr"),
         "ALL, sector/size also beating market": lane_ok & yes("mkt") & yes("size_rs") & yes("sec_rs") & yes("th_tr"),
         "ALL, Stage 2 only (softer)": lane_ok & yes("mkt_s2") & yes("size_s2") & yes("sec_s2"),
         "lane + sector": lane_ok & yes("sec_tr"),
         "skipped by ALL (lane OK but some index not trending)": lane_ok & ~(yes("mkt") & yes("size_tr") & yes("sec_tr") & yes("th_tr"))}
    T["all_ok"] = F["ALL: lane + market + size + sector + theme"]
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 20:
                print(f"R| {nm:52s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; xr = X[X.d >= "2024-01-01"]; xc = X[~X.d.between(*AC.COVID)]; cg, dd = AC.port(X)
            print(f"R| {nm:52s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {xr.ret.mean() * 100:+6.2f}% (n {len(xr)})"
                  f" | Jul21+ {xb.ret.mean() * 100:+6.2f}% | ex-Covid {xc.ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        X = T[T.sys == sysk]
        y = X.groupby(X.d.dt.year).apply(lambda g: f"lane {len(g[g.lane.isin(['build', 'hold', 'mid', 'none'])])} {g[~g.lane.isin(['weak', 'fade', 'bounce'])].ret.mean() * 100:+.1f}% / ALL {int(g.all_ok.sum())} {g[g.all_ok].ret.mean() * 100:+.1f}%")
        print(f"R| {sysk} by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:10]), flush=True)


if __name__ == "__main__":
    main()
