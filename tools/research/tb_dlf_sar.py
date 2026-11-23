"""DLF Top Bottom, ALWAYS IN THE MARKET (stop-and-reverse), for a chart (24 Nov 2026, Amritpal).
Tradable version: buy-stop at the last top + 0.05%, sell-stop at the last bottom - 0.05% (levels from 1-day turning points of the daily
close, each level used once); hit the opposite level -> exit AND reverse. No entry-day / max / breakeven stops, no gap rule, so the only
exit is the opposite system point (always in after the first trade). Fill = the level, or the open if it gaps past it.
Also the course-sheet version (close-confirmed, booked at the level) for reference. Points per share; 0.1% cost per round trip.
Prints JSON chunks (R| J ...) with daily closes and trades for the chart."""
import base64
import json
import os
import sys
import zlib

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
import topbottom_backtest as tbb  # noqa: E402

d = yf.download("DLF.NS", start="2009-06-01", progress=False, auto_adjust=True)
d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
x = d[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.High >= x.Low) & (x.index >= "2010-01-01")].round(2)
sar = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, day_sl_pct=100, max_sl_pct=100, be_pct=0, gap_pct=100, event_exit=False))
sheet = tbb.run_sheet(x, tbb.Params(mode="sheet"))
buyflat = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, day_sl_pct=100, max_sl_pct=100, be_pct=0, gap_pct=100, event_exit=False, long_only=True))
buylive = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5, event_exit=False, long_only=True))
out = {"closes": [[str(i.date()), float(c)] for i, c in x.Close.items()]}
for nm, t in (("sar", sar), ("sheet", sheet), ("buyflat", buyflat), ("buylive", buylive)):
    t = t.copy(); t["EntryDate"] = pd.to_datetime(t.EntryDate).dt.strftime("%Y-%m-%d"); t["ExitDate"] = pd.to_datetime(t.ExitDate).dt.strftime("%Y-%m-%d")
    t["net"] = (t.Points - (t.Entry + t.Exit) * 0.0005).round(2)
    out[nm] = t[["EntryDate", "Side", "Entry", "ExitDate", "Exit", "Reason", "Points", "net", "Open"]].to_dict("records")
    r = t.net; g, b = r[r > 0].sum(), -r[r < 0].sum()
    print(f"R| {nm}: trades {len(t)} win {(r > 0).mean() * 100:.0f}% PF {g / b:.2f} net points {r.sum():,.0f} (long {t[t.Side == 'BUY'].net.sum():,.0f}, short {t[t.Side == 'SELL'].net.sum():,.0f})", flush=True)
s = base64.b64encode(zlib.compress(json.dumps(out, default=str).encode())).decode()
for i in range(0, len(s), 6000):
    print("R| J " + s[i:i + 6000], flush=True)
