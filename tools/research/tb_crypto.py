"""Top Bottom on Bitcoin and Ether (26 Nov 2026, Amritpal: "was top bottom not good for commodities and bitcoins" -> "Yes" to test).
Data: Yahoo BTC-USD (2014-09 on) and ETH-USD (2017-11 on), daily UTC candles, 7 days a week, in US$. Engine
tools/topbottom_backtest.run_live, buffer 0.05%, event exits off, 0.1% cost a round trip (exchange fees + spread). Returns on full
contract value, compounded per trade. Rule sets: INDEX 1/2/2 (Bank Nifty bot), STOCK 1.5/3/3, and CRYPTO 3/6/6 (coins swing ~3x Nifty).
Versions: both sides / buy only / buy only while price > 200-day. Newest windows first; long vs short split; years.
Then an equal-weight monthly book with Bank Nifty futures (both sides) for the diversification question."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

RULES = {"INDEX 1/2/2": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0), "STOCK 1.5/3/3": dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5),
         "CRYPTO 3/6/6": dict(day_sl_pct=3.0, max_sl_pct=6.0, be_pct=6.0, gap_pct=3.0)}
COST = 0.001


def yh(t):
    d = yf.download(t, start="2014-01-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); return x[(x.High >= x.Low) & (x.Low > 0)]


def stats(r, ent, ext, end):
    if not len(r):
        return None
    g, b = r[r > 0].sum(), -r[r < 0].sum(); eq = (1 + r.values).cumprod(); dd = (eq / np.maximum.accumulate(eq) - 1).min()
    yrs = max(0.5, (ext.max() - ent.min()).days / 365.25)
    w = lambda y: (np.prod(1 + r[ext > end - pd.DateOffset(years=y)]) - 1) * 100  # noqa: E731
    return dict(n=len(r), win=(r > 0).mean() * 100, pf=g / b if b else 9, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=dd * 100, y1=w(1), y2=w(2), y3=w(3), y5=w(5))


def main():
    months = {}
    for coin in ("BTC-USD", "ETH-USD"):
        df = yh(coin); end = df.index[-1]; above = (df.Close > df.Close.rolling(200).mean()).to_numpy()
        vol = df.Close.pct_change().std() * np.sqrt(365) * 100
        print(f"R| == {coin} {df.index[0].date()} -> {end.date()} last {df.Close.iloc[-1]:,.0f} | yearly vol {vol:.0f}%", flush=True)
        for rl, kw in RULES.items():
            for lab in ("both sides", "buy only", "buy only >200d"):
                p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=lab != "both sides", **kw)
                t = tbb.run_live(df, p); t = t[~t.Open] if "Open" in t else t
                if lab == "buy only >200d" and len(t):
                    ix = df.index.get_indexer(pd.to_datetime(t.EntryDate)); t = t[[bool(above[max(0, i - 1)]) for i in ix]]
                r = (t.Pct / 100 - COST).reset_index(drop=True); ent, ext = pd.to_datetime(t.EntryDate).reset_index(drop=True), pd.to_datetime(t.ExitDate).reset_index(drop=True)
                S = stats(r, ent, ext, end)
                if S:
                    print(f"R| {coin:7s} {rl:13s} {lab:15s} | n {S['n']:4d} win {S['win']:3.0f}% PF {S['pf']:.2f} | CAGR {S['cagr']:+7.1f}% DD {S['dd']:+6.1f}% | "
                          f"1y {S['y1']:+7.1f} 2y {S['y2']:+7.1f} 3y {S['y3']:+7.1f} 5y {S['y5']:+7.1f}", flush=True)
                if lab == "both sides" and len(t):
                    L = r[(t.Side == "BUY").to_numpy()]; Sh = r[(t.Side == "SELL").to_numpy()]
                    pf = lambda x: x[x > 0].sum() / max(1e-9, -x[x < 0].sum())  # noqa: E731
                    yy = pd.Series(r.values, index=ext).groupby(ext.dt.year.values).apply(lambda x: (np.prod(1 + x) - 1) * 100)
                    print(f"R| {coin:7s} {rl:13s} split | longs PF {pf(L):.2f} ({len(L)}) shorts PF {pf(Sh):.2f} ({len(Sh)}) | years " +
                          " ".join(f"{y}:{v:+.0f}" for y, v in yy[::-1].items()), flush=True)
                if lab in ("both sides", "buy only >200d"):
                    s = pd.Series(r.values, index=ext); months[(coin, rl, lab)] = s.groupby(s.index.to_period("M")).apply(lambda x: np.prod(1 + x) - 1)
    bn = pd.read_csv("data/futures/BANKNIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]]
    t = tbb.run_live(bn[bn.index >= "2010-01-01"], tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **RULES["INDEX 1/2/2"])); t = t[~t.Open]
    s = pd.Series((t.Pct / 100 - 0.0005).values, index=pd.to_datetime(t.ExitDate)); bnm = s.groupby(s.index.to_period("M")).apply(lambda x: np.prod(1 + x) - 1)
    for rl in RULES:
        for lab in ("both sides", "buy only >200d"):
            keys = [("BTC-USD", rl, lab), ("ETH-USD", rl, lab)]
            if not all(k in months for k in keys):
                continue
            M = pd.DataFrame({"BN": bnm, "BTC": months[keys[0]], "ETH": months[keys[1]]}).sort_index()
            M = M[M.index >= pd.Period("2018-01", "M")].fillna(0.0)
            for nm, cols in (("BN alone", ["BN"]), ("BTC + ETH", ["BTC", "ETH"]), ("BN + BTC + ETH", ["BN", "BTC", "ETH"])):
                m = M[cols].mean(axis=1); eq = (1 + m).cumprod(); dd = (eq / eq.cummax() - 1).min(); yrs = len(m) / 12
                w = lambda y: (np.prod(1 + m.iloc[-12 * y:]) - 1) * 100  # noqa: E731
                print(f"R| BOOK 2018+ {rl:13s} {lab:15s} {nm:15s} | CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+6.1f}% monthly DD {dd * 100:+6.1f}% | "
                      f"1y {w(1):+6.1f} 2y {w(2):+6.1f} 3y {w(3):+6.1f} 5y {w(5):+6.1f} | corr BN-BTC {M.BN.corr(M.BTC):+.2f}", flush=True)


if __name__ == "__main__":
    main()
