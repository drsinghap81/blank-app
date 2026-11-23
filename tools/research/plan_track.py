"""Track a saved trade plan (13 Nov 2026 close -> orders for 16 Nov) to date: fill rules as the plan says (limit 'at the open': filled at
the open if open <= limit, else skipped; stop-limit: filled if high >= trigger, at max(open, trigger) if <= limit). Then the protective
stop: first day low <= stop -> out at min(open, stop). Mark to the latest close. Read-only."""
import pandas as pd
import yfinance as yf

PLAN = [("ZIMLAB", "Momentum", "L", 142.30, None, 120.17, 411), ("GLOBAL", "Momentum", "L", 146.49, None, 116.41, 302),
        ("GRAPHITE", "Momentum", "SL", 820.77, 812.65, 716.38, 94), ("DRREDDY", "Momentum", "L", 1393.80, None, 1249.80, 63),
        ("HEGAM", "Momentum", "L", 280.63, None, 226.16, 167), ("MAHLOG", "9/21", "L", 434.05, None, 412.10, 414),
        ("MATRIMONY", "Retest", "L", 567.97, None, 522.32, 199), ("ENTERO", "Retest", "L", 1988.39, None, 1794.59, 46),
        ("LEMONTREE", "Bottom", "L", 121.96, None, 101.28, 440), ("SWIGGY", "Bottom", "L", 186.70, None, 172.75, 652),
        ("GPPL", "Bottom", "L", 173.59, None, 138.64, 260), ("FRACTAL", "Bottom", "L", 830.80, None, 689.34, 64),
        ("ZAGGLE", "Bottom", "L", 173.32, None, 146.94, 345), ("HDFCBANK", "Bottom", "L", 804.00, None, 671.86, 68),
        ("MARATHON", "Bottom", "L", 435.90, None, 345.46, 100), ("SESHAPAPER", "Bottom", "L", 216.31, None, 187.70, 318),
        ("STANLEY", "Bottom", "L", 136.86, None, 123.75, 694), ("BHARTIARTL", "Bottom", "L", 2106.00, None, 1709.04, 22),
        ("EMAMILTD", "Bottom", "L", 408.10, None, 349.15, 154), ("ABREL", "Bottom", "L", 1203.00, None, 985.05, 41),
        ("HAVELLS", "Bottom", "L", 1161.00, None, 989.21, 52), ("IOC", "Bottom", "L", 144.04, None, 124.10, 456),
        ("ANURAS", "Bottom", "L", 1300.60, None, 1066.72, 38), ("TIRUMALCHM", "Bottom", "L", 122.77, None, 112.12, 854),
        ("GANESHCP", "Bottom", "L", 180.04, None, 140.48, 230), ("GRAPHITE", "My picks", "L", 816.71, None, 747.64, 140),
        ("DRREDDY", "My picks", "L", 1410.65, None, 1291.34, 81), ("SYNGENE", "My picks", "L", 399.49, None, 341.75, 163),
        ("EG", "My picks", "L", 429.33, None, 393.01, 266)]
syms = sorted({p[0] + ".NS" for p in PLAN}) + ["^NSEI"]
d = yf.download(syms, start="2026-11-13", progress=False, auto_adjust=False, group_by="ticker")
n = d["^NSEI"].dropna(subset=["Close"]); print(f"R| NIFTY 13 Nov close {n.Close.iloc[0]:.1f} -> {n.index[-1].date()} {n.Close.iloc[-1]:.1f} ({(n.Close.iloc[-1] / n.Close.iloc[0] - 1) * 100:+.2f}%)")
tot_inv = tot_pnl = 0
for sym, sysn, kind, lim, trig, stop, q in PLAN:
    x = d[sym + ".NS"].dropna(subset=["Close"]); x = x[x.index >= "2026-11-16"]
    if not len(x):
        print(f"R| {sym} | no data"); continue
    o, h = x.Open.iloc[0], x.High.iloc[0]
    if kind == "L":
        fill = o if o <= lim else None
    else:
        fill = max(o, trig) if h >= trig and max(o, trig) <= lim else None
    if fill is None:
        print(f"R| {sym:10s} | {sysn:8s} | NOT FILLED (open {o:.2f} vs limit {lim})"); continue
    out, why = None, "open"
    for i, (dt, r) in enumerate(x.iterrows()):
        if r.Low <= stop:
            out = min(r.Open, stop) if i > 0 else stop; why = f"stopped {dt.date()}"; break
    px = out if out is not None else x.Close.iloc[-1]
    pnl = (px - fill) * q; tot_inv += fill * q; tot_pnl += pnl
    print(f"R| {sym:10s} | {sysn:8s} | filled {fill:.2f} x{q} | {why} | now {px:.2f} | {(px / fill - 1) * 100:+.2f}% | Rs {pnl:+,.0f}")
print(f"R| TOTAL invested Rs {tot_inv:,.0f} | P&L Rs {tot_pnl:+,.0f} ({tot_pnl / tot_inv * 100:+.2f}%) | on Rs 20 L capital {tot_pnl / 2e6 * 100:+.2f}% | last bar {d.index[-1].date()}")
