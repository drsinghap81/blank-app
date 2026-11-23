"""Today's Top Bottom levels on the ASX ETFs that tested well (24 Nov 2026). Buy only, ETF rules 1/2/2, buffer 0.05%.
For each ETF: is the system in a trade (since when, entry, current stop) or flat (buy-stop level, initial stop, skip-if-gap level)."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", "angel"))
import topbottom_backtest as tbb  # noqa: E402
import tb_live as tl  # noqa: E402

LIST = ["TECH", "ACDC", "HACK", "MNRS", "ASIA", "OZR", "QRE", "QFN", "NDQ", "ATEC", "SEMI", "ROBO", "IVV", "FANG", "GOLD", "ETPMAG"]
CFG = dict(tl.DEFAULT_CFG, buffer_pts=0, buffer_pct=0.05, day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0, long_only=True, event_exit=False)


def main():
    for tk in LIST:
        d = yf.download(tk + ".AX", start="2015-01-01", progress=False, auto_adjust=True)
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
        d = d[["Open", "High", "Low", "Close"]].dropna(); d = d[(d.High >= d.Low) & (d.Low > 0)]
        if len(d) < 300:
            continue
        last = d.index[-1]; c = d.Close.iloc[-1]
        t = tbb.run_live(d, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0))
        op = t[t.Open] if len(t) else t
        top, bot = tl.levels(d)
        if len(op):
            r = op.iloc[-1]; e = float(r.Entry); since = pd.Timestamp(r.EntryDate)
            hi = d.High[d.index >= since].max(); be = hi >= e * 1.02
            st = tl.State(pos=1, lots=1, entry=e, entry_date=str(since.date()), be_on=bool(be))
            p = tl.make_plan(d, st, CFG)
            print(f"R| {tk:6s} IN TRADE since {since.date()} @ {e:.3f} | last close {c:.3f} ({(c / e - 1) * 100:+.1f}%) | stop now {p['prot']:.3f}{' (breakeven on)' if be else ''} "
                  f"| {'stop = swing bottom (system exit)' if p['prot_is_sys'] else 'stop = max loss / breakeven'} | close {last.date()}", flush=True)
        else:
            st = tl.init_flat_state(d, CFG); p = tl.make_plan(d, st, CFG)
            if p["buy_lvl"]:
                L = p["buy_lvl"]; s0 = max(L * 0.98, (bot - bot * 0.0005) if bot else 0)
                print(f"R| {tk:6s} FLAT | BUY-STOP above {L:.3f} ({(L / c - 1) * 100:+.1f}% from close {c:.3f}) | skip if it opens above {L * 1.01:.3f} | "
                      f"initial stop {s0:.3f} ({(s0 / L - 1) * 100:.1f}%) | entry-day: exit if close < {L * 0.99:.3f} | close {last.date()}", flush=True)
            else:
                print(f"R| {tk:6s} FLAT | no buy level: last top {top} already used - wait for a new swing top | close {c:.3f} {last.date()}", flush=True)


if __name__ == "__main__":
    main()
