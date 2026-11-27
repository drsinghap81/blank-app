"""Clean rising 20 EMA bounce - WATCH LIST + forward record (28 Nov 2026, Amritpal: "Yes" to a nightly watch list he judges by eye).
Rule = tools/research/ema20_bounce.py v3 (claude/ema20-bounce-clean-charts-test.md): about 20 setups a year across NSE, +0.11R a
trade with a 2R target since 2021 (53% won), last 3 years about flat - NOT a tested system, a watch list.
  clean rising chart : 20 EMA rising over the last 60 sessions (checked every 10), no close more than 1% below it, >= 2 earlier
                       touches that held; close > SMA50
  touch (swing low)  : low <= 20 EMA x 1.005 and close >= the EMA, the EMA rising (above its value 5 sessions ago)
  breakout candle    : within 10 sessions of the touch, a close above the previous swing high on >= 1.5x the 20-day volume,
                       the touch low not broken first
  entry / stop       : buy above the breakout candle's high + 0.15% for 3 sessions; stop under the touch (swing) low; risk 1-12%
Rows (latest close): 'breakout' (today's candle, buy above it next 3 sessions), 'pending' (breakout 1-2 sessions ago, trigger
not hit yet), 'watch' (clean chart + touch in the last 10 sessions, waiting for the volume breakout above the swing high).
Forward record: every breakout row goes into data/scan/ema_bounce_log.json once; each night open entries are marked filled /
2R hit / stopped / expired from the data (2R target, 10 sessions after the fill, as tested).
NSE stocks (Yahoo), >= Rs 2 cr/day, price >= 50. Output data/scan/ema_bounce.json."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "research"))
import flag_volume as FV  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "scan", "ema_bounce.json"); LOG = os.path.join(ROOT, "data", "scan", "ema_bounce_log.json")
BUF = 0.0015


def clean_at(m, c, l, t):
    w0 = t - 60
    if w0 < 10:
        return False
    return bool(m[t] > m[w0] and all(m[k] > m[k - 10] for k in range(w0 + 10, t + 1, 10)) and (c[w0:t] >= m[w0:t] * 0.99).all()
                and sum(1 for k in range(w0, t - 2) if l[k] <= m[k] * 1.005 and c[k] >= m[k] and l[k] < l[k - 1] and l[k] <= l[k + 1]) >= 2)


def scan(sym, x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); n = len(c); i = n - 1
    if n < 120:
        return None
    C = x.CLOSE; m = C.ewm(span=20, adjust=False).mean().to_numpy(); s50 = C.rolling(50).mean().to_numpy()
    v20 = x.VOL.rolling(20).mean().shift(1).to_numpy(); val = float((C * x.VOL).rolling(20).mean().iloc[-1]) / 1e7
    if not (val >= 2 and c[i] >= 50):
        return None
    best = None
    for t in range(i - 12, i + 1):                       # touches in the last ~12 sessions, newest wins
        if t < 70 or not (c[t] > s50[t] and m[t] > m[t - 5] and l[t] <= m[t] * 1.005 and c[t] >= m[t]):
            continue
        if not clean_at(m, c, l, t):
            continue
        shs = [k for k in range(max(2, t - 40), t - 1) if h[k] >= h[k - 1] and h[k] >= h[k - 2] and h[k] >= h[k + 1] and h[k] >= h[k + 2]]
        if not shs:
            continue
        sh = float(h[shs[-1]]); bk = None; broken = False
        for k in range(t + 1, min(n, t + 11)):
            if l[k] < l[t]:
                broken = True; break
            if c[k] > sh and v20[k] and v[k] >= 1.5 * v20[k]:
                bk = k; break
        if broken:
            continue
        row = dict(symbol=sym, touch=str(x.index[t].date()), touch_low=round(float(l[t]), 2), swing_high=round(sh, 2),
                   ema20=round(float(m[i]), 2), close=round(float(c[i]), 2), date=str(x.index[i].date()))
        if bk is None:
            if i - t <= 10:
                row.update(status="watch", needs=f"close above {sh:.2f} on >= 1.5x volume", vol20=round(float(v20[i]), 0))
                best = row
            continue
        trig = float(h[bk] * (1 + BUF)); stop = float(l[t]); risk = (trig - stop) / trig
        if not (0.01 <= risk <= 0.12):
            continue
        age = i - bk
        if age == 0:
            st = "breakout"
        elif age <= 2 and h[bk + 1:i + 1].max() < trig:
            st = "pending"
        else:
            continue
        row.update(status=st, breakout_day=str(x.index[bk].date()), vol_x=round(float(v[bk] / v20[bk]), 2), trigger=round(trig, 2),
                   stop=round(stop, 2), risk_pct=round(risk * 100, 1), target_2r=round(trig + 2 * (trig - stop), 2), valid_sessions_left=3 - age)
        best = row
    return best


def update_log(log, P):
    """mark open forward-record entries from the latest data (fill within 3 sessions, then 2R / stop / 10-session close)."""
    for r in log:
        if r.get("result") not in (None, "waiting", "open"):
            continue
        x = P.get(r["symbol"])
        if x is None:
            continue
        D = [str(d.date()) for d in x.index]
        if r["breakout_day"] not in D:
            continue
        b = D.index(r["breakout_day"]); o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c)
        j = None
        for k in range(b + 1, min(n, b + 4)):
            if h[k] >= r["trigger"]:
                if o[k] > r["trigger"] * 1.03:
                    break
                j = k; break
        if j is None:
            r["result"] = "expired" if n - 1 >= b + 3 else "waiting"; continue
        e = max(o[j], r["trigger"]); R = e - r["stop"]; r.update(filled=D[j], entry=round(float(e), 2))
        res = None
        for k in range(j, min(n, j + 11)):
            if l[k] <= r["stop"]:
                res = ("stopped", (min(o[k], r["stop"]) if k > j else r["stop"])); break
            if h[k] >= e + 2 * R:
                res = ("2R", (max(o[k], e + 2 * R) if k > j else e + 2 * R)); break
        if res is None:
            if n - 1 >= j + 10:
                res = ("10 days", c[j + 10])
            else:
                r.update(result="open", now_R=round(float((c[-1] - e) / R), 2)); continue
        r.update(result=res[0], exit=round(float(res[1]), 2), R=round(float((res[1] - e) / R - 0.004 * e / R), 2))
    return log


def main():
    P = FV.load()
    rows = [r for s, x in P.items() if (r := scan(s, x))]
    order = {"breakout": 0, "pending": 1, "watch": 2}
    rows.sort(key=lambda r: (order[r["status"]], r.get("risk_pct") or 99))
    try:
        log = json.load(open(LOG))
    except Exception:  # noqa: BLE001
        log = []
    seen = {(r["symbol"], r["breakout_day"]) for r in log}
    for r in rows:
        if r["status"] in ("breakout", "pending") and (r["symbol"], r["breakout_day"]) not in seen:
            log.append({k: r[k] for k in ("symbol", "touch", "breakout_day", "trigger", "stop", "risk_pct", "vol_x")} | {"result": "waiting"})
    log = update_log(log, P)
    done = [r for r in log if r.get("R") is not None]
    rec = dict(n=len(log), closed=len(done), avg_R=round(float(np.mean([r["R"] for r in done])), 2) if done else None,
               won=sum(1 for r in done if r["R"] > 0))
    asof = max((str(x.index[-1].date()) for x in P.values()), default=None)
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=asof, rows=rows, record=rec,
                   note="Watch only, not a tested system: ~20 setups a year; backtest +0.11R a trade (2R target) since 2021, 53% won; last 3 years about flat."),
              open(OUT, "w"), indent=0)
    json.dump(log, open(LOG, "w"), indent=0)
    print("R| rows", len(rows), {k: sum(r["status"] == k for r in rows) for k in order}, "record", rec)


if __name__ == "__main__":
    main()
