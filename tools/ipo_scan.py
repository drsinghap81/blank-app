"""IPO all-time-high cup scanner (NSE mainboard, listed in the last 3 years).

System (backtest 2017 - Oct 2026 on every NSE IPO since 2016, incl. delisted; 10 stocks equal weight, costs 0.4% round trip):
  setup   : the stock's all-time high SINCE LISTING (highest intraday high) was set at least 20 trading days ago and the
            stock has since closed at least 15% below it (the cup)
  signal  : a daily CLOSE above that all-time high (yesterday's close was at or below it) -> buy at the next open
  filters : listed <= 36 months ago, last close >= Rs 100, >= Rs 2 cr/day traded (20-day average)
  exit    : weekly CLOSE below the 10-week SMA -> sell at the next open
  results : IPOs listed <= 3 years, price >= 100: ~12%/yr, worst fall -27% (Nifty 11.2%, -38%); all IPO ages 14-16%, -24 to -30%.
            Buying every IPO at the listing-day close: median -2% after 12 months. Listing-PRICE cross: whipsaws (win 36%).
  size    : risk % of capital to the 10-week SMA (app input, default 1%), max 20% of capital per stock
Lists written to data/scan/ipo.json:
  breakouts : signal in the last 15 trading days, trade still open
  near      : cup in place and the last close within 5% below the post-listing high
  tracked   : every signal of the last 12 months followed with the exit rule (open / exit next open / exited)
Charts: data/scan/ipo_charts/SYM.json (daily bars since listing; weekly bars with the 10-week SMA).
Project note: claude/ipo-breakouts.md.
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "data/scan"
CH = f"{OUT}/ipo_charts"
MINVAL = 2e7            # Rs 2 cr/day
MIN_CLOSE = 100.0       # no penny stocks
MAX_AGE_M = 36          # listed within the last 3 years
BASE_DAYS = 20          # post-listing high at least 20 trading days old
DEPTH = 0.15            # cup at least 15% deep (closing basis)
NEAR = 0.05
SMA_W = 10              # exit: weekly close below the 10-week SMA


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o.date())
    return o


def weekly(x):
    wk = x.index.to_period("W-FRI")
    W = pd.DataFrame({"o": x.Open.groupby(wk).first(), "h": x.High.groupby(wk).max(), "l": x.Low.groupby(wk).min(),
                      "c": x.Close.groupby(wk).last()})
    W["sma"] = W.c.rolling(SMA_W, min_periods=SMA_W).mean()
    return W


def analyse(sym, x, today, lookback_days=380):
    """x: daily OHLCV since listing (DatetimeIndex). Returns (events, near_row or None, chart dict or None)."""
    x = x.dropna(subset=["Close"])
    x = x[(x.Close > 0) & (x.High > 0)]
    n = len(x)
    if n < BASE_DAYS + 5:
        return [], None, None
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    v = x.Volume.to_numpy(float)
    val20 = pd.Series(c * v).rolling(20, min_periods=5).mean().to_numpy()
    W = weekly(x)
    wk = x.index.to_period("W-FRI")
    last_complete = W.index[-1] if x.index[-1].weekday() == 4 or (today - x.index[-1].date()).days >= 3 else W.index[-2]
    Wc = W.loc[:last_complete]
    events = []
    start = pd.Timestamp(today) - pd.Timedelta(days=lookback_days)
    i = BASE_DAYS
    while i < n:
        hi_i = int(np.argmax(h[:i])); lvl = h[hi_i]
        base_ok = (i - 1 - hi_i) >= BASE_DAYS and c[hi_i:i].min() <= lvl * (1 - DEPTH)
        if not (base_ok and c[i] > lvl and c[i - 1] <= lvl):
            i += 1
            continue
        sig_dt = x.index[i]
        entry_i = i + 1
        depth = c[hi_i:i].min() / lvl - 1
        if entry_i >= n:          # signal at today's close: buy next open
            status, entry, entry_dt, exit_dt, exit_px = "buy next open", None, None, None, None
        else:
            entry, entry_dt = o[entry_i], x.index[entry_i]
            after = Wc[Wc.index >= wk[entry_i]]
            brk = after[after.c < after.sma]
            if len(brk):
                ex_w = brk.index[0]
                nxt = x[wk > ex_w]
                status, exit_px, exit_dt = ("exited", float(nxt.Open.iloc[0]), nxt.index[0]) if len(nxt) else ("exit next open", None, None)
            else:
                status, exit_px, exit_dt = "open", None, None
        if sig_dt >= start and val20[i] >= MINVAL and c[i] >= MIN_CLOSE:
            last = float(c[-1])
            sma_now = float(W.sma.loc[last_complete]) if np.isfinite(W.sma.loc[last_complete]) else None
            ref = entry if entry else last
            events.append(dict(symbol=sym, signal_date=sig_dt, date=entry_dt or sig_dt, entry=entry, ath=float(lvl),
                               ath_date=x.index[hi_i], base_days=int(i - 1 - hi_i), depth=float(depth), status=status,
                               exit_date=exit_dt, exit_price=exit_px, close=last,
                               ret=((exit_px or last) / ref - 1) if entry else 0.0,
                               peak=float(c[entry_i:].max() / entry - 1) if entry else 0.0,
                               weeks=int(((exit_dt or x.index[-1]) - (entry_dt or sig_dt)).days / 7), sma10=sma_now,
                               value_cr=float(val20[i]) / 1e7))
        if status in ("open", "exit next open", "buy next open"):
            break
        i = int(np.searchsorted(x.index, exit_dt)) if exit_dt is not None else n   # one position at a time per stock
    # near: cup in place, last close within 5% below the post-listing high, not crossed
    near = None
    hi_i = int(np.argmax(h)); lvl = h[hi_i]; last = float(c[-1])
    if (n - 1 - hi_i) >= BASE_DAYS and c[hi_i:].min() <= lvl * (1 - DEPTH) and last >= (1 - NEAR) * lvl and last <= lvl \
            and val20[-1] >= MINVAL and last >= MIN_CLOSE:
        sma_now = float(W.sma.loc[last_complete]) if np.isfinite(W.sma.loc[last_complete]) else None
        near = dict(symbol=sym, ath=float(lvl), ath_date=x.index[hi_i], close=last, gap_pct=(lvl / last - 1) * 100,
                    base_days=int(n - 1 - hi_i), depth=float(c[hi_i:].min() / lvl - 1), sma10=sma_now,
                    value_cr=float(val20[-1]) / 1e7)
    Wt = W.tail(160)
    chart = dict(d=dict(t=[str(t.date()) for t in x.index], o=np.round(o, 2).tolist(), h=np.round(h, 2).tolist(),
                        l=np.round(l, 2).tolist(), c=np.round(c, 2).tolist()),
                 w=dict(t=[str(p.end_time.date()) for p in Wt.index], o=Wt.o.round(2).tolist(), h=Wt.h.round(2).tolist(),
                        l=Wt.l.round(2).tolist(), c=Wt.c.round(2).tolist(), sma=Wt.sma.round(2).tolist()),
                 ath=float(lvl), ath_date=str(x.index[hi_i].date()), listed=str(x.index[0].date()))
    return events, near, chart


def listings():
    """NSE EQUITY_L.csv with DATE OF LISTING; mainboard EQ/BE only."""
    from trend_scan import s as sess   # requests session with NSE headers
    for _ in range(3):
        try:
            r = sess.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=40)
            if r.status_code == 200:
                d = pd.read_csv(io.BytesIO(r.content))
                d.columns = [k.strip().upper() for k in d.columns]
                col = lambda key: next(k for k in d.columns if key in k)  # noqa: E731
                out = pd.DataFrame({"symbol": d[col("SYMBOL")].astype(str).str.strip(), "name": d[col("NAME")].astype(str).str.strip(),
                                    "series": d[col("SERIES")].astype(str).str.strip(),
                                    "listed": pd.to_datetime(d[col("DATE OF LISTING")].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")})
                return out[out.series.isin(["EQ", "BE"])].dropna(subset=["listed"])
        except Exception:  # noqa: BLE001
            time.sleep(3)
    raise SystemExit("could not download the NSE equity list")


def main():
    import yfinance as yf
    from trend_scan import telegram
    os.makedirs(CH, exist_ok=True)
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    L = listings()
    L = L[L.listed >= pd.Timestamp(today) - pd.DateOffset(months=MAX_AGE_M)]
    name = dict(zip(L.symbol, L.name)); listed = dict(zip(L.symbol, L.listed))
    tick = [s + ".NS" for s in L.symbol]
    print("recent listings", len(tick), flush=True)
    events, near, charts = [], [], {}
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            sym = t[:-3]
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                if not len(x) or x.index.max() < pd.Timestamp(today) - pd.Timedelta(days=10):
                    continue
                x = x[x.index >= listed[sym] - pd.Timedelta(days=3)]
                ev, nr, ch = analyse(sym, x, today)
            except Exception as e:  # noqa: BLE001
                print("fail", sym, e); continue
            events += ev
            if nr:
                near.append(nr)
            if ev or nr:
                charts[sym] = ch
        print(a + len(chunk), "done;", len(events), "signals,", len(near), "near", flush=True)
        time.sleep(1)
    E = pd.DataFrame(events); N = pd.DataFrame(near)
    for df in (E, N):
        if len(df):
            df["name"] = df.symbol.map(name).fillna("")
            df["listed"] = df.symbol.map(listed)
            df["age_months"] = ((pd.Timestamp(today) - df.listed).dt.days / 30.44).round().astype(int)
    recent = pd.Timestamp(today) - pd.Timedelta(days=21)
    if len(E):
        E["date"] = pd.to_datetime(E.date)
        E = E.sort_values("date").groupby("symbol").tail(1)
        E["order"] = np.select([E.status == "buy next open", E.status == "exit next open", E.status == "open"], [0, 1, 2], 3)
        E = E.sort_values(["order", "date"], ascending=[True, False]).drop(columns="order")
        brk = E[E.status.isin(["open", "buy next open"]) & (pd.to_datetime(E.signal_date) >= recent)]
    else:
        brk = E
    if len(N):
        N = N.sort_values("gap_pct")
    keep = (set(E.symbol) if len(E) else set()) | (set(N.symbol) if len(N) else set())
    for f in os.listdir(CH):
        if f[:-5] not in keep:
            os.remove(os.path.join(CH, f))
    for s_, ch in charts.items():
        if s_ in keep:
            json.dump(clean(ch), open(f"{CH}/{s_}.json", "w"), separators=(",", ":"), allow_nan=False)
    out = dict(asof=str(today), generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), scanned=len(tick),
               rules=dict(max_age_months=MAX_AGE_M, base_days=BASE_DAYS, depth_pct=DEPTH * 100, near_pct=NEAR * 100,
                          min_value_cr=MINVAL / 1e7, min_close=MIN_CLOSE, exit_sma_weeks=SMA_W),
               breakouts=clean(brk.to_dict("records")) if len(brk) else [],
               near=clean(N.to_dict("records")) if len(N) else [],
               tracked=clean(E.to_dict("records")) if len(E) else [])
    json.dump(out, open(f"{OUT}/ipo.json", "w"), indent=0, allow_nan=False)
    print("breakouts", len(brk), "near", len(N), "tracked", len(E))
    new = E[E.status == "buy next open"] if len(E) else E
    ex = E[E.status == "exit next open"] if len(E) else E
    msg = [f"IPO ATH cup scan {today}"]
    msg += [f"Buy next open: {r.symbol} closed above its post-listing high {r.ath:.2f} (cup {r.depth * 100:.0f}%)" for r in new.itertuples()] \
        or ["No new IPO breakouts today."]
    msg += [f"Sell next open (weekly close < 10-wk SMA): {', '.join(ex.symbol)}"] if len(ex) else []
    msg += [f"Near post-listing high (<= 5%): {', '.join(N.symbol.head(12))}"] if len(N) else []
    if len(new) or len(ex):
        telegram("\n".join(msg))


if __name__ == "__main__":
    main()
