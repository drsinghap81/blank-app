"""Top Bottom: ignore tiny turns? (27 Nov 2026, Amritpal, after a Bank Nifty entry off a 0.14% "top": "yes run for all top bottoms").
The live rule counts every 1-day turn in closes as a top / bottom (swing_pct 0). Here a top only counts once the close has fallen
>= X% below it (bottom: risen X% above it) - the engine's swing_pct - for X = 0 (live), 0.2, 0.3, 0.5, 1.0.
Every live Top Bottom sleeve, with its live rules and side:
  India futures (NSE bhavcopy near-month, data/futures): BANKNIFTY both sides 1/2/2 buffer 25 pts; NIFTY buy only 1/2/2 buffer 12 pts;
    BEL, LT, TMPV, TCS buy only 1.5/3/3 buffer 0.05%. Costs 0.05% (index) / 0.1% (stock) a round trip.
  MCX minis (COMEX/NYMEX x USD/INR, as tools/research/tb_mcx_minis.py): crude both sides; silver, natgas buy only > 200-day;
    gold buy only. 1/2/2, buffer 0.05%, cost 0.06%.
  moomoo ETFs (Yahoo, adjusted): US QQQ SMH XLF XLE, ASX TECH HACK OZR ASIA - buy only 1/2/2, buffer 0.05%, cost 0.1%.
Returns on full contract value, compounded per trade. Newest windows first; ex-Covid (2021+) and 2012+."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

IDX = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0)
STK = dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)
SWINGS = tuple(float(x) for x in os.environ.get("SWINGS", "0,0.2,0.3,0.5,1.0").split(","))
MCX = {"CRUDE": ("CL=F", 1.0), "SILVER": ("SI=F", 32.1507), "NATGAS": ("NG=F", 1.0), "GOLD": ("GC=F", 10 / 31.1035)}


def fut(sym):
    x = pd.read_csv(f"data/futures/{sym}.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]].dropna()
    return x[(x.High >= x.Low) & (x.Low > 0) & (x.index >= "2010-01-01")]


def yh(t, adj=True):
    d = yf.download(t, start="2009-01-01", progress=False, auto_adjust=adj)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); return x[(x.High >= x.Low) & (x.Low > 0)]


def mcx(name):
    t, m = MCX[name]; x = yh(t, adj=False); fx = yh("INR=X", adj=False).Close.reindex(x.index).ffill()
    x = x.mul(fx * m, axis=0).dropna()
    return x[(x.Close > 0)]


def trades(df, rules, side, trend, buf_pts, sw):
    p = tbb.Params(buffer_pct=0.0 if buf_pts else 0.05, buffer_pts=buf_pts, event_exit=False, long_only=side == "buy", swing_pct=sw, day_sl_fill=os.environ.get("FILL", "stop"), **rules)
    t = tbb.run_live(df, p); t = t[~t.Open] if "Open" in t else t
    if trend and len(t):
        above = (df.Close > df.Close.rolling(200).mean()).to_numpy(); ix = df.index.get_indexer(pd.to_datetime(t.EntryDate))
        t = t[[bool(above[max(0, i - 1)]) for i in ix]]
    return t


def stats(t, cost, start, end):
    t = t[pd.to_datetime(t.EntryDate) >= start]
    if len(t) < 3:
        return None
    r = (t.Pct / 100 - cost).to_numpy(); eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(eq) - 1).min()
    yrs = max(0.5, (end - start).days / 365.25); g, b = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), win=(r > 0).mean() * 100, pf=g / b if b else 9, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=dd * 100)


def main():
    S = []
    for s, side, rules, buf, cost in (("BANKNIFTY", "both", IDX, 25, 0.0005), ("NIFTY", "buy", IDX, 12, 0.0005), ("BEL", "buy", STK, 0, 0.001),
                                      ("LT", "buy", STK, 0, 0.001), ("TMPV", "buy", STK, 0, 0.001), ("TCS", "buy", STK, 0, 0.001)):
        S.append((s, lambda s=s: fut(s), side, rules, buf, cost, False))
    for nm, side, tr in (("CRUDE", "both", False), ("SILVER", "buy", True), ("NATGAS", "buy", True), ("GOLD", "buy", False)):
        S.append(("MCX " + nm, lambda nm=nm: mcx(nm), side, IDX, 0, 0.0006, tr))
    for tk in ("QQQ", "SMH", "XLF", "XLE"):
        S.append(("US " + tk, lambda tk=tk: yh(tk), "buy", IDX, 0, 0.001, False))
    for tk in ("TECH", "HACK", "OZR", "ASIA"):
        S.append(("ASX " + tk, lambda tk=tk: yh(tk + ".AX"), "buy", IDX, 0, 0.001, False))
    summ = {sw: {"2021": {}, "2012": {}} for sw in SWINGS}
    for nm, load, side, rules, buf, cost, tr in S:
        try:
            df = load()
        except Exception as ex:  # noqa: BLE001
            print(f"R| {nm} no data {ex}", flush=True); continue
        if len(df) < 300:
            print(f"R| {nm} too little data ({len(df)})", flush=True); continue
        end = df.index[-1]
        print(f"R| == {nm} ({side}{' >200d' if tr else ''}) {df.index[0].date()} -> {end.date()}", flush=True)
        for sw in SWINGS:
            t = trades(df, rules, side, tr, buf, sw)
            row = []
            for lab, st in (("1y", end - pd.DateOffset(years=1)), ("3y", end - pd.DateOffset(years=3)), ("2021+", pd.Timestamp("2021-01-01")),
                            ("2012+", max(pd.Timestamp("2012-01-01"), df.index[0] + pd.DateOffset(days=250)))):
                x = stats(t, cost, st, end)
                row.append(f"{lab} " + (f"n{x['n']:3d} PF {x['pf']:.2f} {x['cagr']:+5.1f}%/yr DD {x['dd']:+5.1f}%" if x else "-"))
                if x and lab in ("2021+", "2012+"):
                    summ[sw][lab[:4]][nm] = (x["cagr"], x["pf"], x["dd"])
            print(f"R| {nm:10s} swing {sw:.1f}% | " + " | ".join(row), flush=True)
    print("R| ===== AVERAGE across sleeves (CAGR / PF / worst fall)", flush=True)
    for sw in SWINGS:
        out = []
        for k in ("2021", "2012"):
            D = summ[sw][k]; L = summ[0.0][k]
            a = np.array(list(D.values())) if D else np.zeros((1, 3))
            better = sum(1 for n_, v in D.items() if n_ in L and v[0] > L[n_][0])
            out.append(f"{k}+ n{len(D)} {a[:, 0].mean():+5.1f}%/yr PF {a[:, 1].mean():.2f} DD {a[:, 2].mean():+5.1f}% better-than-live {better}/{len(D)}")
        print(f"R| swing {sw:.1f}% | " + " | ".join(out), flush=True)


if __name__ == "__main__":
    main()
