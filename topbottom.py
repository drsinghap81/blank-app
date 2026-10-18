"""Top Bottom System (Dow-theory style) on the closing-price line.

Rules (as agreed with the user):
  1. Buy above the previous top, sell below the previous bottom (stop-and-reverse).
  2. Tops/bottoms are turning points of the daily CLOSE line. Tiny wiggles
     ("glitches") are ignored: a top is only confirmed once the close has fallen
     at least `swing_pct` % from it (bottoms mirror this).
  3. The stop trails to each new confirmed bottom (long) / top (short).
  4. Optional safety stops: max stop, entry-day stop, breakeven after +X %.
  5. Gap beyond the system point by more than `gap_pct` -> exit only, no new trade.

Reference data transcribed from the user's backtest sheets (Bank Nifty futures,
points per 1 unit, P/L booked in the month the trade was ENTERED).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Reference results (user's sheet). Each list = Jan..Dec. None = no data.
# --------------------------------------------------------------------------
REF_MONTHLY = {
    2007: [204, 1026, -2, 271, 547, 248, 199, 1165, 1088, -292, -485, -356],
    2008: [3364, 0, 36, 866, 1646, 917, 333, 730, 896, 470, 344, 609],
    2009: [809, 1018, 1457, 236, 1265, -3, 1020, 187, 1111, 855, 553, 652],
    2010: [868, 715, 309, 459, 393, 563, 563, 190, 1790, 49, 1380, -201],
    2011: [825, 127, 927, 356, 332, 797, 1186, 83.4, 25, 19, 1195, 176.05],
    2012: [2562.8, 412, 127, 1261, 600, -250, 348, 355, 1303, -56, 1240, 320],
    2013: [117.7, 411, 138, 949, 1183, 163, 881, 414, 1156, 457.7, -212, -123],
    2014: [340.1, -215, 1238, 1320, -70, 655, 650, 1120.8, 408, 2689.1, 433.5, -124],
    2015: [3096.75, 372, 1227, -309, -480, 1649, 130, 1504, 1480, 45, -547, 375],
    2016: [1765, 1001, 933, -123, 652, -281, 546, 833, 75, -896, -307, 502],
    2017: [2403, 0, 701, 838, 437, 711, 1694, 557, 1184, 59, 809, 447],
    2018: [1788, 1379, 93, 1205, 848, None, None, None, None, None, None, None],
}

REF_TRADES_2017 = [  # (entry date, side, entry, exit)
    ("2017-01-04", "SELL", 18034, 18060),
    ("2017-01-05", "BUY", 18060, 19103),
    ("2017-01-20", "SELL", 19103, 19199),
    ("2017-01-25", "BUY", 19199, 20681),
    ("2017-03-02", "SELL", 20681, 20734),
    ("2017-03-08", "BUY", 20734, 21488),
    ("2017-04-07", "SELL", 21488, 21683),
    ("2017-04-11", "BUY", 21683, 21710),
    ("2017-04-17", "SELL", 21710, 21733),
    ("2017-04-24", "BUY", 21733, 22762),
    ("2017-05-12", "SELL", 22762, 22842),
    ("2017-05-16", "BUY", 22842, None),
]


def ref_monthly_series() -> pd.Series:
    rows = {}
    for y, vals in REF_MONTHLY.items():
        for m, v in enumerate(vals, start=1):
            if v is not None:
                rows[pd.Period(f"{y}-{m:02d}", "M")] = float(v)
    return pd.Series(rows).sort_index()


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------
@dataclass
class TBParams:
    swing_pct: float = 0.0        # glitch filter: min reversal (%) to confirm a top/bottom
    trigger: str = "close"        # "close": signal when the CLOSE crosses the point; "intraday": high/low crosses
    fill: str = "level"           # close-trigger fill price: "level" (system point, as in the sheet) or "close"
    safety: bool = True           # apply max / entry-day / breakeven stops
    max_stop_pct: float = 2.0     # 2 indices, 3 stocks
    entry_day_pct: float = 1.0    # 1 indices, 1.5 stocks
    breakeven_pct: float = 2.0    # 2 indices, 3 stocks
    gap_pct: float = 2.0          # gap beyond system point -> exit only
    cost_pts: float = 0.0         # round-trip cost in points per trade
    trail_rule: str = "every"     # "every": stop moves to every new bottom/top;
                                  # "dow": only after a higher top (long) / lower bottom (short)


# --------------------------------------------------------------------------
# Swing detection (causal: a level is known only from the bar AFTER it confirms)
# --------------------------------------------------------------------------
def confirmed_swings(close: np.ndarray, swing_pct: float):
    """Return arrays last_top[i], last_bot[i] = latest top/bottom known at the
    END of bar i, plus a list of (confirm_idx, pivot_idx, kind, value)."""
    n = len(close)
    th = swing_pct / 100.0
    last_top = np.full(n, np.nan)
    last_bot = np.full(n, np.nan)
    pivots = []
    hi, hi_i = close[0], 0
    lo, lo_i = close[0], 0
    mode = 0  # 0 = undecided, +1 = looking for a top, -1 = looking for a bottom
    t = b = np.nan
    for i in range(1, n):
        c = close[i]
        if mode >= 0:
            if c > hi:
                hi, hi_i = c, i
        if mode <= 0:
            if c < lo:
                lo, lo_i = c, i
        if mode >= 0 and c < hi and (hi - c) / hi >= th and hi_i < i:
            t = hi
            pivots.append((i, hi_i, "T", hi))
            mode = -1
            lo, lo_i = c, i
            # the bottom search starts from the bar after the top
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
        last_top[i] = t
        last_bot[i] = b
    return last_top, last_bot, pivots


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------
def run_topbottom(df: pd.DataFrame, p: TBParams) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    idx = df.index
    T, B, piv = confirmed_swings(c, p.swing_pct)
    n = len(c)
    # Dow filter: a bottom raises a long's stop only if the top before it beat the previous top
    bot_ok = np.zeros(n, bool)
    top_ok = np.zeros(n, bool)
    for j, (ci, _pi, kind, val) in enumerate(piv):
        prev = piv[j - 1][3] if j >= 1 else None
        prev2 = piv[j - 3][3] if j >= 3 else None
        ok = prev is None or prev2 is None or (prev > prev2 if kind == "B" else prev < prev2)
        if p.trail_rule == "every":
            ok = True
        (bot_ok if kind == "B" else top_ok)[ci] = ok
    intraday = p.trigger == "intraday"
    gap = p.gap_pct / 100

    trades = []
    pos = 0
    entry = entry_i = stop_be = None
    trail = np.nan

    def close_trade(i, price, reason):
        nonlocal pos
        trades[-1].update(ExitDate=idx[i], Exit=round(price, 2), Reason=reason)
        pos = 0

    def open_trade(i, side, price, why):
        nonlocal pos, entry, entry_i, stop_be
        nonlocal trail
        pos, entry, entry_i, stop_be = side, price, i, False
        trail = B[i - 1] if side > 0 else T[i - 1]
        trades.append(dict(EntryDate=idx[i], Side="BUY" if side > 0 else "SELL",
                           Entry=round(price, 2), Signal=why))

    for i in range(1, len(c)):
        top, bot = T[i - 1], B[i - 1]          # levels known before today
        hi_ = h[i] if intraday else c[i]
        lo_ = l[i] if intraday else c[i]
        op = o[i] if intraday else c[i]

        # ---------------- manage open position ----------------
        if pos != 0:
            # trail the stop with newly confirmed (and accepted) pivots
            k = i - 1
            if pos > 0 and k >= entry_i and bot_ok[k] and not np.isnan(B[k]):
                trail = B[k] if np.isnan(trail) else max(trail, B[k])
            if pos < 0 and k >= entry_i and top_ok[k] and not np.isnan(T[k]):
                trail = T[k] if np.isnan(trail) else min(trail, T[k])
            sys_lvl = trail if p.trail_rule == "dow" else (bot if pos > 0 else top)
            safety_lvl = None
            if p.safety:
                mx = entry * (1 - pos * p.max_stop_pct / 100)
                safety_lvl = mx
                if stop_be:
                    safety_lvl = entry
            # system reversal level vs safety level: whichever is tighter
            exit_lvl, reason, reverse = sys_lvl, "System point", True
            if safety_lvl is not None and (np.isnan(sys_lvl) or
                                           (pos > 0 and safety_lvl > sys_lvl) or
                                           (pos < 0 and safety_lvl < sys_lvl)):
                exit_lvl, reason, reverse = safety_lvl, ("Breakeven" if stop_be else "Max stop"), False
            if not np.isnan(exit_lvl):
                hit = lo_ <= exit_lvl if pos > 0 else hi_ >= exit_lvl
                if hit:
                    gapped = (o[i] < exit_lvl) if pos > 0 else (o[i] > exit_lvl)
                    big_gap = gapped and abs(o[i] - exit_lvl) / exit_lvl > gap
                    if intraday:
                        px = o[i] if gapped else exit_lvl
                    else:
                        px = exit_lvl if p.fill == "level" else c[i]
                    side = pos
                    close_trade(i, px, reason + (" (gap)" if big_gap else ""))
                    if reverse and not big_gap:
                        open_trade(i, -side, px, "Reverse")
                    continue
            # breakeven activation (after surviving the bar)
            if p.safety and not stop_be:
                fav = (h[i] - entry) / entry if pos > 0 else (entry - l[i]) / entry
                if fav >= p.breakeven_pct / 100:
                    stop_be = True
            continue

        # ---------------- flat: look for a fresh signal ----------------
        long_sig = not np.isnan(top) and hi_ > top
        short_sig = not np.isnan(bot) and lo_ < bot
        if long_sig and short_sig:  # pick the one nearer the open
            long_sig = abs(op - top) <= abs(op - bot)
            short_sig = not long_sig
        if long_sig:
            gapped = o[i] > top
            if gapped and (o[i] - top) / top > gap:
                continue
            px = (o[i] if gapped else top) if intraday else (top if p.fill == "level" else c[i])
            open_trade(i, 1, px, "Above top")
            if p.safety and c[i] <= px * (1 - p.entry_day_pct / 100):
                close_trade(i, c[i], "Entry-day stop")
        elif short_sig:
            gapped = o[i] < bot
            if gapped and (bot - o[i]) / bot > gap:
                continue
            px = (o[i] if gapped else bot) if intraday else (bot if p.fill == "level" else c[i])
            open_trade(i, -1, px, "Below bottom")
            if p.safety and c[i] >= px * (1 + p.entry_day_pct / 100):
                close_trade(i, c[i], "Entry-day stop")

    out = pd.DataFrame(trades)
    if out.empty:
        return out
    if "Exit" not in out:
        out["Exit"] = np.nan
    last_c = c[-1]
    out["Open"] = out["Exit"].isna()
    out["Exit"] = out["Exit"].fillna(round(last_c, 2))
    sign = np.where(out["Side"] == "BUY", 1, -1)
    out["Points"] = (out["Exit"] - out["Entry"]) * sign - p.cost_pts
    return out


def monthly_points(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    m = pd.to_datetime(trades["EntryDate"]).dt.to_period("M")
    return trades.groupby(m)["Points"].sum()


def compare_to_reference(trades: pd.DataFrame) -> dict:
    ref = ref_monthly_series()
    mine = monthly_points(trades)
    common = ref.index[(ref.index >= mine.index.min()) & (ref.index <= mine.index.max())] if len(mine) else []
    if len(common) == 0:
        return dict(months=0)
    r = ref.reindex(common).fillna(0)
    m = mine.reindex(common).fillna(0)
    corr = float(np.corrcoef(r, m)[0, 1]) if r.std() and m.std() else float("nan")
    return dict(months=len(common), ref_total=float(r.sum()), my_total=float(m.sum()),
                corr=corr, mae=float((r - m).abs().mean()),
                sign_agree=float(((r >= 0) == (m >= 0)).mean()))


def match_2017(trades: pd.DataFrame, tol_days: int = 2) -> pd.DataFrame:
    rows = []
    t = trades.copy()
    if not t.empty:
        t["EntryDate"] = pd.to_datetime(t["EntryDate"])
    for d, side, en, ex in REF_TRADES_2017:
        d = pd.Timestamp(d)
        cand = t[(t["Side"] == side) & ((t["EntryDate"] - d).abs() <= pd.Timedelta(days=tol_days))] if not t.empty else t
        if len(cand):
            k = cand.iloc[(cand["EntryDate"] - d).abs().argmin()]
            rows.append(dict(RefDate=d.date(), Side=side, RefEntry=en, RefExit=ex,
                             MyDate=k["EntryDate"].date(), MyEntry=k["Entry"], MyExit=k["Exit"],
                             Match="✅" if k["EntryDate"] == d else "≈"))
        else:
            rows.append(dict(RefDate=d.date(), Side=side, RefEntry=en, RefExit=ex,
                             MyDate=None, MyEntry=None, MyExit=None, Match="❌"))
    return pd.DataFrame(rows)


def tune(df: pd.DataFrame, base: TBParams, grid=(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)):
    rows = []
    for trig in ("close", "intraday"):
      for rule in ("every", "dow"):
        for s in grid:
            p = TBParams(**{**base.__dict__, "swing_pct": s, "trigger": trig, "trail_rule": rule})
            tr = run_topbottom(df, p)
            cmp_ = compare_to_reference(tr)
            m17 = match_2017(tr)
            rows.append(dict(trigger=trig, trail=rule, swing_pct=s, trades=len(tr),
                             exact_2017=int((m17["Match"] == "✅").sum()),
                             near_2017=int((m17["Match"] != "❌").sum()),
                             **cmp_))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Tuned, tradable variant (found by walk-forward test: tuned 2007-16, tested 2017-26)
# --------------------------------------------------------------------------
def run_tuned(df: pd.DataFrame, buffer_pct: float = 0.25, max_stop_pct: float = 2.0,
              long_only: bool = True, swing_pct: float = 0.0) -> pd.DataFrame:
    """Resting stop orders: buy-stop at last top * (1 + buffer), exit on a sell-stop at
    last bottom * (1 - buffer) or the max stop, whichever is tighter. Fills at the stop
    price, or at the open if the market gaps through it. Long-only by default."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    T, B, _ = confirmed_swings(c, swing_pct)
    b = buffer_pct / 100
    idx = df.index
    trades, pos, ent, ent_i = [], 0, 0.0, 0
    for i in range(1, len(c)):
        top, bot = T[i - 1], B[i - 1]
        if pos:
            stop = bot * (1 - b) if pos > 0 else top * (1 + b)
            if max_stop_pct:
                ms = ent * (1 - pos * max_stop_pct / 100)
                stop = ms if np.isnan(stop) else (max(stop, ms) if pos > 0 else min(stop, ms))
            if (l[i] <= stop) if pos > 0 else (h[i] >= stop):
                px = min(o[i], stop) if pos > 0 else max(o[i], stop)
                trades[-1].update(ExitDate=idx[i], Exit=round(px, 2))
                pos = 0
            continue
        lt, st_ = top * (1 + b), bot * (1 - b)
        go_l = not np.isnan(top) and h[i] >= lt
        go_s = (not long_only) and not np.isnan(bot) and l[i] <= st_
        if go_l and go_s:
            go_l = abs(o[i] - lt) <= abs(o[i] - st_)
            go_s = not go_l
        if go_l:
            pos, ent, ent_i = 1, max(o[i], lt), i
        elif go_s:
            pos, ent, ent_i = -1, min(o[i], st_), i
        else:
            continue
        trades.append(dict(EntryDate=idx[i], Side="BUY" if pos > 0 else "SELL", Entry=round(ent, 2),
                           Signal="Stop order"))
    out = pd.DataFrame(trades)
    if out.empty:
        return out
    if "Exit" not in out:
        out["Exit"] = np.nan
    out["Open"] = out["Exit"].isna()
    out["Exit"] = out["Exit"].fillna(round(c[-1], 2))
    sign = np.where(out["Side"] == "BUY", 1, -1)
    out["Points"] = (out["Exit"] - out["Entry"]) * sign
    return out
