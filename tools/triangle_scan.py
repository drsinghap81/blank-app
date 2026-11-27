"""Ascending triangle WATCH LIST + forward record (28 Nov 2026, Amritpal: "Usha Martin type and the reel type are good ascending
triangles that can be added as scans"). Rule = tools/research/contract_res.py 'triangle' (claude/contracting-pullbacks-flat-resistance-
test.md): NOT a tested system - 23 cases since 2016 averaged -0.28R (2R target), so this is a list to judge by eye.
  resistance R  : highest high of the last 150 sessions
  flat top      : >= 3 swing highs within 1% of R, >= 10 sessions apart (forming: >= 2 so far, price back near R)
  rising lows   : each pullback from R is 30-80% of the one before (gradual contraction); first >= 6%; last <= 6%
  tight base    : the last 5 sessions' range <= 6%, every close at / under R
  breakout      : close above R. Buy above the breakout candle's high + 0.15% for 3 sessions; stop under the tight range's low.
Rows: 'breakout' (today), 'pending' (1-2 sessions ago, not triggered), 'forming' (>= 2 touches, gradual rising lows, now tight within 6%
under R - the next test). NSE stocks (Yahoo), >= Rs 2 cr/day, price >= 100. Output data/scan/triangle.json (+ triangle_log.json)."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "research"))
import flag_volume as FV  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "scan", "triangle.json"); LOG = os.path.join(ROOT, "data", "scan", "triangle_log.json")
BUF = 0.0015


def touches(h, sh, R, a, b):
    tc = []
    for k in range(a, b):
        if sh[k] and h[k] >= R * 0.99 and (not tc or k - tc[-1] >= 10):
            tc.append(k)
    return tc


def gradual(d):
    return all(0.3 <= d[i + 1] / d[i] <= 0.8 for i in range(len(d) - 1) if d[i] > 0) and d[0] >= 0.06


def chart(x, i0, segs):
    """last bars from i0 (date, high, low, close) + the pullback lows (date, low) for the app's marked chart."""
    h, l, c = (x[k].to_numpy(float) for k in ("HIGH", "LOW", "CLOSE")); D = x.index
    lows = []
    for a, b in segs:
        k = a + int(np.argmin(l[a:b])); lows.append([str(D[k].date()), round(float(l[k]), 2)])
    return dict(bars=[[str(D[k].date()), round(float(h[k]), 2), round(float(l[k]), 2), round(float(c[k]), 2)] for k in range(i0, len(c))], lows=lows)


def scan(sym, x):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); i = n - 1
    if n < 200:
        return None
    val = float((x.CLOSE * x.VOL).rolling(20).mean().iloc[-1]) / 1e7
    if not (val >= 2 and c[i] >= 100):
        return None
    sh = np.zeros(n, bool); sh[2:-2] = (h[2:-2] > h[1:-3]) & (h[2:-2] > h[:-4]) & (h[2:-2] >= h[3:-1]) & (h[2:-2] >= h[4:])
    D = x.index
    # breakouts in the last 3 sessions (t = breakout day)
    for t in range(i, i - 3, -1):
        R = h[t - 150:t].max()
        if not (c[t] > R and c[t - 1] <= R):
            continue
        tc = touches(h, sh, R, t - 150, t - 2)
        if len(tc) < 3 or t - tc[0] < 30:
            continue
        d = [1 - l[a:b].min() / R for a, b in zip(tc, tc[1:] + [t])]
        if not (gradual(d) and d[-1] <= 0.06 and h[t - 5:t].max() / l[t - 5:t].min() - 1 <= 0.06 and (c[t - 5:t] <= R).all()):
            continue
        stop = float(l[tc[-1]:t].min()); trig = float(h[t] * (1 + BUF)); risk = (trig - stop) / trig
        if not 0.01 <= risk <= 0.12:
            continue
        age = i - t
        if age and h[t + 1:i + 1].max() >= trig:
            return None                                  # already triggered - in the forward record, not a fresh setup
        return dict(symbol=sym, status="breakout" if age == 0 else "pending", resistance=round(float(R), 2), touches=[str(D[k].date()) for k in tc],
                    pullbacks=[round(z * 100, 1) for z in d], breakout_day=str(D[t].date()), trigger=round(trig, 2), stop=round(stop, 2),
                    risk_pct=round(risk * 100, 1), target_2r=round(trig + 2 * (trig - stop), 2), valid_sessions_left=3 - age,
                    close=round(float(c[i]), 2), date=str(D[i].date()), **chart(x, max(0, tc[0] - 15), list(zip(tc, tc[1:] + [t]))))
    # forming: >= 2 touches with gradual rising lows, price now tight just under R (testing it again)
    R = h[i - 150:i + 1].max()
    if not (c[i] <= R and c[i] >= R * 0.94):
        return None
    tc = touches(h, sh, R, i - 150, i - 1)
    if len(tc) < 2 or i - tc[0] < 30:
        return None
    d = [1 - l[a:b].min() / R for a, b in zip(tc, tc[1:] + [i + 1])]
    if not (gradual(d) and d[-1] <= 0.06 and h[i - 4:i + 1].max() / l[i - 4:i + 1].min() - 1 <= 0.06):
        return None
    return dict(symbol=sym, status="forming", resistance=round(float(R), 2), touches=[str(D[k].date()) for k in tc],
                pullbacks=[round(z * 100, 1) for z in d], to_line_pct=round((R / c[i] - 1) * 100, 1), stop_if_breaks=round(float(l[tc[-1]:i + 1].min()), 2),
                close=round(float(c[i]), 2), date=str(D[i].date()), **chart(x, max(0, tc[0] - 15), list(zip(tc, tc[1:] + [i + 1]))))


def update_log(log, P):
    """fill within 3 sessions, then 2R / stop / 10-session close (as the backtest); R net of 0.4%."""
    for r in log:
        if r.get("result") not in (None, "waiting", "open"):
            continue
        x = P.get(r["symbol"])
        if x is None:
            continue
        Dl = [str(d.date()) for d in x.index]
        if r["breakout_day"] not in Dl:
            continue
        b = Dl.index(r["breakout_day"]); o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); j = None
        for k in range(b + 1, min(n, b + 4)):
            if h[k] >= r["trigger"]:
                if o[k] > r["trigger"] * 1.03:
                    break
                j = k; break
        if j is None:
            r["result"] = "expired" if n - 1 >= b + 3 else "waiting"; continue
        e = max(o[j], r["trigger"]); R = e - r["stop"]; r.update(filled=Dl[j], entry=round(float(e), 2)); res = None
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
    rows = []
    for s, x in P.items():
        try:
            r = scan(s, x)
        except Exception as ex:  # noqa: BLE001
            print("skip", s, str(ex)[:60]); r = None
        if r:
            rows.append(r)
    order = {"breakout": 0, "pending": 1, "forming": 2}
    rows.sort(key=lambda r: (order[r["status"]], r.get("risk_pct") or r.get("to_line_pct") or 99))
    try:
        log = json.load(open(LOG))
    except Exception:  # noqa: BLE001
        log = []
    seen = {(r["symbol"], r["breakout_day"]) for r in log}
    for r in rows:
        if r["status"] in ("breakout", "pending") and (r["symbol"], r["breakout_day"]) not in seen:
            log.append({k: r[k] for k in ("symbol", "breakout_day", "trigger", "stop", "risk_pct", "pullbacks")} | {"result": "waiting"})
    log = update_log(log, P)
    done = [r for r in log if r.get("R") is not None]
    rec = dict(n=len(log), closed=len(done), avg_R=round(float(np.mean([r["R"] for r in done])), 2) if done else None, won=sum(1 for r in done if r["R"] > 0))
    asof = max((str(x.index[-1].date()) for x in P.values()), default=None)
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=asof, rows=rows, record=rec,
                   note="Watch only, not a tested system: ~2 a year; backtest 23 cases since 2016 averaged -0.28R (2R target)."), open(OUT, "w"), indent=0)
    json.dump(log, open(LOG, "w"), indent=0)
    print("R| rows", len(rows), {k: sum(r["status"] == k for r in rows) for k in order}, "record", rec)


if __name__ == "__main__":
    main()
