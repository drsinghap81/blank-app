"""Top Bottom on ASX-listed ETFs in AUD (24 Nov 2026, Amritpal: A$19,500 in his moomoo AU account, trade in AUD - no FX).
Yahoo daily (adjusted) 2012 -> today. Live engine, buffer 0.05%, ETF rules 1/2/2 and stock rules 1.5/3/3, 0.1% cost a round trip
(ASX spreads + brokerage on small orders). Buy only, both sides shown for reference. Newest first + 2012-18 vs 2019-26 persistence."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

ETFS = {"NDQ": "Nasdaq 100 (AUD)", "SEMI": "Semiconductors", "IVV": "S&P 500 (AUD)", "IOO": "Global 100", "FANG": "FANG+", "HACK": "Cybersecurity",
        "ATEC": "ASX tech", "A200": "ASX 200", "STW": "ASX 200 (SPDR)", "IOZ": "ASX 200 (iShares)", "MVW": "ASX equal weight", "QFN": "ASX financials",
        "OZR": "ASX resources", "MVR": "ASX resources EW", "QRE": "ASX resources", "GOLD": "Gold (AUD)", "QAU": "Gold hedged", "ETPMAG": "Silver",
        "MNRS": "Gold miners", "URNM": "Uranium", "ACDC": "Battery tech", "ASIA": "Asia tech", "NDIA": "India", "IJH": "US midcap", "QUAL": "World quality",
        "ROBO": "Robotics", "TECH": "Global tech", "WXOZ": "World ex-AU", "VAS": "ASX 300 (Vanguard)", "VGS": "World (Vanguard)", "QPON": "Bank bonds"}
RULES = {"ETF 1/2/2": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0), "STOCK 1.5/3/3": dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)}
COST = 0.001


def st(t, end, d0):
    if t.empty or len(t) < 10:
        return None
    r = t.Pct / 100 - COST; g, b = r[r > 0].sum(), -r[r < 0].sum(); eq = np.cumprod(1 + r.values)
    yrs = max(1, (end - d0).days / 365.25); xd = pd.to_datetime(t.ExitDate)
    w = lambda y: (np.prod(1 + r[xd > end - pd.DateOffset(years=y)]) - 1) * 100
    a, b2 = r[xd < "2019-01-01"], r[xd >= "2019-01-01"]
    pf = lambda x: x[x > 0].sum() / max(1e-9, -x[x < 0].sum()) if len(x) > 5 else np.nan
    return dict(n=len(t), pf=g / b if b else 9, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=(eq / np.maximum.accumulate(eq) - 1).min() * 100,
                y1=w(1), y2=w(2), y3=w(3), y5=w(5), pfa=pf(a), pfb=pf(b2))


def main():
    rows = []
    for tk, nm in ETFS.items():
        try:
            d = yf.download(tk + ".AX", start="2011-06-01", progress=False, auto_adjust=True)
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
            d = d[["Open", "High", "Low", "Close"]].dropna(); d = d[(d.High >= d.Low) & (d.Low > 0) & (d.Volume if False else True)]
        except Exception as ex:  # noqa: BLE001
            print(f"R| {tk} failed {ex}", flush=True); continue
        if len(d) < 500:
            print(f"R| {tk} too short ({len(d)})", flush=True); continue
        end, d0 = d.index[-1], d.index[0]; yrs = (end - d0).days / 365.25
        bh = ((d.Close.iloc[-1] / d.Close.iloc[0]) ** (1 / yrs) - 1) * 100; bhdd = (d.Close / d.Close.cummax() - 1).min() * 100
        for rl, kw in RULES.items():
            for side, lo in (("buy only", True), ("both", False)):
                t = tbb.run_live(d, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=lo, **kw)); t = t[~t.Open]
                S = st(t, end, d0)
                if S:
                    rows.append(dict(tk=tk, nm=nm, rule=rl, side=side, start=d0.year, bh=bh, bhdd=bhdd, **S))
        print(f"R| done {tk} from {d0.date()}", flush=True)
    D = pd.DataFrame(rows)
    B = D[(D.side == "buy only") & (D.rule == "ETF 1/2/2")].sort_values("pfb", ascending=False)
    print("R| BUY ONLY, ETF rules 1/2/2 (sorted by 2019-26 PF)", flush=True)
    for r in B.itertuples():
        print(f"R| {r.tk:6s} {r.nm[:22]:22s} from {r.start} | PF {r.pf:.2f} (2012-18 {r.pfa:.2f} / 2019-26 {r.pfb:.2f}) | CAGR {r.cagr:+5.1f}% DD {r.dd:+6.1f}% | 1y {r.y1:+5.1f} 2y {r.y2:+5.1f} 3y {r.y3:+5.1f} 5y {r.y5:+5.1f} | hold {r.bh:+5.1f}%/yr DD {r.bhdd:+5.1f}%", flush=True)
    for rl in RULES:
        for side in ("buy only", "both"):
            x = D[(D.rule == rl) & (D.side == side)]
            print(f"R| SUMMARY {rl} {side}: median PF {x.pf.median():.2f} | profitable {(x.pf > 1).mean() * 100:.0f}% | median CAGR {x.cagr.median():+.1f}% | 2019-26 PF>1 {(x.pfb > 1).mean() * 100:.0f}% | rank corr PF 12-18 vs 19-26 {x.pfa.rank().corr(x.pfb.rank()):+.2f}", flush=True)


if __name__ == "__main__":
    main()
