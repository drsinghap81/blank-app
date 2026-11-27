"""Gap fixes for Top Bottom on crypto ETFs (27 Nov 2026, Amritpal: "can something be done around this"): buy only, ETF rules as the
bot, then one change at a time - no gap skip, no entry-day stop, wider stops, and both. Same data / costs as tb_crypto_etf.py."""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import tb_crypto_etf as E  # noqa: E402

VAR = {"as the bot (1/2/2, skip gaps > 1%)": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0),
       "no gap skip": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=99.0),
       "no entry-day stop": dict(day_sl_pct=99.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0),
       "no gap skip + no entry-day stop": dict(day_sl_pct=99.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=99.0),
       "wider 2/4/4": dict(day_sl_pct=2.0, max_sl_pct=4.0, be_pct=4.0, gap_pct=2.0),
       "wider 3/6/6 (crypto-scaled)": dict(day_sl_pct=3.0, max_sl_pct=6.0, be_pct=6.0, gap_pct=3.0),
       "wider 3/6/6, no gap skip": dict(day_sl_pct=3.0, max_sl_pct=6.0, be_pct=6.0, gap_pct=99.0)}


def main():
    for tk, start in (("IBIT", "2024-01-11"), ("FBTC", "2024-01-11"), ("ETHA", "2024-07-23"), ("BITO", "2021-10-19")):
        df = E.yh(tk)
        print(f"R| == {tk} from {start}", flush=True)
        for nm, kw in VAR.items():
            S = E.run(df, kw, "buy only", pd.Timestamp(start))
            if S:
                print(f"R| {tk:5s} {nm:34s} | n {S['n']:3d} win {S['win']:3.0f}% PF {S['pf']:.2f} | CAGR {S['cagr']:+6.1f}% DD {S['dd']:+6.1f}% | 1y {S['y1']:+6.1f} 2y {S['y2']:+6.1f}", flush=True)


if __name__ == "__main__":
    main()
