"""Trade the course SHEET as closely as possible (28 Nov 2026, Amritpal: "you need to find a method to trade as the sheet does").
Sheet: always in the market; reverse when the CLOSE crosses the last top / bottom (1-day turns of the close), booked at the level.
HYBRID (tradable): a stop order rests at the level all day (fills at the level, or at the open on a gap through it).
  - if the day CLOSES beyond the level -> keep it: same trade and same price as the sheet (except gap days);
  - if the close comes back (false touch) -> at ~3:25 pm undo it: cover the new trade and go back to the old side at the close.
So every sheet trade is taken at the sheet price; the cost is the false touches (2 x level-to-close) and gaps.
Optional buffer (points beyond the level). Points per unit; Bank Nifty futures 2012-Mar 2022 (repo file) or Yahoo index (INDEX=1)."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import topbottom_backtest as tbb  # noqa: E402


def sim(d, buf=0.0, mode="hybrid"):
    o, h, l, c = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); n = len(c)
    T, B, _ = tbb.confirmed_swings(c, 0.0)
    pos, ent = 0, 0.0; out = []  # (date, kind, pnl)
    for i in range(1, n):
        top, bot = T[i - 1], B[i - 1]
        if np.isnan(top) or np.isnan(bot):
            continue
        if pos == 0:                                    # start: take the first sheet signal at the close
            if c[i] > top: pos, ent = 1, c[i]
            elif c[i] < bot: pos, ent = -1, c[i]
            continue
        lvl = bot - buf if pos > 0 else top + buf
        touched = (l[i] <= lvl) if pos > 0 else (h[i] >= lvl)
        if not touched:
            continue
        fill = min(o[i], lvl) if pos > 0 else max(o[i], lvl)
        confirmed = (c[i] < bot) if pos > 0 else (c[i] > top)
        if mode == "sheet":
            if confirmed:
                lv = bot if pos > 0 else top
                out.append((d.index[i], "trade", (lv - ent) * pos)); pos, ent = -pos, lv
            continue
        if confirmed:
            out.append((d.index[i], "trade", (fill - ent) * pos)); pos, ent = -pos, fill
        else:   # false touch: old side closed at fill, new side opened at fill and closed at the close, old side re-opened at the close
            out.append((d.index[i], "false", (fill - ent) * pos + (c[i] - fill) * (-pos))); ent = c[i]
    if pos:
        out.append((d.index[-1], "open", (c[-1] - ent) * pos))
    return pd.DataFrame(out, columns=["d", "k", "p"])


def load():
    if os.environ.get("INDEX"):
        import yfinance as yf
        x = yf.download("^NSEBANK", start="2010-01-01", progress=False, auto_adjust=False)
        x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]; x.index = pd.to_datetime(x.index).tz_localize(None)
        return x[["Open", "High", "Low", "Close"]].dropna()
    return pd.read_csv(os.path.join(HERE, "..", "..", "data", "banknifty_fut_near_2007-2022.csv"), parse_dates=["Date"]).set_index("Date")


def main():
    d = load(); end = d.index[-1]
    W = [("2017", "2017-01-01", "2017-12-31"), ("last 1y", end - pd.DateOffset(years=1), end), ("last 3y", end - pd.DateOffset(years=3), end),
         ("2021+", "2021-01-01", end), ("2015+", "2015-01-01", end)]
    runs = [("sheet as written", sim(d, mode="sheet"))] + [(f"hybrid buffer {b:g}", sim(d, b)) for b in (0, 10, 25)]
    for lab, a, b in W:
        row = []
        for nm, t in runs:
            z = t[(t.d >= pd.Timestamp(a)) & (t.d <= pd.Timestamp(b))]
            f = z[z.k == "false"]
            row.append(f"{nm} {z.p.sum():+8.0f} (false touches {len(f)} {f.p.sum():+.0f})")
        print(f"R| {lab:8s} | " + " | ".join(row), flush=True)


if __name__ == "__main__":
    main()
