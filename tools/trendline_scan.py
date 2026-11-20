"""Trend line scan (17 Nov 2026): for every Nifty 500 stock, Indian sector index, world index and a few commodities /
crypto, draw the line through the 2 latest swing lows (right to left: the newest swing low and the one before it;
swing low = lowest low with 3 days each side). The line must join both wick lows with no candle between them
cutting below it and no close below it since the 2nd low (the latest such pair). Rising lines only.

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
import nse_bhav; nse_bhav.install()  # noqa: E402,E702  20 Nov 2026 (Amritpal: always use bhavcopy): recent NSE sessions from NSE's bhavcopy

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


def best_line(l, c, m=None, K=3, tol=0.001, rising=True):
    """17 Nov 2026: the latest pair of swing lows (lowest low with K bars each side) that a trader would join: the line
    runs through both wick lows, no candle between them pokes below it, and no close after the 2nd low is under it.
    Rising only. Returns (a, b, slope) or None."""
    l = np.asarray(l, float); c = np.asarray(c, float); m = len(c) if m is None else m
    piv = [i for i in range(K, m - K) if l[i] == l[i - K:i + K + 1].min()]
    for j in range(len(piv) - 1, -1, -1):
        b = piv[j]
        if b < m - 250:
            break
        after = np.arange(b + 1, m)
        for k in range(j - 1, -1, -1):
            a = piv[k]
            if b - a < 5:
                continue
            if b - a > 250:
                break
            if rising and l[a] >= l[b]:
                continue
            s = (l[b] - l[a]) / (b - a)
            if (l[a + 1:b] < (l[a] + s * (np.arange(a + 1, b) - a)) * (1 - tol)).any():
                continue
            if len(after) and (c[b + 1:m] < l[b] + s * (after - b)).any():
                continue
            return int(a), int(b), float(s)
    return None


def line_row(t, h, l, c):
    n = len(c); l = np.asarray(l, float); c = np.asarray(c, float)
    r = best_line(l, c)
    if not r:
        return None
    a, b, s = r
    line = lambda i: l[b] + s * (i - b)  # noqa: E731
    touches, armed = 2, False
    for i in range(b + 1, n):
        if i >= b + 5 and all(c[k] > line(k) * 1.01 for k in range(i - 5, i)):
            armed = True
        if armed and l[i] <= line(i) * 1.01:
            touches += 1; armed = False
    armed_next = n - 5 > b and all(c[k] > line(k) * 1.01 for k in range(n - 5, n))
    return dict(a_d=t[a], a_l=round(float(l[a]), 4), b_d=t[b], b_l=round(float(l[b]), 4), slope=round(float(s), 5),
                day=t[-1], close=round(float(c[-1]), 4), line=round(float(line(n - 1)), 4), line_next=round(float(line(n)), 4),
                dist=round(float((c[-1] / line(n) - 1) * 100), 2), armed=bool(armed_next), touches=touches, below=bool(c[-1] < line(n - 1)))


def res_row(t, h, l, c):
    """Mirror of line_row for swing highs: the latest pair of swing-high wicks that no candle pokes above, no close above
    it since the 2nd high. Any slope (falling = downtrend line, rising = channel top). Touch = high within 1% of it."""
    n = len(c); h = np.asarray(h, float); c = np.asarray(c, float)
    r = best_line(-h, -c, rising=False)
    if not r:
        return None
    a, b, s = r; s = -s
    line = lambda i: h[b] + s * (i - b)  # noqa: E731
    touches, armed = 2, False
    for i in range(b + 1, n):
        if i >= b + 5 and all(c[k] < line(k) * 0.99 for k in range(i - 5, i)):
            armed = True
        if armed and h[i] >= line(i) * 0.99:
            touches += 1; armed = False
    armed_next = n - 5 > b and all(c[k] < line(k) * 0.99 for k in range(n - 5, n))
    if line(n) <= 0:
        return None
    return dict(side="res", a_d=t[a], a_l=round(float(h[a]), 4), b_d=t[b], b_l=round(float(h[b]), 4), slope=round(float(s), 5),
                day=t[-1], close=round(float(c[-1]), 4), line=round(float(line(n - 1)), 4), line_next=round(float(line(n)), 4),
                dist=round(float((line(n) / c[-1] - 1) * 100), 2), armed=bool(armed_next), touches=touches, above=bool(c[-1] > line(n - 1)))


def level_rows(t, h, l, c, K=5, PROM=3.0):
    """17 Nov 2026: horizontal levels from the latest PROMINENT swing. Swing high = highest wick with K days each side,
    prominent = price fell at least PROM x ATR(14) below it afterwards (a real turn, not a pause); still unbroken (no close
    above it since). Drawn flat to the right as resistance. Swing low = the mirror (support). Alert when price comes back
    within 1% after 5 closes more than 1% away."""
    n = len(c); h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float); out = []
    pc = np.r_[c[0], c[:-1]]; atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14, min_periods=5).mean().values
    for side, x in (("res", h), ("sup", l)):
        piv = [i for i in range(K, n - K) if (x[i] == x[i - K:i + K + 1].max() if side == "res" else x[i] == x[i - K:i + K + 1].min())]
        b = None
        for i in reversed(piv):
            if not np.isfinite(atr[i]):
                break
            if (c[i + 1:] > x[i]).any() if side == "res" else (c[i + 1:] < x[i]).any():
                continue                               # broken: price closed through it
            move = (x[i] - l[i + 1:].min()) if side == "res" else (h[i + 1:].max() - x[i])
            if move >= PROM * atr[i]:
                b = i; break
        if b is None:
            continue
        v = x[b]
        away = (lambda k: c[k] < v * 0.99) if side == "res" else (lambda k: c[k] > v * 1.01)
        hit = (lambda i: h[i] >= v * 0.99) if side == "res" else (lambda i: l[i] <= v * 1.01)
        touches, armed = 1, False
        for i in range(b + 1, n):
            if i >= b + 5 and all(away(k) for k in range(i - 5, i)):
                armed = True
            if armed and hit(i):
                touches += 1; armed = False
        dist = (v / c[-1] - 1) * 100 if side == "res" else (c[-1] / v - 1) * 100
        out.append(dict(side=side, flat=True, a_d=t[b], a_l=round(float(v), 4), b_d=t[b], b_l=round(float(v), 4), slope=0.0, day=t[-1],
                        close=round(float(c[-1]), 4), line=round(float(v), 4), line_next=round(float(v), 4), dist=round(float(dist), 2),
                        armed=bool(n - 5 > b and all(away(k) for k in range(n - 5, n))), touches=touches))
    return out


TV = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^BSESN": "BSE:SENSEX", "^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO",
      "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXMETAL": "NSE:CNXMETAL", "^CNXREALTY": "NSE:CNXREALTY",
      "^CNXENERGY": "NSE:CNXENERGY", "^CNXPSUBANK": "NSE:CNXPSUBANK", "^CNXMEDIA": "NSE:CNXMEDIA", "^CNXINFRA": "NSE:CNXINFRA",
      "NIFTY_FIN_SERVICE.NS": "NSE:CNXFINANCE", "^NSEMDCP50": "NSE:NIFTYMIDCAP50", "^GSPC": "SP:SPX", "^NDX": "NASDAQ:NDX", "^DJI": "DJ:DJI",
      "^RUT": "TVC:RUT", "^AXJO": "ASX:XJO", "^FTSE": "TVC:UKX", "^GDAXI": "XETR:DAX", "^STOXX50E": "TVC:SX5E", "^N225": "TVC:NI225",
      "^HSI": "TVC:HSI", "GC=F": "COMEX:GC1!", "SI=F": "COMEX:SI1!", "CL=F": "NYMEX:CL1!", "BTC-USD": "BITSTAMP:BTCUSD"}


def tv_sym(y):
    return TV.get(y) or ("NSE:" + y[:-3].replace("&", "_").replace("-", "_") if y.endswith(".NS") else y)


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
            for r in [line_row(t, df.High.values, df.Low.values, df.Close.values), res_row(t, df.High.values, df.Low.values, df.Close.values)] \
                    + level_rows(t, df.High.values, df.Low.values, df.Close.values):
                if not r:
                    continue
                nm, mk, kind = names[y]
                r = dict(y=y, tv=tv_sym(y), symbol=nm, mk=mk, kind=kind, **({"side": "sup"} | r))
                if r["armed"] and r["dist"] <= 3:          # the app's "near the line" list draws this chart on tap
                    g = df.iloc[-260:]; rd = lambda a: [round(float(x), 2) for x in a]  # noqa: E731
                    r["bars"] = dict(t=t[-260:], o=rd(g.Open), h=rd(g.High), l=rd(g.Low), c=rd(g.Close))
                rows.append(r)
    rows.sort(key=lambda r: (not r["armed"], r["dist"]))
    near = [(r["symbol"], r["side"] + ("-level" if r.get("flat") else ""), r["dist"]) for r in rows if r["armed"] and r["dist"] <= 3]
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), scanned=len(tick), lines=len(rows),
                   rule="Support: line through the 2 latest swing lows that no candle cuts (3 days each side), rising only. Resistance: the same "
                        "through the 2 latest swing highs (any slope). Alert when price comes within 1% of a line after 5 closes more than 1% "
                        "away (the 3rd touch). Levels: the latest swing high / swing low drawn flat to the right, alert within 1%. Watch only: the support touch was tested 2016-26, no better than the 50-day average.",
                   rows=[r for r in rows if r["dist"] <= 8]), open(OUT, "w"), indent=0)
    # TradingView watchlist (Watchlist menu > Import list): everything within 3% of a line, in four sections
    sec = [("Support lines", lambda r: r["side"] == "sup" and not r.get("flat")), ("Resistance lines", lambda r: r["side"] == "res" and not r.get("flat")),
           ("Swing low levels", lambda r: r["side"] == "sup" and r.get("flat")), ("Swing high levels", lambda r: r["side"] == "res" and r.get("flat"))]
    parts = []
    for name, f in sec:
        tv = list(dict.fromkeys(r["tv"] for r in rows if r["armed"] and r["dist"] <= 3 and f(r)))
        if tv:
            parts += ["###" + name] + tv
    open(os.path.join(os.path.dirname(OUT), "trendline_tradingview.txt"), "w").write(",".join(parts))
    print("lines", len(rows), "armed within 3%:", near[:40])


if __name__ == "__main__":
    main()
