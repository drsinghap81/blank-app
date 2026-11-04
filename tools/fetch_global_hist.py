"""Daily OHLCV history (Yahoo, split/dividend adjusted, from 2005) of US or ASX stocks for backtests, plus the sector /
theme / broad indices and stock meta. Usage: python fetch_global_hist.py MARKET SHARD NSHARDS -> hist/<mkt>_<shard>.parquet
(shard 0 also writes hist/<mkt>_index.parquet and hist/<mkt>_meta.csv). Keeps a stock only if at some point its close was
>= 30 and its 20-day average traded value >= MINVAL (US $5 m, ASX A$1 m)."""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402
from global_sectors import fetch_meta, index_tickers  # noqa: E402

MKT, SH, NS = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
MINVAL = {"US": 5e6, "ASX": 1e6}[MKT]
os.makedirs("hist", exist_ok=True)


def dl(tickers):
    for _ in range(3):
        try:
            return yf.download(tickers, period="max", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("retry", e, flush=True); time.sleep(20)
    return None


def frames(dd, tickers, sym_of, keep_all=False):
    out = []
    for t in tickers:
        try:
            x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
        except Exception:  # noqa: BLE001
            continue
        x = x[x.index >= "2005-01-01"]
        if len(x) < 60:
            continue
        if not keep_all:
            v = (x.Close * x.Volume).rolling(20).mean()
            if not ((x.Close >= 30) & (v >= MINVAL)).any():
                continue
        x = x.astype("float32"); x["SYMBOL"] = sym_of[t]; x.index.name = "Date"
        out.append(x.reset_index())
    return out


def main():
    if SH == 0:
        try:
            m = fetch_meta(MKT); m.to_csv(f"hist/{MKT.lower()}_meta.csv", index=False); print("meta", len(m))
        except Exception as e:  # noqa: BLE001
            print("meta failed", e)
        it = index_tickers(MKT)
        dd = dl(it)
        F = frames(dd, it, {t: t for t in it}, keep_all=True) if dd is not None else []
        pd.concat(F).to_parquet(f"hist/{MKT.lower()}_index.parquet", index=False)
        print("indices", sorted({f.SYMBOL.iloc[0] for f in F}), "missing", sorted(set(it) - {f.SYMBOL.iloc[0] for f in F}))
    u = symbols(MKT).sort_values("symbol").reset_index(drop=True)
    u = u.iloc[SH::NS]
    sym_of = dict(zip(u.ticker, u.symbol))
    tick = list(u.ticker); print("shard", SH, "tickers", len(tick), flush=True)
    F = []
    for a in range(0, len(tick), 100):
        dd = dl(tick[a:a + 100])
        if dd is not None and not dd.empty:
            F += frames(dd, tick[a:a + 100], sym_of)
        print(a + 100, "kept", len(F), flush=True); time.sleep(1)
    H = pd.concat(F) if F else pd.DataFrame()
    H.to_parquet(f"hist/{MKT.lower()}_{SH}.parquet", index=False)
    print("stocks kept", len(F), "rows", len(H), "MB", os.path.getsize(f"hist/{MKT.lower()}_{SH}.parquet") / 1e6)


if __name__ == "__main__":
    main()
