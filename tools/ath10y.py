"""10-year-base monthly ATH breakouts on NSE (Yahoo full monthly history, ~1996 -> today).

Event = a MONTH whose close is a new all-time closing high, after the previous all-time closing high stood for at least
BASE months (default 120 = 10 years). Two entry styles are compared for the SAME stocks:
  close : the breakout month CLOSES above the old all-time closing high -> buy next month's open
  cross : price trades above the trigger intramonth (the live system's entry) -> buy at the trigger
Outcomes from the entry: return after 12/24/36/60 months, best multiple within 5 years (2x/3x/5x), worst fall within
12 months, and a monthly exit (first monthly close below the 10-month SMA) for comparison.
Base buckets 24-60 / 60-120 / 120+ months are compared on identical rules.
Also lists stocks whose LAST COMPLETED month closed above a >= 10-year-old ATH (and those within 10% of it).
Survivorship: Yahoo only has stocks still listed -> absolute rates are flattered; compare buckets with each other.
Writes data/study10/events.csv, current.csv, near.csv, summary.txt."""
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402

OUT = "data/study10"
MIN_VAL = 1e7          # Rs 1 cr/day average traded value at the breakout (monthly value / 21)
MIN_PX = 20.0


def events_for(sym, m, today):
    m = m.dropna(subset=["Close"])
    m = m[(m.Close > 0) & (m.High > 0)]
    if len(m) < 60:
        return [], None
    # drop the current month if it has not finished
    if m.index[-1].to_period("M") == pd.Timestamp(today).to_period("M") and today.day < 28:
        m = m.iloc[:-1]
    c, h, o = m.Close.values, m.High.values, m.Open.values
    val = (m.Close * m.Volume / 21).rolling(3, min_periods=1).mean().values
    sma10 = m.Close.rolling(10, min_periods=10).mean().values
    n = len(c)
    out, cur = [], None
    best_i = 0                               # index of the ATH CLOSING month so far
    crossed_ref = -1                         # ATH reference already used by a 'cross' event
    def outcome(style, i, e_i, e_px, prev_best, base, trig):
        row = dict(symbol=sym, style=style, month=str(m.index[i].to_period("M")), base_m=int(base),
                   ath_month=str(m.index[prev_best].to_period("M")), trigger=round(trig, 2), entry=round(e_px, 2),
                   close_vs_trig=round((c[i] / trig - 1) * 100, 1))
        for k in (12, 24, 36, 60):
            j = e_i + k - (1 if style == "close" else 0)
            row[f"r{k}"] = round((c[j] / e_px - 1) * 100, 1) if j < n else np.nan
        seg = h[e_i:min(n, e_i + 60)]
        row["best5y"] = round(seg.max() / e_px, 2) if len(seg) else np.nan
        row["full5y"] = bool(e_i + 60 <= n)
        lows = m.Low.values[e_i:min(n, e_i + 12)]
        row["dd12"] = round((lows.min() / e_px - 1) * 100, 1) if len(lows) else np.nan
        xr, xm = np.nan, np.nan
        for j in range(e_i if style == "close" else e_i + 1, n):     # first month-end close below the 10-month SMA
            if np.isfinite(sma10[j]) and c[j] < sma10[j]:
                xr, xm = round((c[j] / e_px - 1) * 100, 1), j - e_i
                break
        row["exit10m_ret"], row["exit10m_months"] = xr, xm
        return row
    for i in range(1, n):
        prev_best = best_i
        base = i - prev_best                  # months since the old ATH closing month
        trig = h[prev_best]                   # HIGH of the old ATH closing month
        ok = base >= 24 and val[i] >= MIN_VAL
        # intramonth cross of the trigger (first time for this ATH reference), whatever the month's close
        if ok and h[i] > trig and crossed_ref != prev_best and max(trig, o[i]) >= MIN_PX:
            out.append(outcome("cross", i, i, max(trig, o[i]), prev_best, base, trig)); crossed_ref = prev_best
        # monthly CLOSE above the old all-time closing high (a new closing ATH after the base) -> buy next month's open
        if ok and c[i] > c[prev_best] and c[i] >= MIN_PX and i + 1 < n:
            out.append(outcome("close", i, i + 1, o[i + 1], prev_best, base, trig))
        if c[i] > c[prev_best]:
            best_i = i
    # current status (last completed month)
    i = n - 1
    pb = int(np.argmax(c[:i])) if i > 0 else 0
    # the old ATH CLOSING month before the last month
    base = i - pb
    cur = dict(symbol=sym, last_month=str(m.index[i].to_period("M")), close=round(c[i], 2), ath_close=round(c[pb], 2),
               ath_month=str(m.index[pb].to_period("M")), trigger=round(h[pb], 2), base_m=int(base),
               vs_trigger=round((c[i] / c[pb] - 1) * 100, 1), value_cr=round(val[i] / 1e7, 2),
               broke_close=bool(c[i] > h[pb]), new_close_ath=bool(c[i] > c[pb]))
    return out, cur


def summary(E):
    lines = []
    E = E.copy()
    E["bucket"] = pd.cut(E.base_m, [23, 59, 119, 10_000], labels=["2-5 y", "5-10 y", "10 y+"])
    for style in ("close", "cross"):
        lines.append(f"\n=== entry: {style} ===")
        for b, g in E[E["style"] == style].groupby("bucket", observed=True):
            f = g[g.full5y]
            lines.append(
                f"{b:6s} events {len(g):4d} | median 1y {g.r12.median():6.1f}% 2y {g.r24.median():6.1f}% 3y {g.r36.median():6.1f}% "
                f"5y {g.r60.median():6.1f}% | up after 1y {100 * (g.r12 > 0).mean():3.0f}% | worst 12m fall median {g.dd12.median():6.1f}% "
                f"| within 5y (n={len(f)}): 2x {100 * (f.best5y >= 2).mean():3.0f}% 3x {100 * (f.best5y >= 3).mean():3.0f}% "
                f"5x {100 * (f.best5y >= 5).mean():3.0f}% | 10-month-SMA exit: median {g.exit10m_ret.median():6.1f}% after "
                f"{g.exit10m_months.median():.0f} m, mean {g.exit10m_ret.mean():6.1f}%")
    return "\n".join(lines)


def main():
    os.makedirs(OUT, exist_ok=True)
    today = date.today()
    u = symbols("NSE")
    tick = [s + ".NS" for s in u.symbol]
    print("symbols", len(tick), flush=True)
    events, cur = [], []
    for a in range(0, len(tick), 100):
        chunk = tick[a:a + 100]
        d = None
        for _ in range(3):
            try:
                d = yf.download(chunk, period="max", interval="1mo", auto_adjust=True, progress=False, group_by="column", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(15)
        if d is None or d.empty:
            continue
        for t in chunk:
            try:
                m = pd.DataFrame({k: d[k][t] for k in ("Open", "High", "Low", "Close", "Volume")})
                ev, c = events_for(t[:-3], m, today)
            except Exception as e:  # noqa: BLE001
                continue
            events += ev
            if c:
                cur.append(c)
        print(a + len(chunk), "done", len(events), "events", flush=True)
        time.sleep(1)
    E = pd.DataFrame(events); C = pd.DataFrame(cur)
    name = dict(zip(u.symbol, u.name)) if "name" in u else {}
    for df in (E, C):
        if len(df):
            df["name"] = df.symbol.map(name)
    E.to_csv(f"{OUT}/events.csv", index=False)
    now = C[(C.base_m >= 120) & C.new_close_ath & (C.close >= 100) & (C.value_cr >= 1)].sort_values("vs_trigger")
    near = C[(C.base_m >= 120) & ~C.new_close_ath & (C.vs_trigger >= -10) & (C.close >= 100) & (C.value_cr >= 1)].sort_values("vs_trigger", ascending=False)
    now.to_csv(f"{OUT}/current.csv", index=False); near.to_csv(f"{OUT}/near.csv", index=False)
    s = summary(E)
    s += "\n\n10y+ events by year (close style): " + E[(E["style"] == "close") & (E.base_m >= 120)].month.str[:4].value_counts().sort_index().to_string().replace("\n", ", ")
    s += f"\n\nLAST COMPLETED MONTH closed above a >=10-year-old all-time closing high (price >= 100, >= Rs 1 cr/day): {len(now)}\n" + now.to_string(index=False)
    s += f"\n\nWithin 10% below the trigger: {len(near)}\n" + near.head(40).to_string(index=False)
    open(f"{OUT}/summary.txt", "w").write(s)
    print(s)


if __name__ == "__main__":
    main()
