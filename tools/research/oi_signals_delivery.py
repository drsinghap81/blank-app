"""Option / futures open-interest signals -> stock delivery (18 Nov 2026, Amritpal: "yes check").

Same data as opt_signal_delivery.py (optatm-* branches: CE and PE strikes within +-10% of the near future, nearest 3 expiries,
futures rows; PE 2022 missing, so PCR / skew skip 2022). Current F&O list 2020 - Oct 2026; stock prices Yahoo (adjusted).
Per stock and day (all measured at the close, trade = buy the stock at the next open, sell 5 / 10 / 20 days later):
  build-up (futures, OI summed over all expiries so rolls cancel):
     long build-up   close +1% or more and futures OI +5% or more     (bullish in the textbook reading)
     short covering  close +1% or more and OI -5% or more
     short build-up  close -1% or more and OI +5% or more             (bearish)
     long unwinding  close -1% or more and OI -5% or more
  PCR      = put OI / call OI, near monthly expiry, strikes within +-10%: quintiles of its level and of its 5-day change
  skew     = (put 5% below the future) / (call 5% above the future), near monthly, as a ratio of premiums: quintiles
Each bucket vs every stock-day (control) and vs the other quintiles; t-statistic of the mean; yearly averages for the extremes.
Output: data/research/oi_signals_delivery.json"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from opt_signal_delivery import load  # noqa: E402

H = (5, 10, 20)


def main():
    X = load(); print("rows", len(X), flush=True)
    X["PX"] = np.where(X.VOL > 0, X.CLOSE, X.SETTLE)
    FU = X[X.INST == "FUT"].drop_duplicates(["SYMBOL", "Date", "EXPIRY"])
    near = FU.sort_values("EXPIRY").groupby(["SYMBOL", "Date"]).agg(F=("CLOSE", "first"), E=("EXPIRY", "first"))
    foi = FU.groupby(["SYMBOL", "Date"]).OI.sum().rename("FOI")
    D = near.join(foi).reset_index().sort_values(["SYMBOL", "Date"])
    OP = X[X.INST == "OPT"].drop_duplicates(["SYMBOL", "Date", "EXPIRY", "STRIKE", "TYPE"])
    # near MONTHLY option expiry with >= 3 days left
    OP = OP.merge(D[["SYMBOL", "Date", "F"]], on=["SYMBOL", "Date"])
    ex = OP[(OP.EXPIRY - OP.Date).dt.days >= 3].groupby(["SYMBOL", "Date"]).EXPIRY.min().rename("NE")
    OP = OP.merge(ex, on=["SYMBOL", "Date"]); OP = OP[OP.EXPIRY == OP.NE]
    oi = OP.pivot_table(index=["SYMBOL", "Date"], columns="TYPE", values="OI", aggfunc="sum")
    oi["PCR"] = oi.get("PE") / oi.get("CE")
    # skew: premium of the put nearest F*0.95 over the call nearest F*1.05
    def pick(g, typ, tgt):
        g = g[g.TYPE == typ]
        if g.empty:
            return np.nan
        i = (g.STRIKE - tgt).abs().idxmin()
        return g.loc[i, "PX"] if abs(g.loc[i, "STRIKE"] / tgt - 1) < 0.02 else np.nan
    sk = OP.groupby(["SYMBOL", "Date"]).apply(lambda g: pick(g, "PE", g.F.iloc[0] * 0.95) / pick(g, "CE", g.F.iloc[0] * 1.05)).rename("SKEW")
    D = D.set_index(["SYMBOL", "Date"]).join(oi[["PCR"]]).join(sk).reset_index()
    syms = sorted(D.SYMBOL.unique())
    P = yf.download([s + ".NS" for s in syms], start="2019-10-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    rows = []
    for sym, g in D.groupby("SYMBOL"):
        try:
            px = P[sym + ".NS"][["Open", "Close"]].dropna()
        except Exception:  # noqa: BLE001
            continue
        g = g.set_index("Date").sort_index()
        g["ret1"] = g.F.pct_change() * 100; g["doi"] = g.FOI.pct_change() * 100
        g["dpcr5"] = g.PCR - g.PCR.shift(5)
        idx = px.index; po, pc = px.Open.values, px.Close.values
        ma200 = px.Close.rolling(200).mean().values
        for d, r in g.iterrows():
            if d not in idx:
                continue
            j = idx.get_loc(d)
            fw = {f"r{h}": (pc[j + h] / po[j + 1] - 1) * 100 if j + h < len(idx) else np.nan for h in H}
            rows.append(dict(sym=sym, d=d, ret1=r.ret1, doi=r.doi, pcr=r.PCR, dpcr5=r.dpcr5, skew=r.SKEW,
                             p5=(pc[j] / pc[j - 5] - 1) * 100 if j >= 5 else np.nan, up=bool(j >= 200 and pc[j] > ma200[j]), **fw))
        print(sym, len(rows), flush=True)
    E = pd.DataFrame(rows); E = E[E.d >= "2020-02-01"]

    def summ(Z):
        out = {}
        for h in H:
            r = Z[f"r{h}"].dropna()
            if len(r) < 30:
                continue
            out[f"{h}d"] = dict(n=len(r), avg=round(r.mean(), 2), win=round((r > 0).mean() * 100, 1), t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2))
        return out
    res = dict(method=__doc__, control=summ(E))
    B = {"long build-up": (E.ret1 >= 1) & (E.doi >= 5), "short covering": (E.ret1 >= 1) & (E.doi <= -5),
         "short build-up": (E.ret1 <= -1) & (E.doi >= 5), "long unwinding": (E.ret1 <= -1) & (E.doi <= -5)}
    for k, m in B.items():
        Z = E[m]; res[k] = summ(Z); res[k + " by year (10d avg)"] = Z.groupby(Z.d.dt.year).r10.mean().round(2).to_dict()
    for col in ("pcr", "dpcr5", "skew"):
        Z = E[(E[col].notna()) & np.isfinite(E[col]) & (E.d.dt.year != 2022)].copy()
        Z["q"] = Z.groupby(Z.d.dt.to_period("M"))[col].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if len(s) >= 25 else np.nan)
        res[col] = {f"Q{int(q)} (low->high)": summ(Z[Z.q == q]) for q in sorted(Z.q.dropna().unique())}
        res[col + " Q5-Q1 10d by year"] = (Z[Z.q == 5].groupby(Z.d.dt.year).r10.mean() - Z[Z.q == 1].groupby(Z.d.dt.year).r10.mean()).round(2).to_dict()
    # 18 Nov 2026 follow-up: is high PCR just short-term reversal (stocks that just fell)? and does it hold in uptrends?
    Z = E[(E.pcr.notna()) & np.isfinite(E.pcr) & (E.d.dt.year != 2022)].copy()
    Z["q"] = Z.groupby(Z.d.dt.to_period("M")).pcr.transform(lambda s_: pd.qcut(s_.rank(method="first"), 5, labels=False) + 1 if len(s_) >= 25 else np.nan)
    Z["p5q"] = Z.groupby(Z.d.dt.to_period("M")).p5.transform(lambda s_: pd.qcut(s_.rank(method="first"), 3, labels=False) + 1 if s_.notna().sum() >= 25 else np.nan)
    res["pcr x prior 5-day return (tercile 1 = fell most)"] = {f"p5 T{int(t)} | PCR Q{q}": summ(Z[(Z.p5q == t) & (Z.q == q)]) for t in (1, 2, 3) for q in (1, 5)}
    res["pcr x trend (close vs 200-day)"] = {f"{'above' if u else 'below'} 200d | PCR Q{q}": summ(Z[(Z.up == u) & (Z.q == q)]) for u in (True, False) for q in (1, 5)}
    # tradable version: every Friday buy the 10 highest-PCR stocks (equal weight), hold 10 trading days (2 overlapping books)
    W = Z[Z.d.dt.weekday == 4]; port = []
    for d, g in W.groupby("d"):
        top = g.nlargest(10, "pcr"); allg = g
        port.append(dict(d=d, top=top.r10.mean() - 0.25, all=allg.r10.mean() - 0.25))
    Pt = pd.DataFrame(port).dropna().set_index("d")
    def curve(r):                                   # two overlapping 2-week books, each half the money
        eq = (1 + r / 100 / 2).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        return dict(cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round(((eq / eq.cummax()) - 1).min() * 100, 1),
                    by_year={int(y): round((v.add(1).prod() - 1) * 100, 1) for y, v in (r / 100 / 2).groupby(r.index.year)})
    res["portfolio: top-10 PCR each Friday, 10 days, 0.25% cost"] = curve(Pt.top)
    res["portfolio: all F&O stocks each Friday, same rules"] = curve(Pt["all"])
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/oi_signals_delivery.json", "w"), indent=1, default=str)
    for k, v in res.items():
        if k != "method":
            print(k, v, flush=True)


if __name__ == "__main__":
    main()
