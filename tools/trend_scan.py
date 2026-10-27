"""Clean-trend scanner for all NSE stocks (main board + SME), daily data from Yahoo.

"Clear trend" (like GCSL in Oct 2026, riding the 9/21 EMAs):
  - close > EMA9 > EMA21, EMA21 rising over the last 10 sessions, close above EMA50
  - at least 85% of the last 60 closes above EMA21
  - within 12% of the 52-week high, 3-month return >= 15%
  - log-price straight-line fit over 120 sessions with R^2 >= 0.80 (a smooth staircase, not one spike)
  - average traded value over 20 sessions >= Rs 1 crore
Each pass is tagged:
  extended   : > 8% above EMA21 or RSI(14) > 75     -> wait for a pullback
  pullback   : within 3% of EMA21 and RSI 45-65     -> nearest to an entry
  riding     : everything else
Writes data/scan/trend_scan.csv (passes, best score first) and data/scan/all_metrics.csv.
"""
import io
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

OUT = "data/scan"
os.makedirs(OUT, exist_ok=True)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def nse_symbols():
    rows = []
    for u, board in (("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "main"),
                     ("https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv", "SME")):
        for _ in range(3):
            try:
                r = s.get(u, timeout=40)
                if r.status_code == 200:
                    d = pd.read_csv(io.BytesIO(r.content))
                    d.columns = [c.strip().upper() for c in d.columns]
                    col = lambda key: next(c for c in d.columns if key in c)  # noqa: E731
                    rows.append(pd.DataFrame({"symbol": d[col("SYMBOL")].astype(str).str.strip(),
                                              "name": d[col("NAME")].astype(str).str.strip(), "board": board}))
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
    return pd.concat(rows).drop_duplicates("symbol")


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def metrics(c, v):
    if len(c) < 130:
        return None
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    last = c.iloc[-1]
    y = np.log(c.iloc[-120:].values)
    x = np.arange(len(y))
    b, a = np.polyfit(x, y, 1)
    r2 = 1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    hi52 = c.iloc[-250:].max()
    rs = rsi(c).iloc[-1]
    val = (c * v).iloc[-20:].mean() / 1e7
    return dict(close=round(last, 2), ema9=round(e9.iloc[-1], 2), ema21=round(e21.iloc[-1], 2),
                ema50=round(e50.iloc[-1], 2),
                above21_60d=round((c.iloc[-60:] > e21.iloc[-60:]).mean() * 100),
                dist21=round((last / e21.iloc[-1] - 1) * 100, 1),
                off_high=round((last / hi52 - 1) * 100, 1),
                r1m=round((last / c.iloc[-22] - 1) * 100, 1), r3m=round((last / c.iloc[-64] - 1) * 100, 1),
                r6m=round((last / c.iloc[-127] - 1) * 100, 1),
                slope_yr=round((np.exp(b * 250) - 1) * 100), r2=round(r2, 2), rsi=round(rs, 1), value_cr=round(val, 2),
                stacked=bool(last > e9.iloc[-1] > e21.iloc[-1]), e21_rising=bool(e21.iloc[-1] > e21.iloc[-11]),
                above50=bool(last > e50.iloc[-1]), last_date=c.index[-1].date())


def main():
    u = nse_symbols()
    print("symbols", len(u), u.board.value_counts().to_dict(), flush=True)
    tick = [t + ".NS" for t in u.symbol]
    out = []
    for i in range(0, len(tick), 150):
        chunk = tick[i:i + 150]
        try:
            d = yf.download(chunk, start=(date.today() - timedelta(days=420)).isoformat(), auto_adjust=True,
                            progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("chunk fail", i, e); continue
        for t in chunk:
            try:
                c = d["Close"][t].dropna(); v = d["Volume"][t].reindex(c.index).fillna(0)
            except Exception:  # noqa: BLE001
                continue
            m = metrics(c, v)
            if m:
                out.append(dict(symbol=t[:-3], **m))
        print(i, len(out), flush=True)
        time.sleep(2)
    df = pd.DataFrame(out).merge(u, on="symbol", how="left")
    df.to_csv(f"{OUT}/all_metrics.csv", index=False)
    p = df[df["stacked"] & df.e21_rising & df.above50 & (df.above21_60d >= 85) & (df.off_high >= -12) & (df.r3m >= 15)
           & (df.r2 >= 0.80) & (df.value_cr >= 1)].copy()
    p["tag"] = np.where((p.dist21 > 8) | (p.rsi > 75), "extended",
                        np.where((p.dist21 <= 3) & p.rsi.between(45, 65), "pullback", "riding"))
    # score: smooth (R^2) and steady (time above EMA21) uptrend, penalise extension
    p["score"] = (p.r2 * 100 + p.above21_60d * 0.5 + np.minimum(p.slope_yr, 300) / 10 - np.maximum(p.dist21 - 5, 0) * 2).round(1)
    p = p.sort_values("score", ascending=False)
    p.to_csv(f"{OUT}/trend_scan.csv", index=False)
    print("passes", len(p), p.tag.value_counts().to_dict())
    print(p.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
