"""Pilot: world GICS sector rotation (tools/world_sector_rrg.py WSECT), dry run + ticker check (history length, volume)."""
import sys

import yfinance as yf

sys.path.insert(0, "tools")
import world_sector_rrg as W  # noqa: E402

t = list(W.CFG["WSECT"]["names"])
d = yf.download(t, period="2y", interval="1d", progress=False, auto_adjust=True, group_by="column")
for k in t:
    c = d["Close"][k].dropna(); v = d["Volume"][k].dropna()
    print(f"R| {k} {W.CFG['WSECT']['names'][k]}: days {len(c)}, last {c.index[-1].date() if len(c) else None}, avg $ volume/day {float((c * v).tail(60).mean()) / 1e6:.1f} m")
W.main("WSECT", dry=True)
