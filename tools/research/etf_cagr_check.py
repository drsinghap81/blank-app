"""Check an ETF's advertised return (28 Nov 2026: Betashares ad "HACK 19.04% p.a. over the last 10 years, returns as at 31 Aug 2026")."""
import pandas as pd
import yfinance as yf

for t in ("HACK.AX", "NDQ.AX", "IOZ.AX", "^AXJO"):
    for adj in (True, False):
        d = yf.download(t, start="2016-07-01", end="2026-11-28", progress=False, auto_adjust=adj)["Close"].squeeze().dropna()
        d.index = pd.to_datetime(d.index).tz_localize(None)
        def cagr(a, b):
            x = d[:a].iloc[-1]; y = d[:b].iloc[-1]; yrs = (pd.Timestamp(b) - pd.Timestamp(a)).days / 365.25
            return (y / x) ** (1 / yrs) * 100 - 100
        print(f"R| {t:8s} {'total return (adj)' if adj else 'price only':18s} 10y to 31 Aug 2026 {cagr('2016-08-31', '2026-08-31'):+.2f}%/yr | "
              f"5y {cagr('2021-08-31', '2026-08-31'):+.2f} | 3y {cagr('2023-08-31', '2026-08-31'):+.2f} | 1y {cagr('2025-08-31', '2026-08-31'):+.2f} | "
              f"since 31 Aug to now {(d.iloc[-1] / d[:'2026-08-31'].iloc[-1] - 1) * 100:+.1f}% (last {d.index[-1].date()})", flush=True)
    dd = (d / d.cummax() - 1)
    print(f"R| {t} worst fall since 2016 {dd.min() * 100:.0f}% ({dd.idxmin().date()})", flush=True)
