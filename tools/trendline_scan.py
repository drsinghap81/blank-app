"""Trend line scan (17 Nov 2026): for every Nifty 500 stock, Indian sector index, world index and a few commodities /
crypto, draw the line through the 2 latest swing lows (right to left: the newest swing low and the one before it;
swing low = lowest low with 5 days each side). Rising lines only.

Writes data/scan/trendline.json. The live server watches the rows that are "armed" (the last 5 closes all > 1% above
the line) and close to it, and sends one phone alert when price comes within 1% of the line (the 3rd touch) - India
stocks and indices in NSE hours, US / world indices whenever their market trades. Watch only: the 3rd touch is NOT a
tested buy signal (research: claude/trendline-3rd-touch-test.md - no better than the 50-day average)."""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

K = 5
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "scan", "trendline.json")
INDICES = {  # yahoo: (name, market)
    "^NSEI": ("Nifty 50", "NSE"), "^NSEBANK": ("Nifty Bank", "NSE"), "^BSESN": ("Sensex", "NSE"), "^CNXIT": ("Nifty IT", "NSE"),
    "^CNXAUTO": ("Nifty Auto", "NSE"), "^CNXPHARMA": ("Nifty Pharma", "NSE"), "^CNXFMCG": ("Nifty FMCG", "NSE"), "^CNXMETAL": ("Nifty Metal", "NSE"),
    "^CNXREALTY": ("Nifty Realty", "NSE"), "^CNXENERGY": ("Nifty Energy", "NSE"), "^CNXPSUBANK": ("Nifty PSU Bank", "NSE"),
    "^CNXMEDIA": ("Nifty Media", "NSE"), "^CNXINFRA": ("Nifty Infra", "NSE"), "NIFTY_FIN_SERVICE.NS": ("Nifty Financial Services", "NSE"),
    "^NSEMDCP50": ("Nifty Midcap 50", "NSE"),
    "^GSPC": ("S&P 500", "US"), "^NDX": ("Nasdaq 100", "US"), "^DJI": ("Dow Jones", "US"), "^RUT": ("Russell 2000", "US"),
    "^AXJO": ("ASX 200", "W"), "^FTSE": ("FTSE 100", "W"), "^GDAXI": ("DAX", "W"), "^STOXX50E": ("Euro Stoxx 50", "W"), "^N225": ("Nikkei 225", "W"),
    "^HSI": ("Hang Seng", "W"), "GC=F": ("Gold", "W"), "SI=F": ("Silver", "W"), "CL=F": ("Crude oil", "W"), "BTC-USD": ("Bitcoin", "W"),
}


def line_row(t, h, l, c):
    n = len(c)
    piv = [i for i in range(K, n - K) if l[i] == l[i - K:i + K + 1].min()]
    if len(piv) < 2:
        return None
    a, b = piv[-2], piv[-1]; s = (l[b] - l[a]) / (b - a)
    if s <= 0:
        return None
    line = lambda i: l[b] + s * (i - b)  # noqa: E731
    touches, armed = 2, False
    for i in range(b + 1, n):
        if i >= b + 5 and all(c[k] > line(k) * 1.01 for k in range(i - 5, i)):
            armed = True
        if armed and l[i] <= line(i) * 1.005:
            touches += 1; armed = False
    armed_next = n - 5 > b and all(c[k] > line(k) * 1.01 for k in range(n - 5, n))
    return dict(a_d=t[a], a_l=round(float(l[a]), 4), b_d=t[b], b_l=round(float(l[b]), 4), slope=round(float(s), 5),
                day=t[-1], close=round(float(c[-1]), 4), line=round(float(line(n - 1)), 4), line_next=round(float(line(n)), 4),
                dist=round(float((c[-1] / line(n) - 1) * 100), 2), armed=bool(armed_next), touches=touches, below=bool(c[-1] < line(n - 1)))


def main():
    names = {}
    for s in pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "universe", "nifty500.csv")).Symbol:
        names[s + ".NS"] = (s, "NSE", "stock")
    for y, (nm, mk) in INDICES.items():
        names[y] = (nm, mk, "index")
    tick = list(names); rows = []
    for k in range(0, len(tick), 100):
        D = yf.download(tick[k:k + 100], period="1y", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for y in tick[k:k + 100]:
            try:
                df = D[y].dropna(subset=["Close", "Low"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) < 60:
                continue
            t = [str(x.date()) for x in df.index]
            r = line_row(t, df.High.values, df.Low.values, df.Close.values)
            if r:
                nm, mk, kind = names[y]
                r = dict(y=y, symbol=nm, mk=mk, kind=kind, **r)
                if r["armed"] and r["dist"] <= 3:          # the app's "near the line" list draws this chart on tap
                    g = df.iloc[-160:]; rd = lambda a: [round(float(x), 2) for x in a]  # noqa: E731
                    r["bars"] = dict(t=t[-160:], o=rd(g.Open), h=rd(g.High), l=rd(g.Low), c=rd(g.Close))
                rows.append(r)
    rows.sort(key=lambda r: (not r["armed"], r["dist"]))
    near = [r for r in rows if r["armed"] and r["dist"] <= 3]
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), scanned=len(tick), rising=len(rows),
                   rule="Line through the 2 latest swing lows (5 days each side), rising only. Alert when price comes within 1% of it "
                        "after 5 closes more than 1% above (the 3rd touch). Watch only: tested 2016-26, no better than the 50-day average.",
                   rows=[r for r in rows if r["dist"] <= 8]), open(OUT, "w"), indent=0)
    print("rising lines", len(rows), "armed within 3%:", [(r["symbol"], r["dist"]) for r in near][:30])


if __name__ == "__main__":
    main()
