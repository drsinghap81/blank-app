"""AustralianSuper DIY Mix switching (27 Nov 2026, Amritpal: "how can I effectively manage super with our strategies" + his fund's notice).
DIY Mix options and stand-ins (Yahoo, adjusted closes, AUD):
  Australian Shares        -> STW.AX (ASX 200, 2001+)            fee 0.15%
  International Shares     -> IVV.AX (S&P 500 in AUD, 2007+)     fee 0.39%   (AustralianSuper's option is wider than the S&P 500)
  Diversified Fixed Int.   -> IAF.AX (AU composite bonds, 2012+) fee 0.37%
  Cash                     -> 3.0% a year flat                     fee 0.05%
Fees = the option's investment + transaction costs from the notice, taken monthly. Super's 15% tax on earnings is ignored (same for
every rule). Switching delay: the decision is made on the month-end close and earns from the NEXT month (a switch takes 1-3 days).
Rules (monthly):
  hold each option; 50/50 Aus/Intl rebalanced; High-Growth-like 35/50/10/5
  TREND: hold Aus + Intl 50/50; each half goes to cash while its option closed the month below its 10-month average
  ROTATION: best 2 of the 4 by 3-month return (cash if below cash); also best 1
Newest windows first, plus calendar years and the number of switches a year."""
import numpy as np
import pandas as pd
import yfinance as yf

FEES = {"AUS": 0.0015, "INTL": 0.0039, "FI": 0.0037, "CASH": 0.0005}
CASH_RATE = 0.03


def monthly():
    T = {"AUS": "STW.AX", "INTL": "IVV.AX", "FI": "IAF.AX"}
    d = yf.download(list(T.values()), start="2006-01-01", auto_adjust=True, progress=False)["Close"]
    d.index = pd.to_datetime(d.index).tz_localize(None)
    m = d.resample("ME").last().rename(columns={v: k for k, v in T.items()})
    r = m.pct_change()
    r["CASH"] = (1 + CASH_RATE) ** (1 / 12) - 1
    for k, f in FEES.items():
        r[k] = r[k] - f / 12
    return m, r


def book(W, R):
    """W: target weights decided at month-end t (rows), earning month t+1."""
    W = W.reindex(R.index).ffill().fillna(0.0)
    ret = (W.shift(1) * R).sum(axis=1, min_count=1)
    sw = (W.diff().abs().sum(axis=1) > 1e-9).sum()
    return ret.dropna(), sw


def stats(ret, sw_total, start):
    x = ret[ret.index >= start]
    if len(x) < 12:
        return None
    eq = (1 + x).cumprod(); yrs = len(x) / 12
    dd = (eq / eq.cummax() - 1).min()
    w = lambda y: ((1 + x.iloc[-12 * y:]).prod() - 1) * 100 if len(x) >= 12 * y else np.nan  # noqa: E731
    return dict(cagr=(eq.iloc[-1] ** (1 / yrs) - 1) * 100, dd=dd * 100, y1=w(1), y3=w(3), y5=w(5), worst_m=x.min() * 100)


def main():
    m, R = monthly()
    R = R.dropna(subset=["AUS", "INTL"])
    idx = R.index
    rules = {}
    for k in ("AUS", "INTL", "FI", "CASH"):
        rules[f"hold {k}"] = pd.DataFrame({k: 1.0}, index=idx)
    rules["50/50 Aus/Intl"] = pd.DataFrame({"AUS": 0.5, "INTL": 0.5}, index=idx)
    rules["High-Growth-like 35/50/10/5"] = pd.DataFrame({"AUS": 0.35, "INTL": 0.5, "FI": 0.10, "CASH": 0.05}, index=idx)
    sma = m[["AUS", "INTL"]].rolling(10).mean().reindex(idx)
    up = (m[["AUS", "INTL"]].reindex(idx) > sma)
    W = pd.DataFrame(0.0, index=idx, columns=["AUS", "INTL", "FI", "CASH"])
    W["AUS"] = up["AUS"] * 0.5; W["INTL"] = up["INTL"] * 0.5; W["CASH"] = 1 - W.AUS - W.INTL
    rules["TREND 10-month (each half to cash below its average)"] = W
    W2 = W.copy(); W2["FI"] = W2["CASH"]; W2["CASH"] = 0.0
    rules["TREND 10-month (to fixed interest instead of cash)"] = W2
    r3 = (1 + R[["AUS", "INTL", "FI", "CASH"]]).rolling(3).apply(np.prod, raw=True) - 1
    for top in (1, 2):
        Wr = pd.DataFrame(0.0, index=idx, columns=["AUS", "INTL", "FI", "CASH"])
        for t in idx:
            row = r3.loc[t].dropna()
            if row.empty:
                Wr.loc[t, "CASH"] = 1.0; continue
            cash = row.get("CASH", 0)
            pick = row.sort_values(ascending=False).index[:top]
            for p in pick:
                Wr.loc[t, p if row[p] >= cash else "CASH"] += 1.0 / top
        rules[f"ROTATION best {top} by 3-month return"] = Wr
    print(f"R| data {idx[0].date()} -> {idx[-1].date()} (FI from {R['FI'].first_valid_index().date()})", flush=True)
    for nm, W in rules.items():
        ret, sw = book(W, R.fillna(0.0))
        yrs = len(ret) / 12
        for lab, st in (("since 2008", "2008-01-01"), ("since 2016", "2016-01-01"), ("since 2021", "2021-01-01")):
            S = stats(ret, sw, st)
            if S:
                print(f"R| {nm:52s} {lab:10s} | {S['cagr']:+5.1f}%/yr worst fall {S['dd']:6.1f}% worst month {S['worst_m']:+5.1f}% | "
                      f"1y {S['y1']:+5.1f} 3y {S['y3']:+6.1f} 5y {S['y5']:+6.1f} | switches/yr {sw / yrs:.1f}", flush=True)
        yy = ret.groupby(ret.index.year).apply(lambda x: ((1 + x).prod() - 1) * 100)
        print(f"R|   years {nm[:30]}: " + " ".join(f"{y}:{v:+.0f}" for y, v in yy.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
