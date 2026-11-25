"""Pulse as the industry filter on the live breakout entries (25 Nov 2026, Amritpal: "Will this impact pulse rating priority" -> "Yes"
to testing the app's own Pulse in place of 3-month industry return, so what Today shows and what gets bought use one measure).
Entries = the live rules (ath_confirm_test: Cup 9/21 wick close B, Momentum close confirm C). NSE 2007-26, 0.4% cost.
Groups = the Pulse groups (basic_industry + group_pulse.NSE_SPLIT), liquid members only (60-day median traded >= Rs 2 cr, price >= 50),
>= 3 liquid members. Pulse(stock, day) = trending per tools/group_pulse.py; group Pulse = share of member-days trending over 1 m / 1 q.
All tags taken at the signal day's previous close (point in time). Filters:
  return top 50% (as ath_filter_test, on these groups) | Pulse quarter top 50% | Pulse month top 50% | Pulse quarter top 40% (lane 'strong')
  | lane not Weak / Fading / Bouncing (app lanes) | Pulse quarter top 50% AND return top 50%."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import yfinance as yf  # noqa: E402

SPLIT = {
    "Banks - PSU": ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB", "BANKINDIA", "CENTRALBK", "IOB", "UCOBANK", "MAHABANK", "PSB", "IDBI"],
    "Banks - Private Large": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Banks - Small Finance & Payments": ["AUBANK", "EQUITASBNK", "UJJIVANSFB", "SURYODAY", "UTKARSHBNK", "ESAFSFB", "CAPITALSFB", "JSFB", "FINOPB"],
    "Auto - 2W/3W/EV": ["HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT", "TVSMOTOR", "TVSHLTD", "OLAELEC", "ATHERENERG", "ATULAUTO", "MERCURYEV"],
    "Auto - PV & Tractors": ["MARUTI", "M&M", "TMPV", "HYUNDAI", "ESCORTS", "VSTTILLERS"],
    "Auto - CV & Buses": ["TMCV", "ASHOKLEY", "SMLMAH", "FORCEMOT", "OLECTRA"],
    "Dairy": ["HATSUN", "DODLA", "PARAGMILK", "HERITGFOOD", "MILKYMIST", "MLKFOOD", "UMANGDAIRY", "VADILALIND"],
}


def main():
    nif = yf.download("^NSEI", start="2000-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index()
    V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    B = nif.reindex(C.index).ffill()
    liq = ((C * V).rolling(60, min_periods=40).median() >= 2e7) & (C >= 50)
    rpi = lambda k: 100 * (C / C.shift(k)).div(B / B.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = ((w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52) & liq).astype(float)
    S1w, S1m, S1q = (tr.rolling(n).mean() for n in (5, 21, 63))
    R63 = C / C.shift(63) - 1
    u = pd.read_csv("data/universe/nse_industry.csv")
    grp = dict(zip(u.symbol, u.basic_industry))
    for g, L in SPLIT.items():
        for s in L:
            grp[s] = g
    groups = {}
    for s in C.columns:
        if isinstance(grp.get(s), str):
            groups.setdefault(grp[s], []).append(s)
    groups = {g: L for g, L in groups.items() if len(L) >= 3}
    def gmean(X):   # group mean over liquid members, NaN when < 3 liquid
        out = {}
        for g, L in groups.items():
            m = X[L].where(liq[L]); out[g] = m.mean(axis=1).where(liq[L].sum(axis=1) >= 3)
        return pd.DataFrame(out)
    GQ, GM, GW, GR = gmean(S1q), gmean(S1m), gmean(S1w), gmean(R63)
    pct = lambda G: G.rank(axis=1, pct=True) * 100  # noqa: E731
    PQ, PM, PR = pct(GQ), pct(GM), pct(GR)
    print(f"R| {len(P)} stocks, {len(groups)} Pulse groups", flush=True)
    T = []
    for s, x in P.items():
        try:
            T += AC.trades_for(s, x, reg)
        except Exception as e:  # noqa: BLE001
            print("err", s, e)
    T = pd.DataFrame(T); T = T[(T.d >= "2007-01-01") & (((T.sys == "tf") & (T.v == "B")) | ((T.sys == "mom") & (T.v == "C")))].copy()
    idx = C.index
    def at(df, d, g):
        i = idx.searchsorted(d) - 1
        return df[g].iloc[i] if i >= 0 and g in df.columns else np.nan
    T["g"] = [grp.get(s) if grp.get(s) in groups else None for s in T.sym]
    for k, df in (("pq", PQ), ("pm", PM), ("pr", PR), ("q", GQ), ("m", GM), ("wk", GW)):
        T[k] = [at(df, d, g) if g else np.nan for d, g in zip(T.d, T.g)]
    up = (T.wk > T.m) & (T.m > T.q) & ((T.wk - T.q) * 100 >= 10); dn = (T.wk < T.m) & (T.m < T.q) & ((T.q - T.wk) * 100 >= 10)
    T["lane"] = np.where(T.pq >= 60, np.where(up, "build", np.where(dn, "fade", "hold")), np.where(T.pq <= 40, np.where(up, "bounce", "weak"), "mid"))
    T.loc[T.pq.isna(), "lane"] = "none"
    print(f"R| signals with a Pulse group: {T.g.notna().mean() * 100:.0f}%; agreement Pulse-q top half vs return top half: "
          f"{((T.pq >= 50) == (T.pr >= 50))[T.pq.notna() & T.pr.notna()].mean() * 100:.0f}%", flush=True)
    F = {"all (live rules)": T.index == T.index,
         "return top 50% (3-month price)": T.pr >= 50,
         "PULSE quarter top 50%": T.pq >= 50,
         "PULSE month top 50%": T.pm >= 50,
         "PULSE quarter bottom 50%": T.pq < 50,
         "PULSE quarter top 40% (lane strong)": T.pq >= 60,
         "lane not Weak/Fading/Bouncing": ~T.lane.isin(["weak", "fade", "bounce"]),
         "PULSE quarter top 50% + return top 50%": (T.pq >= 50) & (T.pr >= 50)}
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 20:
                print(f"R| {nm:42s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; cg, dd = AC.port(X)
            print(f"R| {nm:42s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2021-26 {xb.ret.mean() * 100:+6.2f}% (n {len(xb)})"
                  f" | bull {X[X.bull].ret.mean() * 100:+.2f}% bear {X[~X.bull].ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        X = T[T.sys == sysk]
        print("R| by lane: " + " | ".join(f"{k} n {len(g)} {g.ret.mean() * 100:+.1f}%" for k, g in X.groupby("lane")), flush=True)
        y = X.groupby(X.d.dt.year).apply(lambda g: f"all {g.ret.mean() * 100:+.1f}% / pulseQ50 {g[g.pq >= 50].ret.mean() * 100:+.1f}% / ret50 {g[g.pr >= 50].ret.mean() * 100:+.1f}%")
        print("R| by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:8]), flush=True)


if __name__ == "__main__":
    main()
