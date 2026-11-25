"""Size and sector-strength filters on the live breakout entries (25 Nov 2026, Amritpal: "shortlist should happen as per sector
strength, yes test it" - after large caps led for 3 months while mid/small caps lagged and the book, mostly mid/small breakouts,
stood still).
Entries = the live rules (tools/research/ath_confirm_test.py): Cup 9/21 = daily close above the wick high, Momentum = daily close
above the ATH-month high, then next session above that candle's high + 0.15%. Exits as live. NSE, Yahoo daily, 2007-26, 0.4% cost.
Point-in-time tags at each signal (no today's lists):
  size     : rank by 60-day average traded value among all loaded stocks that day - LARGE = top 100, MID = 101-250, SMALL = rest
  regime   : 'large leads' when the equal-weight 63-day return of the top-100 beats that of ranks 101-250 (the Midcap 150 picture)
  industry : the stock's industry (data/universe/nse_industry.csv), equal-weight 63-day return of its members, ranked across
             industries with >= 3 stocks -> percentile (100 = strongest)
Filters: all | large only | regime (large-only while large leads, else all) | industry top 50% / top 30% | regime + industry top 50%
| size-matched (large while large leads, mid+small while they lead)."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import ath_confirm_test as AC  # noqa: E402
import yfinance as yf  # noqa: E402


def main():
    nif = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index()
    V = pd.DataFrame({s: (x.C * x.V) for s, x in P.items()}).reindex(C.index).rolling(60, min_periods=40).mean()
    R63 = C / C.shift(63) - 1
    rank = V.rank(axis=1, ascending=False)
    big = rank <= 100; mid = (rank > 100) & (rank <= 250)
    lead = (R63.where(big).mean(axis=1) - R63.where(mid).mean(axis=1)) > 0          # large caps lead
    ind = pd.read_csv("data/universe/nse_industry.csv").set_index("symbol")["industry"].to_dict()
    groups = {}
    for s in C.columns:
        if isinstance(ind.get(s), str):
            groups.setdefault(ind[s], []).append(s)
    groups = {g: L for g, L in groups.items() if len(L) >= 3}
    GR = pd.DataFrame({g: R63[L].mean(axis=1) for g, L in groups.items()})
    GP = GR.rank(axis=1, pct=True) * 100
    print(f"R| {len(P)} stocks, {len(groups)} industries; large caps led on {lead.mean() * 100:.0f}% of days since 2007", flush=True)
    T = []
    for s, x in P.items():
        try:
            T += AC.trades_for(s, x, reg)
        except Exception as e:  # noqa: BLE001
            print("err", s, e)
    T = pd.DataFrame(T); T = T[(T.d >= "2007-01-01") & (((T.sys == "tf") & (T.v == "B")) | ((T.sys == "mom") & (T.v == "C")))].copy()
    def at(df, d, s):
        try:
            i = df.index.searchsorted(d) - 1
            return df.iloc[i][s] if i >= 0 and s in df.columns else np.nan
        except Exception:  # noqa: BLE001
            return np.nan
    T["rk"] = [at(rank, d, s) for d, s in zip(T.d, T.sym)]
    T["lead"] = [bool(lead.iloc[max(lead.index.searchsorted(d) - 1, 0)]) for d in T.d]
    T["ip"] = [at(GP, d, ind.get(s)) if ind.get(s) in groups else np.nan for d, s in zip(T.d, T.sym)]
    T["size"] = np.where(T.rk <= 100, "large", np.where(T.rk <= 250, "mid", "small"))
    F = {"all (live rules)": T.index == T.index,
         "large caps only": T["size"] == "large",
         "mid + small only": T["size"] != "large",
         "regime: large only while large leads": (~T["lead"]) | (T["size"] == "large"),
         "size-matched: large while large leads, mid/small while they lead": (T["lead"] & (T["size"] == "large")) | (~T["lead"] & (T["size"] != "large")),
         "industry top 50%": T.ip >= 50,
         "industry top 30%": T.ip >= 70,
         "industry bottom 50%": T.ip < 50,
         "regime + industry top 50%": ((~T["lead"]) | (T["size"] == "large")) & (T.ip >= 50)}
    for sysk, lab in (("tf", "CUP 9/21 (wick close)"), ("mom", "MOMENTUM (close confirm)")):
        print(f"R| ===== {lab} =====", flush=True)
        for nm, m in F.items():
            X = T[(T.sys == sysk) & m]
            if len(X) < 20:
                print(f"R| {nm:62s} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; xc = X[~X.d.between(*AC.COVID)]; cg, dd = AC.port(X)
            print(f"R| {nm:62s} n {len(X):4d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | 2021-26 {xb.ret.mean() * 100:+6.2f}% (n {len(xb)})"
                  f" | bull {X[X.bull].ret.mean() * 100:+.2f}% bear {X[~X.bull].ret.mean() * 100:+.2f}% | ex-Covid {xc.ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
        for sz in ("large", "mid", "small"):
            for ld in (True, False):
                X = T[(T.sys == sysk) & (T["size"] == sz) & (T["lead"] == ld)]
                if len(X) >= 10:
                    print(f"R| cell {sz:5s} while {'large leads' if ld else 'mid/small lead'}: n {len(X)} avg {X.ret.mean() * 100:+.2f}% win {(X.ret > 0).mean() * 100:.0f}%", flush=True)
        X = T[(T.sys == sysk)]
        y = X.groupby(X.d.dt.year).apply(lambda g: f"{len(g)} all {g.ret.mean() * 100:+.1f}% / regime {g[(~g['lead']) | (g['size'] == 'large')].ret.mean() * 100:+.1f}% / ind50 {g[g.ip >= 50].ret.mean() * 100:+.1f}%")
        print(f"R| {sysk} by year (newest first): " + " | ".join(f"{k}: {v}" for k, v in sorted(y.items(), reverse=True)[:10]), flush=True)


if __name__ == "__main__":
    main()
