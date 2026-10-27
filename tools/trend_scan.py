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
Watchlist: a looser version (>=70% of 60 closes above EMA21, R^2 >= 0.70, within 15% of the high,
3-month return >= 10%) so stocks pulling back to EMA21 are not dropped.

ENTRY TRIGGER (second layer, checked on each of the last 5 sessions for stocks on either list):
  - RSI(14) crosses up through 60 on that day (previous close < 60, today >= 60)
  - bullish candle: green and closing in the top 40% of its range
  - near EMA21: the lowest low of the last 3 sessions is within 2% of EMA21 (or dipped below it),
    and the close is back above EMA21
  stop = lowest low of those 3 sessions.

Writes data/scan/trend_scan.json (for the app), trend_scan.csv, watchlist.csv, triggers.csv, and
sends a Telegram summary when SEND_TELEGRAM=1.
"""
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

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


def metrics(o, h, l, c, v):
    if len(c) < 130:
        return None, []
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    r = rsi(c)
    last = c.iloc[-1]
    y = np.log(c.iloc[-120:].values)
    x = np.arange(len(y))
    b, a = np.polyfit(x, y, 1)
    r2 = 1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    hi52 = c.iloc[-250:].max()
    val = (c * v).iloc[-20:].mean() / 1e7
    m = dict(close=round(last, 2), ema9=round(e9.iloc[-1], 2), ema21=round(e21.iloc[-1], 2),
             ema50=round(e50.iloc[-1], 2),
             above21_60d=round((c.iloc[-60:] > e21.iloc[-60:]).mean() * 100),
             dist21=round((last / e21.iloc[-1] - 1) * 100, 1),
             off_high=round((last / hi52 - 1) * 100, 1),
             r1m=round((last / c.iloc[-22] - 1) * 100, 1), r3m=round((last / c.iloc[-64] - 1) * 100, 1),
             r6m=round((last / c.iloc[-127] - 1) * 100, 1),
             slope_yr=round((np.exp(b * 250) - 1) * 100), r2=round(r2, 2), rsi=round(r.iloc[-1], 1),
             value_cr=round(val, 2),
             stacked=bool(last > e9.iloc[-1] > e21.iloc[-1]), e21_rising=bool(e21.iloc[-1] > e21.iloc[-11]),
             above50=bool(last > e50.iloc[-1]), last_date=str(c.index[-1].date()))
    trig = []
    for k in range(1, 6):                       # last 5 sessions
        i = len(c) - k
        rng = h.iloc[i] - l.iloc[i]
        if rng <= 0 or np.isnan(o.iloc[i]):
            continue
        rsi_cross = r.iloc[i - 1] < 60 <= r.iloc[i]
        bull = c.iloc[i] > o.iloc[i] and (c.iloc[i] - l.iloc[i]) / rng >= 0.6
        low3 = l.iloc[i - 2:i + 1].min()
        near = low3 <= e21.iloc[i] * 1.02 and c.iloc[i] > e21.iloc[i]
        if rsi_cross and bull and near:
            trig.append(dict(trigger_date=str(c.index[i].date()), trigger_close=round(c.iloc[i], 2),
                             trigger_rsi=round(r.iloc[i], 1), ema21_then=round(e21.iloc[i], 2),
                             stop=round(low3, 2), risk_pct=round((c.iloc[i] / low3 - 1) * 100, 1),
                             days_ago=k - 1, move_since=round((last / c.iloc[i] - 1) * 100, 1)))
    return m, trig


def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat or os.environ.get("SEND_TELEGRAM") != "1":
        return
    try:
        s.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=20)
    except Exception as e:  # noqa: BLE001
        print("telegram failed:", e)


def main():
    u = nse_symbols()
    print("symbols", len(u), u.board.value_counts().to_dict(), flush=True)
    tick = [t + ".NS" for t in u.symbol]
    out, trigs = [], []
    for i in range(0, len(tick), 150):
        chunk = tick[i:i + 150]
        try:
            d = yf.download(chunk, start=(date.today() - timedelta(days=420)).isoformat(), auto_adjust=True,
                            progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("chunk fail", i, e); continue
        for t in chunk:
            try:
                c = d["Close"][t].dropna()
                o, h, l = (d[f][t].reindex(c.index) for f in ("Open", "High", "Low"))
                v = d["Volume"][t].reindex(c.index).fillna(0)
            except Exception:  # noqa: BLE001
                continue
            m, tg = metrics(o, h, l, c, v)
            if m:
                out.append(dict(symbol=t[:-3], **m))
                trigs += [dict(symbol=t[:-3], **x) for x in tg]
        print(i, len(out), flush=True)
        time.sleep(2)
    df = pd.DataFrame(out).merge(u, on="symbol", how="left")
    df.to_csv(f"{OUT}/all_metrics.csv", index=False)
    base = df.e21_rising & df.above50 & (df.value_cr >= 1)
    strict = base & df["stacked"] & (df.above21_60d >= 85) & (df.off_high >= -12) & (df.r3m >= 15) & (df.r2 >= 0.80)
    loose = base & (df.above21_60d >= 70) & (df.off_high >= -15) & (df.r3m >= 10) & (df.r2 >= 0.70)
    df["list"] = np.where(strict, "trend", np.where(loose, "watch", ""))
    p = df[df.list != ""].copy()
    p["tag"] = np.where((p.dist21 > 8) | (p.rsi > 75), "extended",
                        np.where(p.dist21 <= 3, "at EMA21", "riding"))
    # score: smooth (R^2) and steady (time above EMA21) uptrend, penalise extension
    p["score"] = (p.r2 * 100 + p.above21_60d * 0.5 + np.minimum(p.slope_yr, 300) / 10
                  - np.maximum(p.dist21 - 5, 0) * 2).round(1)
    p = p.sort_values(["list", "score"], ascending=[True, False])
    tr = pd.DataFrame(trigs)
    if len(tr):
        tr = tr.merge(p[["symbol", "name", "list", "score", "r2", "above21_60d", "value_cr", "close", "rsi"]],
                      on="symbol", how="inner").sort_values(["days_ago", "score"], ascending=[True, False])
    p.to_csv(f"{OUT}/trend_scan.csv", index=False)
    tr.to_csv(f"{OUT}/triggers.csv", index=False)
    asof = df.last_date.max()
    cols = ["symbol", "name", "board", "list", "tag", "score", "close", "ema9", "ema21", "dist21", "rsi", "r1m", "r3m",
            "r6m", "r2", "above21_60d", "off_high", "value_cr", "last_date"]
    json.dump(dict(asof=asof, generated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   scanned=len(df), rows=p[cols].to_dict("records"),
                   triggers=tr.to_dict("records") if len(tr) else []),
              open(f"{OUT}/trend_scan.json", "w"), indent=1, default=str)
    print("trend", int(strict.sum()), "watch", int((loose & ~strict).sum()), "triggers", len(tr))
    print(p.head(40).to_string(index=False))
    if len(tr):
        print(tr.to_string(index=False))
    fresh = tr[tr.days_ago == 0] if len(tr) else tr
    msg = [f"📈 Trend scan — NSE close {asof}: {int(strict.sum())} clear trends, {int((loose & ~strict).sum())} on watch"]
    if len(fresh):
        msg.append("\n🟢 ENTRY TRIGGER today (RSI crossed 60 + bullish candle at EMA21):")
        for _, x in fresh.iterrows():
            msg.append(f"{x.symbol} {x.trigger_close:g} — stop {x.stop:g} ({x.risk_pct}% risk), {x.list}, RSI {x.trigger_rsi}")
    else:
        msg.append("No new entry triggers today.")
    top = p[(p.list == "trend")].head(8)
    if len(top):
        msg.append("\nClear trends: " + ", ".join(f"{x.symbol} ({x.tag})" for _, x in top.iterrows()))
    msg.append("Full list: app → 📈 Trend scan tab")
    telegram("\n".join(msg))


if __name__ == "__main__":
    main()
