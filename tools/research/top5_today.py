"""One-off (19 Nov 2026): TODAY's move of the Top 5 vs their industry and theme (median of member stocks today), their sector
index and Nifty. Yahoo daily bars (today's partial bar in market hours)."""
import json

import pandas as pd
import yfinance as yf

PICKS = ["KOTAKBANK", "ETERNAL", "MEESHO", "DRREDDY", "PRIMESECU"]
SEC = {"KOTAKBANK": "NIFTY_FIN_SERVICE.NS", "PRIMESECU": "NIFTY_FIN_SERVICE.NS", "ETERNAL": "^CNXCONSUM", "MEESHO": "^CNXCONSUM", "DRREDDY": "^CNXPHARMA"}
S = json.load(open("data/scan/sectors.json")); ind = S["symbols"]; th = S.get("themes", {})
need = set(PICKS)
for p in PICKS:
    need |= {s for s, i in ind.items() if i == ind.get(p)}
    for t in th.get(p, []):
        need |= {s for s, ts in th.items() if t in ts}
tick = sorted(need)
D = yf.download([s + ".NS" for s in tick] + ["^NSEI"] + sorted(set(SEC.values())), period="5d", interval="1d", progress=False, auto_adjust=True)["Close"]
chg = (D.iloc[-1] / D.iloc[-2] - 1) * 100
print("last bar", D.index[-1])
med = lambda L: round(float(chg.reindex([s + ".NS" for s in L]).dropna().median()), 2) if L else None  # noqa: E731
for p in PICKS:
    peers = [s for s, i in ind.items() if i == ind.get(p) and s != p]
    tl = []
    for t in th.get(p, []):
        m = [s for s, ts in th.items() if t in ts and s != p]
        tl.append(f"{t.replace('NIFTY ', '')} {med(m)}% ({len(m)})")
    print(f"R| {p}: stock {round(float(chg.get(p + '.NS', float('nan'))), 2)}% | industry {ind.get(p)} median {med(peers)}% ({len(peers)} stocks) | "
          f"sector index {SEC[p]} {round(float(chg[SEC[p]]), 2)}% | Nifty {round(float(chg['^NSEI']), 2)}% | themes: {'; '.join(tl) or '-'}")
