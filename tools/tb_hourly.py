"""Top Bottom hourly re-entry level (for a MISSED daily entry). Runs every ~15 min in NSE hours (ath-intraday workflow).

Backtest (Nov 2023 - Oct 2026, 108 daily trades still open on day 2, costs 0.06%):
  chase at next open -2,145 pts | hourly breakout + hourly stop, ONE attempt +6,129 pts, worst trade -549.
Rule, while the daily system is LONG (mirror for SHORT), from the day after the daily entry:
  buy when Bank Nifty trades above the last HOURLY top + 50 pts; stop = last hourly bottom - 50 (trails up);
  if the stop is hit, stay out until the next daily signal; otherwise exit with the daily system.
Levels are computed on the Bank Nifty INDEX (Yahoo 60-minute candles, ~15 min delayed) and shown with a futures
equivalent using the basis at the last close (paper/next_orders.json). Writes data/live/tb_hourly.json."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send  # noqa: E402

BUF = 50.0
OUT = "data/live"
SENT = f"{OUT}/tb_hourly_sent.json"


def swings(close):
    """Last top / bottom known at the end of each bar: every 1-bar turning point of the close (same as topbottom.py)."""
    n = len(close); lt = np.full(n, np.nan); lb = np.full(n, np.nan)
    hi, hi_i, lo, lo_i, mode, t, b = close[0], 0, close[0], 0, 0, np.nan, np.nan
    for i in range(1, n):
        c = close[i]
        if mode >= 0 and c > hi:
            hi, hi_i = c, i
        if mode <= 0 and c < lo:
            lo, lo_i = c, i
        if mode >= 0 and c < hi and hi_i < i:
            t = hi; mode = -1
            seg = close[hi_i + 1:i + 1]; j = int(np.argmin(seg)); lo, lo_i = seg[j], hi_i + 1 + j
        elif mode <= 0 and c > lo and lo_i < i:
            b = lo; mode = 1
            seg = close[lo_i + 1:i + 1]; j = int(np.argmax(seg)); hi, hi_i = seg[j], lo_i + 1 + j
        lt[i], lb[i] = t, b
    return lt, lb


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    force = os.environ.get("FORCE") == "1"
    if not force and (now.weekday() > 4 or not (9 * 60 + 15 <= now.hour * 60 + now.minute <= 15 * 60 + 40)):
        print("outside NSE hours", now); return
    os.makedirs(OUT, exist_ok=True)
    orders = json.load(open("paper/next_orders.json"))["BANKNIFTY"]
    led = pd.read_csv("paper/ledger.csv")
    op = led[led.Status.astype(str).str.startswith("OPEN")]
    base = dict(time=now.strftime("%Y-%m-%d %H:%M IST"), buffer=BUF, delayed_min=15)
    if op.empty:
        json.dump(dict(base, state="flat", note="Daily system is flat: no missed entry to re-enter."), open(f"{OUT}/tb_hourly.json", "w"), indent=1)
        print("flat"); return
    tr = op.iloc[-1]; side = 1 if tr.Side == "BUY" else -1
    entry_day = pd.Timestamp(tr.EntryDate).date()
    d = yf.download("^NSEBANK", period="60d", interval="60m", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d[["Open", "High", "Low", "Close"]].dropna()
    d.index = d.index.tz_convert("Asia/Kolkata").tz_localize(None)
    now_naive = now.replace(tzinfo=None)
    last_px = float(d.Close.iloc[-1])
    # swing levels use finished candles only (the last candle may still be forming)
    d_fin = d.iloc[:-1] if d.index[-1] + pd.Timedelta(minutes=60) > now_naive else d
    c = d_fin.Close.to_numpy(float); h = d.High.to_numpy(float); lo = d.Low.to_numpy(float); o = d.Open.to_numpy(float)
    T, B = swings(c)
    # simulate the one-attempt rule from the first hourly bar after the daily entry day
    state, ent, ent_t, stop, xp, xt = "waiting", None, None, None, None, None
    for k in range(1, len(d)):
        kk = min(k - 1, len(c) - 1)          # levels known at the end of the previous finished bar
        if d.index[k].date() <= entry_day or kk < 0:
            continue
        lvl = (T[kk] + BUF) if side > 0 else (B[kk] - BUF)
        sl = (B[kk] - BUF) if side > 0 else (T[kk] + BUF)
        if state == "entered":
            stop = max(stop, sl) if side > 0 else min(stop, sl)
            if (side > 0 and lo[k] <= stop) or (side < 0 and h[k] >= stop):
                state, xp, xt = "stopped", (min(o[k], stop) if side > 0 else max(o[k], stop)), d.index[k]
                break
        elif state == "waiting" and np.isfinite(lvl) and ((side > 0 and h[k] > lvl) or (side < 0 and lo[k] < lvl)):
            state, ent, ent_t, stop = "entered", (max(o[k], lvl) if side > 0 else min(o[k], lvl)), d.index[k], sl
    top, bot = float(T[-1]), float(B[-1])
    lvl_now = (top + BUF) if side > 0 else (bot - BUF)
    stop_now = (bot - BUF) if side > 0 else (top + BUF)
    if state == "entered":
        stop_now = stop
    basis = float(orders.get("close", 0) or 0) - float(orders.get("spot_close", 0) or 0)
    r = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 1)
    out = dict(base, state=state, side="LONG" if side > 0 else "SHORT", daily_entry=str(entry_day),
               daily_entry_price=float(tr.Entry), last_index=r(last_px), hour_top=r(top), hour_bottom=r(bot),
               level=r(lvl_now) if state == "waiting" else None, stop=r(stop_now) if state in ("waiting", "entered") else None,
               entered_at=r(ent), entered_time=str(ent_t) if ent_t is not None else None,
               stopped_at=r(xp), stopped_time=str(xt) if xt is not None else None, basis=round(basis, 1),
               level_fut=r(lvl_now + basis) if state == "waiting" else None,
               stop_fut=r(stop_now + basis) if state in ("waiting", "entered") else None)
    json.dump(out, open(f"{OUT}/tb_hourly.json", "w"), indent=1)
    # one alert per event
    try:
        sent = json.load(open(SENT))
    except Exception:  # noqa: BLE001
        sent = {"keys": []}
    word = "Buy" if side > 0 else "Sell"
    for key, msg in ((f"in:{entry_day}:{ent_t}", state in ("entered", "stopped") and ent is not None and
                      f"Top Bottom hourly re-entry ({out['side']}): {word} triggered at {ent:,.0f} (index) {ent_t:%d %b %H:%M}. "
                      f"Hourly stop {stop:,.0f} (fut ~{stop + basis:,.0f}). One attempt only."),
                     (f"out:{entry_day}:{xt}", state == "stopped" and
                      f"Top Bottom hourly re-entry stopped at {xp:,.0f} (index). Stay out until the next daily signal.")):
        if msg and key not in sent["keys"]:
            send(msg); sent["keys"].append(key)
    json.dump(sent, open(SENT, "w"))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
