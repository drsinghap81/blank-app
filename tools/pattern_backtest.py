"""Backtest every candlestick pattern x confluence on a folder of daily OHLCV CSVs.

Trade: enter at the NEXT open in the pattern's direction; stop just beyond the pattern's
extreme (low for bullish, high for bearish); targets 1R and 2R; exit at the close after
15 sessions if neither is hit. Gap through the stop = filled at the open.
Hit rate = % of trades reaching the target before the stop.
Drawdown = portfolio taking every trade at 0.5% risk each, booked on exit date.

    python tools/pattern_backtest.py DATA_DIR [OUT.csv]
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patterns as pt  # noqa: E402

HOLD, MAXRISK, MINRISK, COST = 15, 0.08, 0.003, 0.0010   # cost: 0.10% round trip of entry


def outcomes(df, sig):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(c)
    out = []
    for r in sig.itertuples():
        i, s = r.Bar, r.Side
        if i + 1 >= n:
            continue
        e = o[i + 1]
        stop = r.PLow * 0.999 if s > 0 else r.PHigh * 1.001
        risk = (e - stop) * s
        if risk <= 0 or risk / e > MAXRISK or risk / e < MINRISK:
            continue
        res = {}
        for tgt in (1, 2):
            t = e + s * tgt * risk
            R, j_exit = None, None
            for j in range(i + 1, min(i + 1 + HOLD, n)):
                if (s > 0 and l[j] <= stop) or (s < 0 and h[j] >= stop):
                    px = min(o[j], stop) if s > 0 else max(o[j], stop)
                    if j == i + 1:
                        px = stop
                    R, j_exit = (px - e) * s / risk, j
                    break
                if (s > 0 and h[j] >= t) or (s < 0 and l[j] <= t):
                    px = max(o[j], t) if s > 0 and j > i + 1 else (min(o[j], t) if s < 0 and j > i + 1 else t)
                    R, j_exit = tgt if j == i + 1 else (px - e) * s / risk, j
                    break
            if R is None:
                j_exit = min(i + HOLD, n - 1)
                R = (c[j_exit] - e) * s / risk
            R -= COST * e / risk
            res[f"R{tgt}"], res[f"x{tgt}"] = R, df.index[j_exit]
        out.append(dict(Date=r.Date, Pattern=r.Pattern, Side=s, Risk=risk / e, **res,
                        **{k: bool(getattr(r, k.replace("/", "_").replace(" ", "_"), False)) for k in []}))
    return out


def run(data_dir, start="2010-01-01"):
    rows = []
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    for f in files:
        sym = os.path.basename(f)[:-4]
        if sym in ("NIFTYBEES",):
            continue
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        df = df[(df.Close > 0)].dropna(subset=["Open", "High", "Low", "Close"])
        if len(df) < 260:
            continue
        sig = pt.detect(df)
        if sig.empty:
            continue
        sig = sig[sig.Date >= start]
        res = outcomes(df, sig)
        if not res:
            continue
        rd = pd.DataFrame(res)
        merged = sig.merge(rd, on=["Date", "Pattern", "Side"], how="inner")
        merged["Sym"] = sym
        rows.append(merged)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    T = run(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "pattern_trades.csv"
    T.to_csv(out, index=False)
    print(len(T), "trades written to", out)
