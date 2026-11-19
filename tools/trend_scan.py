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
    and the close is back above EMA21 but no more than 6% above it
  - risk to the stop no more than 10%
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
MARKET = "NSE"
VALUE_DIV = 1e7      # traded-value unit used by the filters (>= 1 unit/day); NSE: Rs 1 crore
MIN_PRICE = 30.0     # no penny stocks: every list skips stocks whose last close is below 30 in the local currency
                     # (NSE Rs 100, US $30, ASX A$30) - set 30 Oct 2026 at Amritpal's request
DISP_MULT = 1.0      # converts filter units to the display unit (NSE: Rs cr, US: $ m, ASX: A$ m)
os.makedirs(OUT, exist_ok=True)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def nse_symbols(bse=False):
    """NSE main board + NSE SME (Emerge); with bse=True also BSE-only scrips (17 Nov 2026: liquid, non-penny ones only, picked from
    the latest BSE bhavcopy: close >= Rs 100 and that day's turnover >= Rs 50 lakh, equity codes, ISIN not listed on NSE).
    BSE-only symbols carry Yahoo's .BO suffix (e.g. ABCD.BO) so they never clash with an NSE symbol; the scans' own 20-day
    Rs 1 crore and Rs 100 floors still apply."""
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
                    isin = d[col("ISIN")].astype(str).str.strip() if any("ISIN" in c for c in d.columns) else ""
                    rows.append(pd.DataFrame({"symbol": d[col("SYMBOL")].astype(str).str.strip(),
                                              "name": d[col("NAME")].astype(str).str.strip(), "board": board, "isin": isin}))
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
    u = pd.concat(rows).drop_duplicates("symbol")
    u["ticker"] = u.symbol + ".NS"
    if bse:
        try:
            b = bse_only(set(u["isin"]) - {""})
            if len(b):
                u = pd.concat([u, b])
        except Exception as e:  # noqa: BLE001
            print("BSE list failed:", e, flush=True)
    return u


def bse_only(nse_isins, min_close=100.0, min_turnover=5e6):
    """Liquid, non-penny BSE equity scrips that are not listed on NSE (from the latest BSE bhavcopy)."""
    from datetime import date as _d, timedelta as _td
    for back in range(0, 10):
        d = _d.today() - _td(days=back)
        if d.weekday() >= 5:
            continue
        try:
            r = s.get(f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV", timeout=40,
                      headers={"Referer": "https://www.bseindia.com/"})
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200 or r.content[:5] == b"<!DOC":
            continue
        x = pd.read_csv(io.BytesIO(r.content))
        x = x[x.ISIN.astype(str).str.startswith("INE")]
        code = x.FinInstrmId.astype(str)
        x = x[(code.str.len() == 6) & (code < "700000") & ~x.ISIN.isin(nse_isins)]
        x = x[(pd.to_numeric(x.ClsPric, errors="coerce") >= min_close) & (pd.to_numeric(x.TtlTrfVal, errors="coerce") >= min_turnover)]
        print("BSE bhavcopy", d, "BSE-only liquid:", len(x), flush=True)
        sym = x.TckrSymb.astype(str).str.strip() + ".BO"
        return pd.DataFrame({"symbol": sym.values, "name": x.FinInstrmNm.astype(str).str.strip().values, "board": "BSE",
                             "isin": x.ISIN.astype(str).values, "ticker": sym.values})
    print("no BSE bhavcopy found", flush=True)
    return pd.DataFrame(columns=["symbol", "name", "board", "isin", "ticker"])


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
    val = (c * v).iloc[-20:].mean() / VALUE_DIV
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
        near = low3 <= e21.iloc[i] * 1.02 and e21.iloc[i] < c.iloc[i] <= e21.iloc[i] * 1.06
        risk = c.iloc[i] / low3 - 1
        if rsi_cross and bull and near and risk <= 0.10:
            trig.append(dict(trigger_date=str(c.index[i].date()), trigger_close=round(c.iloc[i], 2),
                             trigger_rsi=round(r.iloc[i], 1), ema21_then=round(e21.iloc[i], 2),
                             stop=round(low3, 2), risk_pct=round((c.iloc[i] / low3 - 1) * 100, 1),
                             days_ago=k - 1, move_since=round((last / c.iloc[i] - 1) * 100, 1)))
    return m, trig


def supertrend(h, l, c, n=10, m=3.0):
    """Supertrend(10,3): direction (+1 up / -1 down) and the trailing line."""
    h, l, c = (np.asarray(x, dtype=float) for x in (h, l, c))
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.empty_like(c); atr[0] = tr[0]
    for i in range(1, len(c)):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / n
    mid = (h + l) / 2
    fu, fl = mid + m * atr, mid - m * atr
    d = np.ones(len(c), dtype=int); line = fl.copy()
    for i in range(1, len(c)):
        ub, lb = mid[i] + m * atr[i], mid[i] - m * atr[i]
        fu[i] = ub if (ub < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb if (lb > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = (-1 if c[i] < fl[i] else 1) if d[i - 1] == 1 else (1 if c[i] > fu[i] else -1)
        line[i] = fl[i] if d[i] == 1 else fu[i]
    return d, line


def early(o, h, l, c, v):
    """EARLY TREND ENTRY (backtested 2017-26 on all NSE stocks incl. delisted: ~22-25%/yr, max DD -26 to -27%,
    10-15 positions at 1% risk; see project doc trend-scan.md):
      signal : EMA9 crosses above EMA21 today with Supertrend(10,3) green, close > EMA50, EMA50 higher than
               10 sessions ago, RSI(14) >= 55,
               >= Rs 1 cr/day traded (20-day avg), >= 120 sessions listed, close within 30% of the 52-week high
      entry  : next session's open;  initial stop = lowest low of the last 5 sessions (skip if > 12% away)
      exit   : Supertrend(10,3) turns red (close below its line) -> sell next open
    Returns the latest signal of the last 60 sessions, followed forward to today (open / stopped / exited)."""
    if len(c) < 130:
        return None
    e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    r = rsi(c)
    val = (c * v).rolling(20).mean() / VALUE_DIV
    hi = c.rolling(250, min_periods=60).max()
    sig = ((e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (c > e50) & (e50 > e50.shift(10)) & (r >= 55)
           & (val >= 1) & (c >= 0.7 * hi))
    sd, line = supertrend(h.values, l.values, c.values)
    sig = sig & (sd == 1)                        # Supertrend already green (else the exit would fire at once)
    sig.iloc[:120] = False
    return follow(o, h, l, c, sig, sd, line, r, val, cap_stop=False)


def follow(o, h, l, c, sig, sd, line, r, val, cap_stop=False, lookback=60):
    """Take the latest signal of the last `lookback` sessions and follow it to today: entry next open, stop = 5-day low
    (cap_stop: never more than 12% below the signal close; else skip if > 12% away), exit when Supertrend turns red."""
    idx = np.where(sig.values[-lookback:])[0]
    if not len(idx):
        return None
    i = len(c) - lookback + idx[-1]
    stop = float(l.iloc[i - 4:i + 1].min())
    if cap_stop:
        stop = max(stop, float(c.iloc[i]) * 0.88)
    rec = dict(signal_date=str(c.index[i].date()), signal_close=round(float(c.iloc[i]), 2), stop=round(stop, 2),
               rsi_signal=round(float(r.iloc[i]), 1), value_cr=round(float(val.iloc[-1]), 2),
               supertrend=round(float(line[-1]), 2), st_up=bool(sd[-1] == 1), close=round(float(c.iloc[-1]), 2))
    if i == len(c) - 1:
        rk = round((c.iloc[i] / stop - 1) * 100, 1)
        rec.update(status="NEW - buy next open" if (cap_stop or rk <= 12) else "NEW but stop > 12% away - skip unless it opens lower",
                   entry=None, days=0, gain_pct=None, risk_pct=rk)
        return rec
    entry = float(o.iloc[i + 1])
    rec.update(entry=round(entry, 2), risk_pct=round((entry / stop - 1) * 100, 1), days=len(c) - 1 - i)
    if entry <= stop or (not cap_stop and entry / stop - 1 > 0.12):
        rec.update(status="skipped (stop too far / gap below stop)", gain_pct=None)
        return rec
    status, exit_px = "open", None
    for j in range(i + 1, len(c)):
        if l.iloc[j] <= stop:
            status, exit_px = f"stopped {c.index[j].date()}", min(float(o.iloc[j]), stop); break
        if sd[j] == -1 and j < len(c) - 1:
            status, exit_px = f"exited {c.index[j + 1].date()} (Supertrend red)", float(o.iloc[j + 1]); break
        if sd[j] == -1:
            status = "EXIT next open (Supertrend turned red)"
    px = exit_px if exit_px is not None else float(c.iloc[-1])
    rec.update(status=status, gain_pct=round((px / entry - 1) * 100, 1),
               R=round((px - entry) / (entry - stop), 2))
    return rec


def base_breakout(o, h, l, c, v):
    """FIRST 52-WEEK-HIGH BREAKOUT AFTER A 6-MONTH BASE (Chartink screen + Amritpal's base idea; backtested 2017-26 on
    all NSE stocks incl. delisted: ~15%/yr, max DD -29%, 2022-26 ~17.6%/yr, 10 positions at 1% risk):
      signal : today's high > highest close of the prior 240 sessions, close > previous close, close > MIN_PRICE (NSE 100, US/ASX 30),
               20-day avg traded value >= Rs 2 cr, the previous 240-day closing high was >= 126 sessions ago,
               Supertrend(10,3) green
      entry  : next open; stop = 5-day low but never more than 12% below the signal close
      exit   : Supertrend(10,3) turns red -> sell next open"""
    if len(c) < 260:
        return None
    r = rsi(c)
    val = (c * v).rolling(20).mean() / VALUE_DIV
    pmax = c.shift(1).rolling(240, min_periods=240).max()
    newhi = (c >= c.rolling(240, min_periods=240).max()).values
    k = np.arange(len(c), dtype=float)
    last = pd.Series(np.where(newhi, k, np.nan), index=c.index).ffill().shift(1)
    age = pd.Series(k, index=c.index) - last
    sd, line = supertrend(h.values, l.values, c.values)
    sig = ((h > pmax) & (c > c.shift(1)) & (c > MIN_PRICE) & (val >= 2) & (age >= 126) & (sd == 1))
    return follow(o, h, l, c, sig, sd, line, r, val, cap_stop=True)


def tight_base(o, h, l, c, v, lookback=5):
    """TIGHT BASE BREAKOUT (Amritpal, 19 Nov 2026; WATCH-ONLY - research tools/research/gurjar_momentum.py: as a system ~16-19%/yr,
    worst fall about -30%, below 9/21; the <= 8% version held up best in 2022-26):
      trend : close > SMA50, SMA20 > SMA50, RSI(14) > 50, 20-day average volume > 500,000 shares
      base  : the last 10 sessions within 12% high-to-low, the base came back to within 2% of the 20 SMA, and its average volume is
              below the 50-day average (volume drying up)
      break : a close above the base high on >= 1.5x the 20-day average volume (tested: buy next open, stop = 5-day low,
              exit when Supertrend turns red)
    Returns the latest breakout of the last `lookback` sessions, else a base still forming today (buy-stop level = base high)."""
    if len(c) < 70:
        return None
    s20, s50 = c.rolling(20).mean(), c.rolling(50).mean()
    vs20, vs50 = v.rolling(20).mean(), v.rolling(50).mean()
    r = rsi(c); n = len(c)

    def trend(i):
        return bool(c.iloc[i] > s50.iloc[i] and s20.iloc[i] > s50.iloc[i] and r.iloc[i] > 50 and vs20.iloc[i] > 500000)

    def base(i):
        hi, lo = float(h.iloc[i - 9:i + 1].max()), float(l.iloc[i - 9:i + 1].min())
        ok = (hi / lo - 1 <= 0.12 and lo <= s20.iloc[i] * 1.02 and v.iloc[i - 9:i + 1].mean() < vs50.iloc[i])
        return ok, hi, lo

    def rec(i, hi, lo, status, j=None):
        stop = float(l.iloc[(j if j is not None else n - 1) - 4:(j if j is not None else n - 1) + 1].min())
        last = float(c.iloc[-1])
        return dict(status=status, base_from=str(c.index[i - 9].date()), base_to=str(c.index[i].date()), base_hi=round(hi, 2),
                    base_lo=round(lo, 2), range_pct=round((hi / lo - 1) * 100, 1), tight8=bool(hi / lo - 1 <= 0.08),
                    vol_dry=round(float(v.iloc[i - 9:i + 1].mean() / vs50.iloc[i]), 2),
                    breakout_date=str(c.index[j].date()) if j is not None else None,
                    breakout_vol=round(float(v.iloc[j] / vs20.iloc[j]), 1) if j is not None else None,
                    vol_needed=round(float(1.5 * vs20.iloc[-1])), trigger=round(hi, 2), stop=round(stop, 2),
                    risk_pct=round((max(last, hi) / stop - 1) * 100, 1), dist_pct=round((hi / last - 1) * 100, 1),
                    close=round(last, 2), days_ago=(n - 1 - j) if j is not None else None)

    for k in range(lookback):
        j = n - 1 - k
        if j < 60:
            break
        ok, hi, lo = base(j - 1)
        if ok and trend(j) and c.iloc[j] > hi and v.iloc[j] >= 1.5 * vs20.iloc[j]:
            st = "BREAKOUT today - buy next open" if k == 0 else f"broke out {k} session{'s' if k > 1 else ''} ago"
            return rec(j - 1, hi, lo, st, j)
    ok, hi, lo = base(n - 1)
    if ok and trend(n - 1) and c.iloc[-1] <= hi:
        return rec(n - 1, hi, lo, "base forming")
    return None

def export_charts(frames, syms, tbs=None):
    """Compact daily chart files for the phone app: data/scan/charts/<SYM>.json (last ~160 sessions with
    EMA 9/21/50, Supertrend(10,3) line/direction and RSI(14))."""
    import shutil
    cdir = f"{OUT}/charts"
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(cdir, exist_ok=True)
    for sym in syms:
        if sym not in frames:
            continue
        o, h, l, c = frames[sym]
        e9, e21, e50 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
        sd, line = supertrend(h.values, l.values, c.values)
        r = rsi(c)
        n = min(160, len(c))
        rd = lambda a: [None if not np.isfinite(x) else round(float(x), 2) for x in np.asarray(a)[-n:]]  # noqa: E731
        b = (tbs or {}).get(sym)
        tb = dict(f=b["base_from"], to=b["base_to"], hi=b["base_hi"], lo=b["base_lo"], stop=b["stop"],
                  bo=b["breakout_date"] if isinstance(b["breakout_date"], str) else None) if b else None   # NaN breaks the browser's JSON
        json.dump(dict(t=[str(x.date()) for x in c.index[-n:]], o=rd(o), h=rd(h), l=rd(l), c=rd(c), e9=rd(e9),
                       e21=rd(e21), e50=rd(e50), st=rd(line), sd=[int(x) for x in sd[-n:]], rsi=rd(r), tb=tb),
                  open(f"{cdir}/{sym}.json", "w"), separators=(",", ":"), allow_nan=False)


def telegram(text):
    """Evening alert to WhatsApp and/or Telegram (tools/notify.py), only on scheduled runs (SEND_TELEGRAM=1)."""
    if os.environ.get("SEND_TELEGRAM") != "1":
        return
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from notify import send
    send(text)


def main():
    global MARKET, VALUE_DIV, DISP_MULT, OUT, MIN_PRICE
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from global_universe import MARKETS, symbols
    MARKET = sys.argv[1] if len(sys.argv) > 1 else "NSE"
    cfg = MARKETS[MARKET]
    VALUE_DIV, DISP_MULT = cfg["min_value"], cfg["min_value"] / cfg["value_unit"]
    MIN_PRICE = {"NSE": 100.0, "US": 30.0, "ASX": 30.0, "UK": 100.0}[MARKET]   # UK in pence (= GBP 1)
    if MARKET != "NSE":
        OUT = f"data/scan/{MARKET.lower()}"
    os.makedirs(OUT, exist_ok=True)
    u = nse_symbols(bse=True) if MARKET == "NSE" else symbols(MARKET)
    if MARKET == "NSE":                                  # 17 Nov 2026: SME / BSE-only symbols, for the plan and the app (chips, links)
        json.dump({r.symbol: r.board for r in u.itertuples() if r.board != "main"}, open(f"{OUT}/boards.json", "w"))
    if "ticker" not in u:
        u["ticker"] = u.symbol + ".NS"
    print(MARKET, "symbols", len(u), u.board.value_counts().to_dict(), flush=True)
    tick = list(u.ticker)
    tmap = dict(zip(u.ticker, u.symbol))
    out, trigs, earl, frames, closes, close_day, bases = [], [], [], {}, {}, "", []
    for i in range(0, len(tick), 150):
        chunk = tick[i:i + 150]
        try:
            d = yf.download(chunk, start=(date.today() - timedelta(days=800)).isoformat(), auto_adjust=False,
                            progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("chunk fail", i, e); continue
        for t in chunk:
            try:
                from session import drop_partial
                c = drop_partial(d["Close"][t].dropna())
                o, h, l = (d[f][t].reindex(c.index) for f in ("Open", "High", "Low"))
                v = d["Volume"][t].reindex(c.index).fillna(0)
                from adjust import fix_gaps
                o, h, l, c, v = fix_gaps(o, h, l, c, v)
            except Exception:  # noqa: BLE001
                continue
            if len(c) >= 2:                                # every stock's close, for the app's portfolio view
                closes[tmap[t]] = [round(float(c.iloc[-1]), 2), round(float(c.iloc[-2]), 2)]
                close_day = max(close_day, str(c.index[-1].date()))
            if not len(c) or c.iloc[-1] < MIN_PRICE:      # penny-stock floor for every list
                continue
            m, tg = metrics(o, h, l, c, v)
            frames[tmap[t]] = (o.iloc[-260:], h.iloc[-260:], l.iloc[-260:], c.iloc[-260:])
            try:
                ea = early(o, h, l, c, v)
            except Exception as e:  # noqa: BLE001
                ea = None
            if ea:
                earl.append(dict(symbol=tmap[t], setup="EMA 9/21 cross", **ea))
            try:
                bo = base_breakout(o, h, l, c, v)
            except Exception:  # noqa: BLE001
                bo = None
            if bo:
                earl.append(dict(symbol=tmap[t], setup="52w-high base breakout", **bo))
            if MARKET == "NSE":
                try:
                    tbx = tight_base(o, h, l, c, v)
                except Exception:  # noqa: BLE001
                    tbx = None
                if tbx:
                    bases.append(dict(symbol=tmap[t], **tbx))
            if m:
                out.append(dict(symbol=tmap[t], **m))
                trigs += [dict(symbol=tmap[t], **x) for x in tg]
        print(i, len(out), flush=True)
        time.sleep(2)
    if MARKET == "NSE" and closes:
        json.dump(dict(asof=close_day or str(date.today()), prices=closes), open(f"{OUT}/nse_close.json", "w"), separators=(",", ":"))
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
    asof_all = df.last_date.max()
    if len(tr):
        tr["days_ago"] = [int(np.busday_count(t, asof_all)) for t in tr.trigger_date]
        tr = tr[tr.days_ago <= 4]
        tr = tr.merge(p[["symbol", "name", "list", "score", "r2", "above21_60d", "value_cr", "close", "rsi"]],
                      on="symbol", how="inner").sort_values(["days_ago", "score"], ascending=[True, False])
    # traded value in the market's display unit (NSE Rs cr/day, US $ m/day, ASX A$ m/day)
    p["value_cr"] = (p.value_cr * DISP_MULT).round(2)
    if len(tr):
        tr["value_cr"] = (tr.value_cr * DISP_MULT).round(2)
    p.to_csv(f"{OUT}/trend_scan.csv", index=False)
    tr.to_csv(f"{OUT}/triggers.csv", index=False)
    E = pd.DataFrame(earl)
    if len(E):
        E = E.merge(u[["symbol", "name", "board"]], on="symbol", how="left")
        E["value_cr"] = (E.value_cr * DISP_MULT).round(2)
        E["order"] = np.select([E.status.str.startswith("NEW"), E.status.str.startswith("EXIT"), E.status == "open"],
                               [0, 1, 2], 3)
        E = E.sort_values(["order", "value_cr"], ascending=[True, False]).drop(columns="order")
        E.to_csv(f"{OUT}/early.csv", index=False)
    asof = df.last_date.max()
    # company-size bucket by rank of 20-day traded value among all scanned stocks (proxy for market-cap rank)
    rk = df.set_index("symbol").value_cr.rank(ascending=False, method="first")
    cuts = {"NSE": [0, 100, 250, 500, 1e9], "US": [0, 500, 1500, 3000, 1e9], "ASX": [0, 100, 300, 600, 1e9], "UK": [0, 100, 200, 300, 1e9]}[MARKET]
    size = pd.cut(rk, cuts, labels=["Large", "Mid", "Small", "Micro"]).astype(str).to_dict()
    p["size"] = p.symbol.map(size)
    if len(E):
        E["size"] = E.symbol.map(size)
    if len(tr):
        tr["size"] = tr.symbol.map(size)
    chart_syms = set(p.symbol) | (set(tr.symbol) if len(tr) else set()) | \
        (set(E[E.status.str.startswith(("NEW", "open", "EXIT"))].symbol) if len(E) else set())
    # 19 Nov 2026 (Amritpal): market breadth for the traffic light, the 20 > 50 > 100 > 200 SMA stack, 3-month strength for every stock.
    # Breadth = EMA 9/21 cross-ups vs cross-downs summed over the last 10 sessions across all scanned stocks (as data/research/red_light.json).
    xu, xd, a50, a200, R3, STACK = {}, {}, [], [], {}, []
    for sym, (fo, fh, fl, fc) in frames.items():
        if len(fc) < 120:
            continue
        e9, e21 = fc.ewm(span=9, adjust=False).mean(), fc.ewm(span=21, adjust=False).mean()
        up = e9 > e21; pu = up.shift(1)
        cu, cd = (up & (pu == False)).iloc[-30:], ((~up) & (pu == True)).iloc[-30:]   # noqa: E712
        for dt, v in cu.items():
            xu[dt] = xu.get(dt, 0) + int(v)
        for dt, v in cd.items():
            xd[dt] = xd.get(dt, 0) + int(v)
        sm = {n: fc.rolling(n).mean() for n in (20, 50, 100, 200)}
        a50.append(bool(fc.iloc[-1] > sm[50].iloc[-1]))
        if np.isfinite(sm[200].iloc[-1]):
            a200.append(bool(fc.iloc[-1] > sm[200].iloc[-1]))
            if (fc.iloc[-1] > sm[20].iloc[-1] > sm[50].iloc[-1] > sm[100].iloc[-1] > sm[200].iloc[-1]
                    and all(sm[n].iloc[-1] > sm[n].iloc[-1 - k] for n, k in ((20, 5), (50, 10), (100, 10), (200, 20)))):
                STACK.append(sym)
        if len(fc) > 64:
            R3[sym] = round(float(fc.iloc[-1] / fc.iloc[-64] - 1) * 100, 1)
    dts = sorted(xu)[-20:]
    bu, bd = pd.Series(xu).sort_index(), pd.Series(xd).sort_index()
    b10, s10 = bu.rolling(10).sum(), bd.rolling(10).sum()
    BREADTH = dict(buys10=int(b10.iloc[-1]), sells10=int(s10.iloc[-1]), p50=round(float(np.mean(a50)) * 100, 1) if a50 else None,
                   p200=round(float(np.mean(a200)) * 100, 1) if a200 else None, stocks=len(a50),
                   hist=[dict(d=str(pd.Timestamp(k).date()), b=int(b10[k]), s=int(s10[k])) for k in dts if np.isfinite(b10[k])]) if len(bu) else {}
    print("breadth", {k: v for k, v in BREADTH.items() if k != "hist"}, "stack", len(STACK))
    B = pd.DataFrame(bases)
    if len(B):
        B = B.merge(u[["symbol", "name", "board"]], on="symbol", how="left")
        B["size"] = B.symbol.map(size)
        B["value_cr"] = B.symbol.map(df.set_index("symbol").value_cr * DISP_MULT).round(2)
        B["order"] = np.where(B.status.str.startswith("BREAKOUT"), 0, np.where(B.status == "base forming", 1, 2))
        B = B.sort_values(["order", "dist_pct", "days_ago"]).drop(columns="order")
        chart_syms = chart_syms | set(B.symbol)
    tbs = {r["symbol"]: r for r in B.to_dict("records")} if len(B) else {}
    if MARKET == "NSE":             # TradingView watchlist (File > Import list) for the Tight bases tab
        tvs = lambda x: ("BSE:" + x[:-3]) if x.endswith(".BO") else "NSE:" + x.replace("&", "_").replace("-", "_")  # noqa: E731
        live = set(E[E.status.str.startswith("NEW") | (E.status == "open")].symbol) if len(E) else set()
        parts = []
        if len(B):
            for title, m in (("Tight base breakouts", ~(B.status == "base forming")),
                             ("Tight base forming + 9/21", (B.status == "base forming") & B.symbol.isin(live)),
                             ("Tight base forming", (B.status == "base forming") & ~B.symbol.isin(live))):
                if m.any():
                    parts += ["###" + title] + [tvs(x) for x in B[m].symbol]
        open(f"{OUT}/tight_bases_tradingview.txt", "w").write(",".join(parts))
    export_charts(frames, chart_syms, tbs)
    spark = {k: [round(float(x), 2) for x in frames[k][3].iloc[-60:].values] for k in chart_syms if k in frames}
    p["spark"] = p.symbol.map(spark)
    if len(E):
        E["spark"] = E.symbol.map(spark)
    if len(B):
        B["spark"] = B.symbol.map(spark)
    cols = ["symbol", "name", "board", "size", "list", "tag", "score", "close", "ema9", "ema21", "dist21", "rsi", "r1m",
            "r3m", "r6m", "r2", "above21_60d", "off_high", "value_cr", "last_date", "spark"]
    def clean(o):   # strict JSON for the phone app: NaN/inf -> null
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (float, np.floating)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return o
    json.dump(clean(dict(market=MARKET, market_label=cfg["label"], currency=cfg["currency"], value_label=cfg["value_label"],
                         asof=asof, generated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                         scanned=len(df), rows=p[cols].to_dict("records"),
                         triggers=tr.to_dict("records") if len(tr) else [],
                         early=E.to_dict("records") if len(E) else [],
                         bases=B.to_dict("records") if len(B) else [],
                         breadth=BREADTH, stack=sorted(STACK), r3m=R3)),
              open(f"{OUT}/trend_scan.json", "w"), indent=1, default=str, allow_nan=False)
    print("tight bases", len(B), (B.status.value_counts().to_dict() if len(B) else {}))
    print("trend", int(strict.sum()), "watch", int((loose & ~strict).sum()), "triggers", len(tr))
    print(p.head(40).to_string(index=False))
    if len(tr):
        print(tr.to_string(index=False))
    fresh = tr[tr.days_ago == 0] if len(tr) else tr
    msg = [f"📈 Trend scan — {cfg['label']} close {asof}: {int(strict.sum())} clear trends, {int((loose & ~strict).sum())} on watch"]
    if len(E):
        new = E[E.status.str.startswith("NEW - buy")].head(16)
        ex = E[E.status.str.startswith("EXIT")]
        msg.append(f"\n🚀 TREND ENTRIES today ({len(new)}) — EMA 9/21 cross or first 52w high after a 6-month base, Supertrend green, buy next open, "
                   "stop = 5-day low, exit when Supertrend(10,3) turns red:")
        msg += [f"{x.symbol} [{'cross' if x.setup.startswith('EMA') else 'base breakout'}] {x.signal_close:g} — stop {x.stop:g} "
                f"({x.risk_pct}% risk), {x.value_cr:g} {cfg['value_label']}/day" for _, x in new.iterrows()] or ["none"]
        if len(ex):
            msg.append("\n🔻 Supertrend turned red (exit next open): " + ", ".join(ex.symbol.head(20)))
    if len(fresh):
        msg.append("\n🟢 Pullback trigger today (RSI crossed 60 + bullish candle at EMA21 — weaker in backtests):")
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
