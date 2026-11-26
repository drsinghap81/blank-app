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
    E9 = {k: H[k].ewm(span=9, adjust=False).mean() > H[k].ewm(span=21, adjust=False).mean() for k in H.columns}   # 26 Nov: 9/21 only
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
    # 26 Nov 2026 (Amritpal: "apply these 4 rules, or at least 2, 3, 4, to all levels of top down"): the stock itself on the 4 Pulse
    # rules, and the industry as an equal-weight index of its liquid members on rules 2-4 (and rule 1 vs the Nifty 500)
    n5 = n500.reindex(C.index).ffill()
    rpi = lambda X, k: 100 * (X / X.shift(k)).div(n5 / n5.shift(k), axis=0)      # noqa: E731
    W_ = (rpi(C, 10) + rpi(C, 63) + rpi(C, 126)) / 3
    e9_, e21_, s150_ = C.ewm(span=9, adjust=False).mean(), C.ewm(span=21, adjust=False).mean(), C.rolling(150).mean()
    s234 = (e9_ > e21_) & (C > s150_) & (s150_ > s150_.shift(20)) & (C >= 0.75 * C.rolling(250, min_periods=120).max())
    S4 = s234 & (W_ > 100)
    R1d = (C / C.shift(1) - 1).clip(-0.2, 0.2)
    liq = (C * Vv).rolling(60, min_periods=40).median() >= 2e7
    IXI = pd.DataFrame({g: (1 + R1d[m].where(liq[m].shift(1, fill_value=False)).median(axis=1).fillna(0)).cumprod() for g, m in IND.items()})
    I234 = {}; I4 = {}
    for g in IXI.columns:
        a_, _ = trend(IXI[g]); I234[g] = a_
        I4[g] = a_ & ((IXI[g] / IXI[g].shift(63)) > (n5 / n5.shift(63)))
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
    T["e_mkt"] = [on(E9, "NIFTY 500", d) for d in T.d]
    T["e_size"] = [on(E9, SZ[z], d) for z, d in zip(T["size"], T.d)]
    T["e_sec"] = [on(E9, sec_of[s], d) if h else None for s, d, h in zip(T.sym, T.d, T.has_sec)]
    T["e_th"] = [any(on(E9, t, d) for t in th_of[s]) if h else None for s, d, h in zip(T.sym, T.d, T.has_th)]
    IE9 = {g: IXI[g].ewm(span=9, adjust=False).mean() > IXI[g].ewm(span=21, adjust=False).mean() for g in IXI.columns}
    T["e_ind"] = [bool(prev(IE9[ind_of[s]], d)) if ind_of.get(s) in IE9 else None for d, s in zip(T.d, T.sym)]
    T["e_stk"] = [bool(prev((e9_ > e21_)[s], d)) if s in C.columns else False for d, s in zip(T.d, T.sym)]
    T["stk4"] = [bool(prev(S4[s], d)) if s in S4.columns else False for d, s in zip(T.d, T.sym)]
    T["stk234"] = [bool(prev(s234[s], d)) if s in s234.columns else False for d, s in zip(T.d, T.sym)]
    T["ind234"] = [bool(prev(I234[ind_of[s]], d)) if ind_of.get(s) in I234 else None for d, s in zip(T.d, T.sym)]
    T["ind4"] = [bool(prev(I4[ind_of[s]], d)) if ind_of.get(s) in I4 else None for d, s in zip(T.d, T.sym)]
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
         "stock passes all 4 rules": T.stk4,
         "stock passes rules 2-4": T.stk234,
         "industry index rules 2-4": yes("ind234"),
         "industry index all 4 rules": yes("ind4"),
         "CHAIN 2-4: market+size+sector+industry+theme+stock": yes("mkt") & yes("size_tr") & yes("sec_tr") & yes("ind234") & yes("th_tr") & T.stk234,
         "CHAIN 1-4 (beat market at size/sector/industry/stock)": yes("mkt") & yes("size_rs") & yes("sec_rs") & yes("ind4") & yes("th_tr") & T.stk4,
         "CHAIN 2-4 + lane": lane_ok & yes("mkt") & yes("size_tr") & yes("sec_tr") & yes("ind234") & yes("th_tr") & T.stk234,
         "9/21 market": yes("e_mkt"),
         "9/21 size index": yes("e_size"),
         "9/21 sector": yes("e_sec"),
         "9/21 industry index": yes("e_ind"),
         "9/21 theme": yes("e_th"),
         "9/21 stock": T.e_stk,
         "9/21 at every level": yes("e_mkt") & yes("e_size") & yes("e_sec") & yes("e_ind") & yes("e_th") & T.e_stk,
         "lane + 9/21 market + size": lane_ok & yes("e_mkt") & yes("e_size"),
         "lane + 9/21 every level": lane_ok & yes("e_mkt") & yes("e_size") & yes("e_sec") & yes("e_ind") & yes("e_th") & T.e_stk,
         "lane + own size index only (no market check)": lane_ok & yes("size_tr"),
         "lane + own size index Stage 2 only": lane_ok & yes("size_s2"),
         "lane + market + size + stock 4 rules": lane_ok & yes("mkt") & yes("size_tr") & T.stk4,
         "skipped by ALL (lane OK but some index not trending)": lane_ok & ~(yes("mkt") & yes("size_tr") & yes("sec_tr") & yes("th_tr"))}
    T["all_ok"] = F["ALL: lane + market + size + sector + theme"]
    # 26 Nov 2026 (Amritpal: "I will rotate when the 9/21 signal goes away"): exit early when a top-down level's EMA 9 closes below
    # EMA 21 - sold at the next day's close (stand-in for the next open), or the system's own exit if that comes first.
    # New return = old return scaled by close(new exit) / close(old exit day) (exit prices approximated by closes).
    Cn = C.ffill()

    def early(row, series):
        if series is None:
            return row.dx, row.ret
        s_ = series.loc[(series.index > row.d) & (series.index < row.dx)]
        bad = s_[~s_.astype(bool)]
        if not len(bad):
            return row.dx, row.ret
        i = Cn.index.searchsorted(bad.index[0]) + 1
        if i >= len(Cn.index) or Cn.index[i] >= row.dx or row.sym not in Cn.columns:
            return row.dx, row.ret
        dn = Cn.index[i]; c0 = Cn.at[row.dx, row.sym] if row.dx in Cn.index else np.nan; c1 = Cn.at[dn, row.sym]
        if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0):
            return row.dx, row.ret
        return dn, (1 + row.ret + AC.COST) * c1 / c0 - 1 - AC.COST

    def any_down(row):
        ks = [E9["NIFTY 500"], E9[SZ[row.size]]] + ([E9[sec_of[row.sym]]] if row.has_sec else []) + ([IE9[ind_of[row.sym]]] if ind_of.get(row.sym) in IE9 else [])
        return pd.concat(ks, axis=1).reindex(Cn.index).ffill().fillna(True).astype(bool).all(axis=1)
    ESER = {"size index 9/21 down": lambda r: E9[SZ[r.size]].reindex(Cn.index).ffill(),
            "sector 9/21 down": lambda r: E9[sec_of[r.sym]].reindex(Cn.index).ffill() if r.has_sec else None,
            "industry 9/21 down": lambda r: IE9[ind_of[r.sym]] if ind_of.get(r.sym) in IE9 else None,
            "market 9/21 down": lambda r: E9["NIFTY 500"].reindex(Cn.index).ffill(),
            "any level 9/21 down": any_down}
    # 26 Nov 2026 (Amritpal: "cup breakout in ICICIBANK - enter on the breakout candle high if Bank Nifty / Pvt Bank index is 9/21
    # trending, exit when it's not"): the stock's own NARROW index - a real NSE index where one matches the basic industry, else the
    # sector index - as BOTH the entry gate and the exit
    NARROW = {"Private Sector Bank": "NIFTY PRIVATE BANK", "Public Sector Bank": "NIFTY PSU BANK", "Pharmaceuticals": "NIFTY PHARMA",
              "Computers - Software & Consulting": "NIFTY IT", "Iron & Steel": "NIFTY METAL", "Diversified Metals": "NIFTY METAL",
              "Cement & Cement Products": "NIFTY COMMODITIES", "Diversified FMCG": "NIFTY FMCG", "Residential, Commercial Projects": "NIFTY REALTY",
              "Passenger Cars & Utility Vehicles": "NIFTY AUTO", "Auto Components & Equipments": "NIFTY AUTO", "2/3 Wheelers": "NIFTY AUTO",
              "Depositories Clearing Houses and Other Intermediaries": "NIFTY CAPITAL MARKETS", "Stockbroking & Allied": "NIFTY CAPITAL MARKETS",
              "Aerospace & Defense": "NIFTY INDIA DEFENCE", "Oil Exploration & Production": "NIFTY OIL & GAS", "Refineries & Marketing": "NIFTY OIL & GAS"}
    nar_of = {s_: (NARROW.get(ind_of.get(s_)) if NARROW.get(ind_of.get(s_)) in H.columns else sec_of.get(s_) if sec_of.get(s_) in H.columns else None) for s_ in T.sym.unique()}
    T["e_nar"] = [on(E9, nar_of[s_], d) if nar_of.get(s_) else None for s_, d in zip(T.sym, T.d)]
    nar_x = lambda r: E9[nar_of[r.sym]].reindex(Cn.index).ffill() if nar_of.get(r.sym) else None          # noqa: E731
    sec_x = lambda r: E9[sec_of[r.sym]].reindex(Cn.index).ffill() if r.has_sec else None                   # noqa: E731
    ind_x = lambda r: IE9[ind_of[r.sym]] if ind_of.get(r.sym) in IE9 else None                            # noqa: E731
    PAIRS = [("9/21 narrow index (in & out)", yes("e_nar"), nar_x), ("lane + 9/21 narrow index (in & out)", lane_ok & yes("e_nar"), nar_x),
             ("9/21 sector index (in & out)", yes("e_sec"), sec_x), ("lane + 9/21 sector (in & out)", lane_ok & yes("e_sec"), sec_x),
             ("lane + 9/21 industry index (in & out)", lane_ok & yes("e_ind"), ind_x),
             ("lane + 9/21 narrow in, own exit", lane_ok & yes("e_nar"), lambda r: None)]
    for sysk, lab in (("tf", "CUP 9/21"), ("mom", "MOMENTUM")):
        for en, m, fn in PAIRS:
            Y = T[(T.sys == sysk) & m].copy()
            if len(Y) < 20:
                continue
            nd = [early(r, fn(r)) for r in Y.itertuples()]
            Y["dx"] = [z[0] for z in nd]; Y["ret"] = [z[1] for z in nd]
            cg, dd = AC.port(Y); xr = Y[Y.d >= "2024-01-01"]; xb = Y[Y.d >= "2021-07-01"]
            print(f"R| SECTOR-RULE {lab:8s} {en:38s} n {len(Y):4d} | win {(Y.ret > 0).mean() * 100:3.0f}% | avg {Y.ret.mean() * 100:+6.2f}% | hold {((Y.dx - Y.d).dt.days).mean():4.0f}d | 2024+ {xr.ret.mean() * 100:+6.2f}% | Jul21+ {xb.ret.mean() * 100:+6.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
    for sysk, lab in (("tf", "CUP 9/21"), ("mom", "MOMENTUM")):
        for en, m in (("lane (live)", lane_ok), ("lane + 9/21 every level", lane_ok & yes("e_mkt") & yes("e_size") & yes("e_sec") & yes("e_ind") & yes("e_th") & T.e_stk)):
            base = T[(T.sys == sysk) & m]
            for xn, fn in ESER.items():
                if len(base) < 20:
                    continue
                Y = base.copy(); nd = [early(r, fn(r)) for r in Y.itertuples()]
                Y["dx"] = [z[0] for z in nd]; Y["ret"] = [z[1] for z in nd]
                cg, dd = AC.port(Y); xr = Y[Y.d >= "2024-01-01"]
                print(f"R| ROTATE {lab:8s} entry {en:24s} exit {xn:22s} n {len(Y):4d} | avg {Y.ret.mean() * 100:+6.2f}% | hold {((Y.dx - Y.d).dt.days).mean():4.0f}d | 2024+ {xr.ret.mean() * 100:+6.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 20:
                print(f"R| {nm:52s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; xr = X[X.d >= "2024-01-01"]; xc = X[~X.d.between(*AC.COVID)]; cg, dd = AC.port(X)
            print(f"R| {nm:52s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {xr.ret.mean() * 100:+6.2f}% (n {len(xr)})"
                  f" | Jul21+ {xb.ret.mean() * 100:+6.2f}% | ex-Covid {xc.ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        for sz in ("large", "mid", "small"):                     # 26 Nov 2026 (Amritpal: "check as per size")
            for nm, m in (("lane (live)", lane_ok), ("lane + size index", lane_ok & yes("size_tr")), ("lane + market + size", lane_ok & yes("mkt") & yes("size_tr")),
                          ("skipped by size index (lane OK)", lane_ok & ~yes("size_tr"))):
                X = T[(T.sys == sysk) & (T["size"] == sz) & m]
                if len(X) < 15:
                    print(f"R| size {sz:5s} {nm:34s} n {len(X)}", flush=True); continue
                cg, dd = AC.port(X); xr = X[X.d >= "2024-01-01"]
                print(f"R| size {sz:5s} {nm:34s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2024+ {xr.ret.mean() * 100:+6.2f}% (n {len(xr)}) | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        X = T[T.sys == sysk]
        y = X.groupby(X.d.dt.year).apply(lambda g: f"lane {len(g[g.lane.isin(['build', 'hold', 'mid', 'none'])])} {g[~g.lane.isin(['weak', 'fade', 'bounce'])].ret.mean() * 100:+.1f}% / ALL {int(g.all_ok.sum())} {g[g.all_ok].ret.mean() * 100:+.1f}%")
        print(f"R| {sysk} by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:10]), flush=True)


if __name__ == "__main__":
    main()
