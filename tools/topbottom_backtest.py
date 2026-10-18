#!/usr/bin/env python3
"""
Top Bottom System — standalone backtester
=========================================

Captures the Top Bottom logic decoded and validated in this project:

  * Tops / bottoms = 1-day turning points of the DAILY CLOSE line
    (a top is a close higher than the closes either side; confirmed when the
    next, lower close prints — bottoms mirror this).
  * LIVE rules (default, matches the published daily calls):
      - Buy-stop  at previous top    + buffer  (e.g. +25 pts Bank Nifty)
      - Sell-stop at previous bottom - buffer
      - 1% stop on the entry day (1.5% for stocks)
      - From the next day: stop = opposite system point (prev bottom - buffer for a
        long), never wider than the max stop (2% indices / 3% stocks)
      - Stop to breakeven once the trade is in profit by 2% (3% stocks)
      - A system-point exit reverses the position; a max/breakeven/day stop exit
        goes flat ("trade closed without system")
      - Each top/bottom triggers only once ("awaiting new bottom")
      - Gap of more than 2% beyond the order level -> exit only, no new trade
  * SHEET rules (to reproduce the course spreadsheets): signal when the CLOSE
    crosses the last top/bottom, booked at the system-point price, always in the
    market. NOTE: not tradable live — the price is only known after the close.

Data
----
  --csv FILE        CSV with Date, Open, High, Low, Close (any extra columns ignored)
  --yahoo SYMBOL    download daily data with yfinance (e.g. ^NSEBANK, ^NSEI, RELIANCE.NS)
  --nse SYMBOL      build near-month FUTURES from NSE F&O bhavcopies (BANKNIFTY, NIFTY,
                    or a stock symbol). Needs internet access to archives.nseindia.com
                    (works from India; slow — one file per trading day; cached locally).

Examples
--------
  python topbottom_backtest.py --csv data/banknifty_fut_near_2007-2022.csv --lot 20
  python topbottom_backtest.py --yahoo ^NSEBANK --start 2015-01-01
  python topbottom_backtest.py --csv bnf.csv --mode sheet --start 2017-01-01 --end 2017-12-31
  python topbottom_backtest.py --csv bnf.csv --compare my_live_log.csv
  python topbottom_backtest.py --yahoo TATASTEEL.NS --stock          # 3% / 1.5% / 3% rules

Outputs (in --out folder, default ./tb_out): trades.csv, monthly.csv, yearly.csv,
plus a printed summary and the NEXT-DAY levels in the WhatsApp-call format.

Requirements: pandas, numpy (+ yfinance for --yahoo, requests for --nse)
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


# ============================================================================
# 1. Parameters
# ============================================================================
@dataclass
class Params:
    mode: str = "live"          # "live" or "sheet"
    buffer_pts: float = 25.0    # live: points beyond the top/bottom for the stop order
    buffer_pct: float | None = None  # live: use % buffer instead of points (e.g. 0.07)
    day_sl_pct: float = 1.0     # stop on the entry day (1.5 for stocks)
    max_sl_pct: float = 2.0     # maximum stop from entry (3 for stocks)
    be_pct: float = 2.0         # move stop to breakeven after this profit (3 for stocks)
    gap_pct: float = 2.0        # gap beyond order level > this -> exit only
    use_once: bool = True       # each top/bottom can trigger only once
    long_only: bool = False
    swing_pct: float = 0.0      # optional glitch filter (0 = pure 1-day turns, as validated)
    cost_pts: float = 0.0       # round-trip cost per trade, in points
    lot: float = 1.0            # multiply points by lot size for rupee P&L
    start_flat_on: str | None = None  # live: be flat from this date and wait for a FRESH signal
                                      # (levels already traded stay used, e.g. "awaiting new top")

    @classmethod
    def for_stocks(cls, **kw):
        return cls(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, **kw)


# ============================================================================
# 2. Tops & bottoms on the closing line (causal)
# ============================================================================
def confirmed_swings(close: np.ndarray, swing_pct: float = 0.0):
    """last_top[i] / last_bot[i] = latest top / bottom KNOWN at the end of bar i.
    With swing_pct=0 every 1-day turn counts. Returns (last_top, last_bot, pivots)
    where pivots = [(confirm_idx, pivot_idx, 'T'|'B', value), ...]."""
    n = len(close)
    th = swing_pct / 100.0
    last_top = np.full(n, np.nan)
    last_bot = np.full(n, np.nan)
    pivots = []
    hi, hi_i, lo, lo_i = close[0], 0, close[0], 0
    mode = 0  # 0 undecided, +1 looking for a top, -1 looking for a bottom
    t = b = np.nan
    for i in range(1, n):
        c = close[i]
        if mode >= 0 and c > hi:
            hi, hi_i = c, i
        if mode <= 0 and c < lo:
            lo, lo_i = c, i
        if mode >= 0 and c < hi and (hi - c) / hi >= th and hi_i < i:
            t = hi
            pivots.append((i, hi_i, "T", hi))
            mode = -1
            seg = close[hi_i + 1: i + 1]
            j = int(np.argmin(seg))
            lo, lo_i = seg[j], hi_i + 1 + j
        elif mode <= 0 and c > lo and (c - lo) / lo >= th and lo_i < i:
            b = lo
            pivots.append((i, lo_i, "B", lo))
            mode = 1
            seg = close[lo_i + 1: i + 1]
            j = int(np.argmax(seg))
            hi, hi_i = seg[j], lo_i + 1 + j
        last_top[i], last_bot[i] = t, b
    return last_top, last_bot, pivots


# ============================================================================
# 3a. LIVE engine — resting stop orders, exactly as the calls are traded
# ============================================================================
def run_live(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    T, B, _ = confirmed_swings(c, p.swing_pct)
    idx, n = df.index, len(c)
    used_T = used_B = np.nan
    pos, ent, ei, be_on = 0, 0.0, 0, False
    trades: list[dict] = []

    def buf(x):
        return x * p.buffer_pct / 100 if p.buffer_pct is not None else p.buffer_pts

    def close_pos(i, px, why):
        nonlocal pos
        trades[-1].update(ExitDate=idx[i], Exit=round(px, 2), Reason=why)
        pos = 0

    def open_pos(i, side, px, why):
        nonlocal pos, ent, ei, be_on
        pos, ent, ei, be_on = side, px, i, False
        trades.append(dict(EntryDate=idx[i], Side="BUY" if side > 0 else "SELL",
                           Entry=round(px, 2), Signal=why))

    def day_stop_check(i, side, px):
        stop = px * (1 - side * p.day_sl_pct / 100)
        if (side > 0 and c[i] <= stop) or (side < 0 and c[i] >= stop):
            close_pos(i, stop, "Entry-day SL")

    sf = pd.Timestamp(p.start_flat_on) if p.start_flat_on else None
    flat_done = False
    for i in range(1, n):
        if sf is not None and not flat_done and idx[i] >= sf:
            flat_done = True
            if pos != 0:          # drop the position the system was holding: we start flat
                trades.pop()
                pos = 0
            # a top/bottom that price has ALREADY broken is spent: wait for a fresh one
            for lvl_arr, is_top in ((T, True), (B, False)):
                v = lvl_arr[i - 1]
                if np.isnan(v):
                    continue
                k = int(np.argmax(lvl_arr[:i] == v))  # bar on which this level was confirmed
                seg_h, seg_l = h[k + 1:i], l[k + 1:i]
                if is_top and len(seg_h) and seg_h.max() >= v + buf(v):
                    used_T = v
                if not is_top and len(seg_l) and seg_l.min() <= v - buf(v):
                    used_B = v
        top, bot = T[i - 1], B[i - 1]
        buy_lvl = top + buf(top) if (not np.isnan(top) and (not p.use_once or top != used_T)) else np.nan
        sell_lvl = bot - buf(bot) if (not np.isnan(bot) and (not p.use_once or bot != used_B)) else np.nan

        # ---- manage an open position (stops set on previous days) ----
        if pos != 0 and i > ei:
            prot = ent * (1 - pos * p.max_sl_pct / 100)
            if pos > 0 and not np.isnan(bot):
                prot = max(prot, bot - buf(bot))
            if pos < 0 and not np.isnan(top):
                prot = min(prot, top + buf(top))
            if be_on:
                prot = max(prot, ent) if pos > 0 else min(prot, ent)
            if (pos > 0 and l[i] <= prot) or (pos < 0 and h[i] >= prot):
                px = min(o[i], prot) if pos > 0 else max(o[i], prot)
                is_sys = (pos > 0 and not np.isnan(sell_lvl) and abs(prot - sell_lvl) < 1e-6) or \
                         (pos < 0 and not np.isnan(buy_lvl) and abs(prot - buy_lvl) < 1e-6)
                side = pos
                reason = "System point" if is_sys else ("Breakeven" if be_on else "Max SL")
                close_pos(i, px, reason + (" (gap)" if px != prot else ""))
                if is_sys and not (p.long_only and side > 0):
                    lvl = sell_lvl if side > 0 else buy_lvl
                    if side > 0:
                        used_B = bot
                    else:
                        used_T = top
                    gapped = ((side > 0 and o[i] < lvl) or (side < 0 and o[i] > lvl)) and \
                        abs(o[i] - lvl) / lvl * 100 > p.gap_pct
                    if not gapped:
                        open_pos(i, -side, px, "Reverse at system point")
                        day_stop_check(i, -side, px)
                continue
            fav = (h[i] - ent) / ent * 100 if pos > 0 else (ent - l[i]) / ent * 100
            if p.be_pct and fav >= p.be_pct:
                be_on = True
            continue
        if pos != 0:
            continue

        # ---- flat: resting buy-stop / sell-stop orders ----
        go_l = not np.isnan(buy_lvl) and h[i] >= buy_lvl
        go_s = (not p.long_only) and not np.isnan(sell_lvl) and l[i] <= sell_lvl
        if go_l and go_s:  # both levels hit the same day: take the one nearer the open
            go_l = abs(o[i] - buy_lvl) <= abs(o[i] - sell_lvl)
            go_s = not go_l
        if go_l:
            used_T = top
            if o[i] > buy_lvl and (o[i] - buy_lvl) / buy_lvl * 100 > p.gap_pct:
                continue  # gap rule: no new position
            px = max(o[i], buy_lvl)
            open_pos(i, 1, px, "Buy above prev top")
            day_stop_check(i, 1, px)
        elif go_s:
            used_B = bot
            if o[i] < sell_lvl and (sell_lvl - o[i]) / sell_lvl * 100 > p.gap_pct:
                continue
            px = min(o[i], sell_lvl)
            open_pos(i, -1, px, "Sell below prev bottom")
            day_stop_check(i, -1, px)
    out = _finish(trades, c, idx, p)
    out.attrs["used_T"], out.attrs["used_B"] = used_T, used_B
    out.attrs["flat_from"] = p.start_flat_on
    return out


# ============================================================================
# 3b. SHEET engine — reproduces the course spreadsheets (close-confirmed,
#     booked at the system point, always in the market). Not tradable live.
# ============================================================================
def run_sheet(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    c = df["Close"].to_numpy(float)
    T, B, _ = confirmed_swings(c, p.swing_pct)
    idx = df.index
    trades, pos = [], 0
    for i in range(1, len(c)):
        top, bot = T[i - 1], B[i - 1]
        if pos >= 0 and not np.isnan(bot) and c[i] < bot and not (p.long_only and pos == 0 and False):
            if pos > 0:
                trades[-1].update(ExitDate=idx[i], Exit=round(bot, 2), Reason="System point")
            if not p.long_only:
                trades.append(dict(EntryDate=idx[i], Side="SELL", Entry=round(bot, 2), Signal="Close below bottom"))
                pos = -1
            else:
                pos = 0
        elif pos <= 0 and not np.isnan(top) and c[i] > top:
            if pos < 0:
                trades[-1].update(ExitDate=idx[i], Exit=round(top, 2), Reason="System point")
            trades.append(dict(EntryDate=idx[i], Side="BUY", Entry=round(top, 2), Signal="Close above top"))
            pos = 1
    return _finish(trades, c, idx, p)


def _finish(trades, c, idx, p: Params) -> pd.DataFrame:
    t = pd.DataFrame(trades)
    if t.empty:
        return t
    for col in ("ExitDate", "Exit", "Reason"):
        if col not in t:
            t[col] = np.nan
    t["Open"] = t["Exit"].isna()
    t["Exit"] = t["Exit"].fillna(round(c[-1], 2))
    t["ExitDate"] = t["ExitDate"].fillna(idx[-1])
    t["Reason"] = t["Reason"].fillna("Open position")
    sign = np.where(t["Side"] == "BUY", 1, -1)
    t["Points"] = ((t["Exit"] - t["Entry"]) * sign - p.cost_pts).round(2)
    t["Pct"] = (t["Points"] / t["Entry"] * 100).round(3)
    t["PnL"] = (t["Points"] * p.lot).round(0)
    return t


# ============================================================================
# 4. Reporting
# ============================================================================
def summary(t: pd.DataFrame, p: Params) -> dict:
    if t.empty:
        return {"Trades": 0}
    pts = t["Points"]
    wins, losses = pts[pts > 0], pts[pts < 0]
    eq = pts.cumsum()
    streak = mx = 0
    for v in pts:
        streak = streak + 1 if v < 0 else 0
        mx = max(mx, streak)
    return {
        "Trades": len(t), "Winners": len(wins), "Losers": len(losses),
        "No P/L": int((pts == 0).sum()),
        "Hit rate %": round(100 * len(wins) / len(t), 1),
        "Total points": round(pts.sum(), 1),
        "Total P&L (x lot)": round(pts.sum() * p.lot),
        "Avg win": round(wins.mean(), 1) if len(wins) else 0,
        "Avg loss": round(losses.mean(), 1) if len(losses) else 0,
        "Profit factor": round(wins.sum() / -losses.sum(), 2) if len(losses) else float("inf"),
        "Max loss (pts)": round(pts.min(), 1), "Max profit (pts)": round(pts.max(), 1),
        "Max drawdown (pts)": round((eq - eq.cummax()).min(), 1),
        "Max consecutive losses": mx,
    }


def monthly_table(t: pd.DataFrame) -> pd.DataFrame:
    """Points booked in the month of ENTRY (as the course sheets do)."""
    d = pd.to_datetime(t["EntryDate"])
    m = t.groupby([d.dt.year, d.dt.month])["Points"].sum().unstack(fill_value=0).round(1)
    m.columns = [pd.Timestamp(2000, k, 1).strftime("%b") for k in m.columns]
    m["Total"] = m.sum(axis=1)
    m.index.name = "Year"
    return m


def next_orders(df: pd.DataFrame, t: pd.DataFrame, p: Params) -> dict:
    """Position-aware orders for the NEXT session under the live rules."""
    c = df["Close"].to_numpy(float)
    T, B, _ = confirmed_swings(c, p.swing_pct)
    top, bot, last = T[-1], B[-1], c[-1]
    bt = (top * p.buffer_pct / 100) if p.buffer_pct is not None else p.buffer_pts
    bb = (bot * p.buffer_pct / 100) if p.buffer_pct is not None else p.buffer_pts
    out = dict(date=df.index[-1], close=last, prev_top=top, prev_bottom=bot, position="FLAT", orders=[],
               lines={})  # numeric levels for charting: name -> price
    used_top = used_bot = False
    if p.use_once and "used_T" in t.attrs:
        used_top = (not np.isnan(top)) and t.attrs["used_T"] == top
        used_bot = (not np.isnan(bot)) and t.attrs["used_B"] == bot
    elif p.use_once and not t.empty:
        tol = 1e-6
        used_top = any(abs(e - (top + bt)) < tol for e in t.loc[t.Side == "BUY", "Entry"]) or \
            any(abs(x - (top + bt)) < tol for x in t.loc[t.Side == "SELL", "Exit"])
        used_bot = any(abs(e - (bot - bb)) < tol for e in t.loc[t.Side == "SELL", "Entry"]) or \
            any(abs(x - (bot - bb)) < tol for x in t.loc[t.Side == "BUY", "Exit"])
    is_open = not t.empty and bool(t.iloc[-1]["Open"])
    if p.start_flat_on and pd.Timestamp(p.start_flat_on) > df.index[-1]:
        # paper account starts flat on the next session: re-run as if flat from now
        is_open = False
        tmp = run_live(pd.concat([df, df.iloc[[-1]].set_axis([pd.Timestamp(p.start_flat_on)])]), p)
        used_top = (not np.isnan(top)) and tmp.attrs.get("used_T") == top
        used_bot = (not np.isnan(bot)) and tmp.attrs.get("used_B") == bot
    if is_open:
        r = t.iloc[-1]
        side = 1 if r.Side == "BUY" else -1
        ent = float(r.Entry)
        since = df.loc[pd.Timestamp(r.EntryDate):]
        fav = ((since.High.max() - ent) / ent * 100) if side > 0 else ((ent - since.Low.min()) / ent * 100)
        be_on = bool(p.be_pct) and fav >= p.be_pct
        maxsl = ent * (1 - side * p.max_sl_pct / 100)
        sysl = (bot - bb) if side > 0 else (top + bt)
        stop = max(maxsl, sysl) if side > 0 else min(maxsl, sysl)
        kind = "system point (exit & REVERSE)" if stop == sysl else f"max {p.max_sl_pct:g}% SL (exit only)"
        if be_on:
            stop2 = max(stop, ent) if side > 0 else min(stop, ent)
            if stop2 != stop:
                stop, kind = stop2, "breakeven SL (exit only)"
        out["position"] = f"{'LONG' if side > 0 else 'SHORT'} from {ent:,.2f} ({pd.Timestamp(r.EntryDate).date()})"
        out["lines"]["Entry"] = ent
        out["lines"]["Stop-loss" + (" (reverse)" if stop == sysl else "")] = stop
        out["open_pnl"] = round((last - ent) * side, 2)
        out["breakeven_active"] = be_on
        word = "Sell" if side > 0 else "Buy"
        out["orders"].append(f"HOLD {'long' if side > 0 else 'short'}. Stop: {word} {'below' if side > 0 else 'above'} "
                             f"{stop:,.0f} — {kind}")
        if kind.endswith("(exit only)") and not (side > 0 and p.long_only):
            # the opposite entry order still rests at the system point
            lvl, used = ((bot - bb), used_bot) if side > 0 else ((top + bt), used_top)
            if not used:
                out["lines"]["Sell entry" if side > 0 else "Buy entry"] = lvl
                out["orders"].append(f"Separate {'sell' if side > 0 else 'buy'}-stop entry at {lvl:,.0f} "
                                     f"(Prev {'Bottom' if side > 0 else 'Top'}); if it triggers keep "
                                     f"{p.day_sl_pct:g}% SL at {lvl * (1 + side * p.day_sl_pct / 100):,.0f}")
        if not be_on:
            be_px = ent * (1 + side * p.be_pct / 100)
            out["lines"]["Breakeven trigger"] = be_px
            out["orders"].append(f"Move SL to breakeven ({ent:,.0f}) once price reaches {be_px:,.0f}")
    else:
        if np.isnan(top) or used_top:
            out["orders"].append("No Buy trade as awaiting new top")
        else:
            bl = top + bt
            out["lines"]["Buy above"] = bl
            out["lines"]["Buy SL (1st day)"] = bl * (1 - p.day_sl_pct / 100)
            out["orders"].append(f"Buy above +{bt:.4g} @ {bl:,.0f} (Prev Top {top:,.2f}); if triggers keep "
                                 f"{p.day_sl_pct:g}% SL at {bl * (1 - p.day_sl_pct / 100):,.0f}")
        if p.long_only:
            out["orders"].append("(long only — no sell trades)")
        elif np.isnan(bot) or used_bot:
            out["orders"].append("No Sell trade as awaiting new bottom")
        else:
            sl = bot - bb
            out["lines"]["Sell below"] = sl
            out["lines"]["Sell SL (1st day)"] = sl * (1 + p.day_sl_pct / 100)
            out["orders"].append(f"Sell below -{bb:.4g} @ {sl:,.0f} (Prev Bottom {bot:,.2f}); if triggers keep "
                                 f"{p.day_sl_pct:g}% SL at {sl * (1 + p.day_sl_pct / 100):,.0f}")
    out["orders"].append(f"Gap > {p.gap_pct:g}% beyond a level at the open: exit only, no new trade "
                         "(let the market settle)")
    return out


def next_day_levels(df: pd.DataFrame, t: pd.DataFrame, p: Params, name: str) -> str:
    """Next-session orders, in the same style as the WhatsApp calls."""
    o = next_orders(df, t, p)
    lines = [f"TOP BOTTOM LEVELS for the session after {o['date'].date()}",
             f"  {name} - Closing Price {o['close']:,.2f}",
             f"  Position: {o['position']}"]
    lines += [f"    {x}" for x in o["orders"]]
    return "\n".join(lines)


def compare_with_log(t: pd.DataFrame, log_csv: str, tol_days: int = 1) -> pd.DataFrame:
    """Match a real/live trade log (columns: Date, Side[B/S/BUY/SELL], Entry, Exit)."""
    ref = pd.read_csv(log_csv)
    ref.columns = [x.strip().title() for x in ref.columns]
    ds = ref["Date"].astype(str)
    iso = ds.str.match(r"^\d{4}-\d{2}-\d{2}").all()
    ref["Date"] = pd.to_datetime(ds, format="ISO8601") if iso else pd.to_datetime(ds, format="mixed", dayfirst=True)
    ref["Side"] = ref["Side"].astype(str).str.upper().str[0].map({"B": "BUY", "S": "SELL"})
    mine = t.copy()
    mine["EntryDate"] = pd.to_datetime(mine["EntryDate"])
    rows = []
    for _, r in ref.iterrows():
        m = mine[(mine.Side == r.Side) & ((mine.EntryDate - r.Date).abs() <= pd.Timedelta(days=tol_days))]
        k = m.iloc[0] if len(m) else None
        rows.append(dict(LogDate=r.Date.date(), Side=r.Side, LogEntry=r.get("Entry"), LogExit=r.get("Exit"),
                         BT_Date=None if k is None else k.EntryDate.date(),
                         BT_Entry=None if k is None else k.Entry, BT_Exit=None if k is None else k.Exit,
                         Match="yes" if k is not None else "NO"))
    return pd.DataFrame(rows)


# ============================================================================
# 5. Data loaders
# ============================================================================
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [x.strip().title() for x in df.columns]
    date_col = next(c for c in df.columns if c.lower() in ("date", "datetime", "timestamp"))
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=False)
    df = df.set_index(date_col).sort_index()
    return df[["Open", "High", "Low", "Close"]].astype(float).dropna()


def load_yahoo(symbol: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[df["Close"] > 0]


def load_nse_futures(symbol: str, start: str, end: str, cache_dir: str = "nse_cache") -> pd.DataFrame:
    """Near-month futures OHLC built from NSE F&O bhavcopies (old archive format,
    valid up to mid-2024). Rolls on expiry day to the next contract."""
    import requests
    os.makedirs(cache_dir, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"})
    rows = []
    days = pd.bdate_range(start, end)
    for k, d in enumerate(days, 1):
        mon = d.strftime("%b").upper()
        fn = f"fo{d:%d}{mon}{d.year}bhav.csv.zip"
        cache = os.path.join(cache_dir, fn)
        if not os.path.exists(cache):
            url = f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/{fn}"
            try:
                r = s.get(url, timeout=30)
            except Exception:
                continue
            if r.status_code != 200 or r.content[:2] != b"PK":
                open(cache + ".missing", "w").close()
                continue
            open(cache, "wb").write(r.content)
            time.sleep(0.15)
        if not os.path.exists(cache):
            continue
        z = zipfile.ZipFile(cache)
        f = pd.read_csv(z.open(z.namelist()[0]))
        f.columns = [x.strip() for x in f.columns]
        f = f[f.INSTRUMENT.isin(["FUTIDX", "FUTSTK"]) & (f.SYMBOL == symbol)]
        if len(f):
            f = f.assign(Date=d)
            rows.append(f[["Date", "EXPIRY_DT", "OPEN", "HIGH", "LOW", "CLOSE"]])
        if k % 100 == 0:
            print(f"  ...{k}/{len(days)} days", file=sys.stderr)
    raw = pd.concat(rows)
    raw["Exp"] = pd.to_datetime(raw.EXPIRY_DT, format="mixed", dayfirst=True)
    raw = raw[raw.Exp >= raw.Date].sort_values(["Date", "Exp"])
    g = raw.groupby("Date").first()
    return g.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})[
        ["Open", "High", "Low", "Close"]]


# ============================================================================
# 6. CLI
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Top Bottom System backtester",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--yahoo")
    src.add_argument("--nse", help="NSE futures symbol, e.g. BANKNIFTY")
    ap.add_argument("--name", help="display name (default: symbol / file name)")
    ap.add_argument("--mode", choices=["live", "sheet"], default="live")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--stock", action="store_true", help="stock rules: 1.5%% day SL, 3%% max SL, 3%% breakeven")
    ap.add_argument("--buffer", type=float, default=25.0, help="entry buffer in points (live)")
    ap.add_argument("--buffer-pct", type=float, help="entry buffer in %% instead of points")
    ap.add_argument("--day-sl", type=float)
    ap.add_argument("--max-sl", type=float)
    ap.add_argument("--be", type=float)
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--reuse-levels", action="store_true", help="allow a top/bottom to trigger more than once")
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--swing", type=float, default=0.0, help="glitch filter %% (0 = validated default)")
    ap.add_argument("--cost", type=float, default=0.0, help="round-trip cost per trade, points")
    ap.add_argument("--lot", type=float, default=1.0, help="lot size for rupee P&L")
    ap.add_argument("--compare", help="CSV trade log to match (Date, Side, Entry, Exit)")
    ap.add_argument("--out", default="tb_out")
    a = ap.parse_args(argv)

    base = Params.for_stocks() if a.stock else Params()
    p = Params(mode=a.mode, buffer_pts=a.buffer, buffer_pct=a.buffer_pct,
               day_sl_pct=a.day_sl if a.day_sl is not None else base.day_sl_pct,
               max_sl_pct=a.max_sl if a.max_sl is not None else base.max_sl_pct,
               be_pct=a.be if a.be is not None else base.be_pct,
               gap_pct=a.gap, use_once=not a.reuse_levels, long_only=a.long_only,
               swing_pct=a.swing, cost_pts=a.cost, lot=a.lot)

    if a.csv:
        df, name = load_csv(a.csv), a.name or os.path.basename(a.csv)
    elif a.yahoo:
        df, name = load_yahoo(a.yahoo), a.name or a.yahoo
    else:
        df, name = load_nse_futures(a.nse, a.start or "2008-01-01", a.end or pd.Timestamp.today().strftime("%Y-%m-%d")), a.name or f"{a.nse} FUT"

    # run on full history (so levels are warmed up), then report the requested window
    t = (run_live if p.mode == "live" else run_sheet)(df, p)
    if not t.empty:
        ed = pd.to_datetime(t["EntryDate"])
        if a.start:
            t = t[ed >= pd.Timestamp(a.start)]
            ed = pd.to_datetime(t["EntryDate"])
        if a.end:
            t = t[ed <= pd.Timestamp(a.end)]

    os.makedirs(a.out, exist_ok=True)
    t.to_csv(os.path.join(a.out, "trades.csv"), index=False)
    print(f"\n=== Top Bottom backtest — {name} — mode: {p.mode.upper()} ===")
    print("Settings:", {k: v for k, v in asdict(p).items()})
    print(f"Data: {df.index[0].date()} → {df.index[-1].date()}  ({len(df)} bars)\n")
    for k, v in summary(t, p).items():
        print(f"  {k:24} {v}")
    if not t.empty:
        m = monthly_table(t)
        m.to_csv(os.path.join(a.out, "monthly.csv"))
        y = t.assign(Year=pd.to_datetime(t.EntryDate).dt.year).groupby("Year").agg(
            Trades=("Points", "size"), Points=("Points", "sum"), PnL=("PnL", "sum"),
            HitPct=("Points", lambda s: round((s > 0).mean() * 100)))
        y.to_csv(os.path.join(a.out, "yearly.csv"))
        print("\nYearly:\n" + y.round(1).to_string())
        print("\nExit reasons:", t["Reason"].value_counts().to_dict())
    if a.compare:
        cmp_ = compare_with_log(t, a.compare)
        cmp_.to_csv(os.path.join(a.out, "comparison.csv"), index=False)
        print(f"\nComparison with {a.compare}: matched {int((cmp_.Match == 'yes').sum())}/{len(cmp_)} "
              f"trades (same side, ±1 day)\n" + cmp_.to_string(index=False))
    if p.mode == "live":
        print("\n" + next_day_levels(df, run_live(df, p), p, name))
    print(f"\nFiles written to {os.path.abspath(a.out)}/")


if __name__ == "__main__":
    main()
