"""Variants of the EMA 9/21 cross backtest for one market: stricter liquidity and minimum price.
Downloads once (same pipeline as trend_bt_global.py), then reruns the portfolio with filtered signals.
Usage: python trend_bt_variants.py MARKET -> data/btv/<MARKET>.json
"""
import json
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import MARKETS  # noqa: E402
from trend_bt_global import load, run, stats  # noqa: E402

VARIANTS = {
    "US": [("base $2m", 2e6, 3), ("$10m", 1e7, 3), ("$25m, price>=$10", 2.5e7, 10), ("$50m, price>=$10", 5e7, 10),
           ("$100m, price>=$10", 1e8, 10)],
    "ASX": [("base A$0.5m", 5e5, 0), ("A$2m, price>=A$0.50", 2e6, 0.5), ("A$5m, price>=A$1", 5e6, 1),
            ("A$10m, price>=A$1", 1e7, 1), ("A$20m, price>=A$2", 2e7, 2)],
    "NSE": [("base ₹1cr", 1e7, 0), ("₹5cr", 5e7, 50), ("₹20cr", 2e8, 100)],
}


def main():
    market = sys.argv[1]
    cfg = MARKETS[market]
    os.makedirs("data/btv", exist_ok=True)
    d, u = load(market)
    out = []
    for name, minval, minpx in VARIANTS[market]:
        x = d.copy()
        x["sig"] = x.sig & (x.val >= minval) & (x.CLOSE >= minpx)
        res = []
        for seed in range(3):
            eq, T = run(x, cfg, seed=seed)
            a = stats(eq, "2017-01-01", "2030-01-01"); c = stats(eq, "2022-01-01", "2030-01-01")
            res.append(dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], trades=len(T),
                            pf=round(T.pnl[T.pnl > 0].sum() / max(-T.pnl[T.pnl < 0].sum(), 1), 2) if len(T) else None))
        R = pd.DataFrame(res)
        row = dict(variant=name, signals=int(x.sig.sum()), cagr=float(R.cagr.median()), cagr_min=float(R.cagr.min()),
                   cagr_max=float(R.cagr.max()), maxdd=float(R.maxdd.median()), cagr_22_26=float(R.cagr_22_26.median()),
                   pf=float(R.pf.median()), trades=float(R.trades.median()))
        print(row, flush=True)
        out.append(row)
    json.dump(dict(market=market, asof=str(date.today()), variants=out), open(f"data/btv/{market}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
