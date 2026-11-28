"""Top Bottom: does a proper V (ignore shallow turns) help once entry-day stops are booked honestly? (28 Nov 2026, Amritpal:
"that's why I told that the system point has to be a proper V shape, not a very shallow one").
Found today: the engine checks the 1% entry-day stop on the close but books it AT the stop level. Honest versions:
  close    = exit at the close when it is beyond the stop
  intraday = a resting stop order at 1% hit whenever the day's range touches it (pessimistic on the order of the day's moves)
V shape = engine swing_pct: a top counts only after the close falls >= X% below it (a bottom: rises X%), zig-zag on the closes.
COINS env (default BTC-USD,ETH-USD). Paper-book rules: buffer 0.05%, 1/2/2, 0.1% cost. Windows newest first."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import topbottom_backtest as tbb  # noqa: E402
import paper_crypto_tb as pc  # noqa: E402


def stats(t, st):
    t = t[(pd.to_datetime(t.EntryDate) >= st) & (~t.Open)]
    if not len(t):
        return "n 0"
    r = t.Pct.to_numpy() / 100 - pc.COST; eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(np.r_[1, eq])[1:] - 1).min()
    return f"{(eq[-1] - 1) * 100:+7.0f}% n{len(t):4d} win{(r > 0).mean() * 100:3.0f}% dd{dd * 100:4.0f}%"


def main():
    for sym in os.environ.get("COINS", "BTC-USD,ETH-USD").split(","):
        df = pc.bars(sym); today = pd.Timestamp.utcnow().tz_localize(None).normalize(); df = df[df.index < today]
        end = df.index[-1]; W = [("1y", end - pd.DateOffset(years=1)), ("3y", end - pd.DateOffset(years=3)), ("5y", end - pd.DateOffset(years=5))]
        for side, lo in (("both", False), ("buy", True)):
            for fill in ("stop", "close", "intraday"):
                for sw in (0, 0.3, 0.5, 1.0, 2.0, 3.0):
                    out = []
                    for lab, st in W:
                        p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=lo, swing_pct=sw, day_sl_fill=fill,
                                       start_flat_on=str(st.date()), **pc.RULES)
                        out.append(f"{lab} {stats(tbb.run_live(df, p), st)}")
                    print(f"R| {sym:8s} {side:4s} fill={fill:8s} V>={sw:3.1f}% | " + " | ".join(out), flush=True)


if __name__ == "__main__":
    main()
