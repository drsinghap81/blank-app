"""Top Bottom on US-listed Bitcoin / Ether ETFs (27 Nov 2026, Amritpal: moomoo AU can't trade coins - "yes do it" for the ETF route).
ETFs trade US hours only, so weekend / overnight coin moves arrive as opening gaps (the coin test, tb_crypto.py, ran on 24/7 bars).
Yahoo daily, buffer 0.05%, 0.1% cost a round trip, returns on full value compounded per trade. The moomoo bot is BUY ONLY with ETF
rules 1/2/2 (as the US ETF Top Bottom bot); both sides and the 200-day filter shown for reference.
  IBIT (iShares Bitcoin, Jan 2024), FBTC (Fidelity Bitcoin, Jan 2024), ETHA (iShares Ether, Jul 2024),
  BITO (Bitcoin futures ETF, Oct 2021), GBTC (Grayscale Bitcoin, OTC trust 2015 -> ETF Jan 2024; premium/discount before 2024),
  ETHE (Grayscale Ether, OTC 2019 -> ETF Jul 2024), and BTC-USD / ETH-USD over the same dates for comparison."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

RULES = {"ETF 1/2/2": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0), "STOCK 1.5/3/3": dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)}
COST = 0.001


def yh(t, start="2014-01-01"):
    d = yf.download(t, start=start, progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); return x[(x.High >= x.Low) & (x.Low > 0)]


def run(df, rules, lab, start):
    p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=lab != "both sides", **rules)
    t = tbb.run_live(df, p); t = t[~t.Open] if "Open" in t else t
    if lab == "buy only >200d" and len(t):
        above = (df.Close > df.Close.rolling(200).mean()).to_numpy(); ix = df.index.get_indexer(pd.to_datetime(t.EntryDate))
        t = t[[bool(above[max(0, i - 1)]) for i in ix]]
    t = t[pd.to_datetime(t.EntryDate) >= start]
    if not len(t):
        return None
    r = (t.Pct / 100 - COST).to_numpy(); ext = pd.to_datetime(t.ExitDate).to_numpy(); end = df.index[-1]
    eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(eq) - 1).min(); yrs = max(0.5, (df.index[-1] - pd.Timestamp(start)).days / 365.25)
    g, b = r[r > 0].sum(), -r[r < 0].sum()
    w = lambda y: (np.prod(1 + r[ext > np.datetime64(end - pd.DateOffset(years=y))]) - 1) * 100  # noqa: E731
    hold = (df.Close.iloc[-1] / df.Close[df.index >= start].iloc[0]) ** (1 / yrs) - 1
    return dict(n=len(r), win=(r > 0).mean() * 100, pf=g / b if b else 9, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=dd * 100, y1=w(1), y2=w(2), hold=hold * 100)


def main():
    for tk, start in (("IBIT", "2024-01-11"), ("FBTC", "2024-01-11"), ("ETHA", "2024-07-23"), ("BITO", "2021-10-19"), ("GBTC", "2016-01-01"),
                      ("ETHE", "2020-01-01"), ("BTC-USD", "2024-01-11"), ("ETH-USD", "2024-07-23"), ("BTC-USD", "2021-10-19")):
        try:
            df = yh(tk, "2014-01-01")
        except Exception as ex:  # noqa: BLE001
            print(f"R| {tk} no data {ex}", flush=True); continue
        if len(df) < 60:
            print(f"R| {tk} too little data", flush=True); continue
        print(f"R| == {tk} from {start} | last {df.index[-1].date()} {df.Close.iloc[-1]:,.2f}", flush=True)
        for rl, kw in RULES.items():
            for lab in ("buy only", "buy only >200d", "both sides"):
                S = run(df, kw, lab, pd.Timestamp(start))
                if S:
                    print(f"R| {tk:8s} {rl:13s} {lab:15s} | n {S['n']:3d} win {S['win']:3.0f}% PF {S['pf']:.2f} | CAGR {S['cagr']:+7.1f}% DD {S['dd']:+6.1f}% | "
                          f"1y {S['y1']:+7.1f} 2y {S['y2']:+7.1f} | buy&hold {S['hold']:+6.1f}%/yr", flush=True)


if __name__ == "__main__":
    main()
