"""20 EMA / SMA undercut-and-hold watch list (28 Nov 2026, Amritpal: "can I see such charts and decide").
WATCH ONLY. Tested (claude/undercut-20-ma-breakout-test.md): no short-term edge; the 20 EMA + falling trendline + volume version
held with the 9/21 exit made +0.44R a trade since 2021 (257 trades, last year -0.13R) - so: charts to look at, not a system.
Rules (as tools/research/undercut20.py): uptrend (close > SMA50, the 20 average rising); the last 3 swing lows (2 bars each side,
within 45 sessions) each wick BELOW the 20 average and the 3rd swing-low candle CLOSES at / above it (>= 0.998x).
Rows (latest close):
  breakout - today closed above the base top or above the falling trendline (base's highest high -> its latest lower swing high);
             buy tomorrow above today's high + 0.15%, stop under swing low 3
  forming  - the 3 swing lows are in place, no breakout yet; shows the base top and where the trendline will be next session
NSE stocks (Yahoo), >= Rs 2 cr/day, price >= 50. Output data/scan/undercut.json."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "research"))
import flag_volume as FV  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "data", "scan", "undercut.json")


def scan(sym, x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); n = len(c); i = n - 1
    if n < 90:
        return []
    C = x.CLOSE; s50 = C.rolling(50).mean().to_numpy()
    val = float((C * x.VOL).rolling(20).mean().iloc[-1]) / 1e7; v20 = float(x.VOL.rolling(20).mean().shift(1).iloc[-1])
    if not (val >= 2 and c[i] >= 50 and c[i] > s50[i]):
        return []
    sl = [k for k in range(2, n - 2) if l[k] < l[k - 1] and l[k] < l[k - 2] and l[k] < l[k + 1] and l[k] < l[k + 2]]
    sh = [k for k in range(2, n - 2) if h[k] > h[k - 1] and h[k] > h[k - 2] and h[k] > h[k + 1] and h[k] > h[k + 2]]
    lows = [k for k in sl if i - 45 <= k <= i - 3]
    if len(lows) < 3:
        return []
    a, b, z = lows[-3:]; rows = []
    for ma, m in (("EMA", C.ewm(span=20, adjust=False).mean().to_numpy()), ("SMA", C.rolling(20).mean().to_numpy())):
        # 28 Nov 2026: the 20 average must be RISING at all three swing lows and price above the 50 SMA there (a healthy uptrend
        # riding the 20 - NTPC, a downtrend bottom, slipped through the first version)
        if not (m[i] > m[i - 10] and l[a] < m[a] and l[b] < m[b] and l[z] < m[z] and c[z] >= 0.998 * m[z]
                and all(m[k] > m[k - 5] and c[k] > s50[k] * 0.98 for k in (a, b, z))):
            continue
        top = float(h[a:i].max())
        p = a + int(np.argmax(h[a:i])); qs = [k for k in sh if p < k <= i - 3 and h[k] < h[p]]
        line_now = line_next = None
        if qs:
            q = qs[-1]; slope = (h[q] - h[p]) / (q - p)
            if slope < 0:
                line_now, line_next = h[p] + slope * (i - p), h[p] + slope * (i + 1 - p)
                line_prev = h[p] + slope * (i - 1 - p)
        bo_top = bool(c[i] > top and c[i - 1] <= top)
        bo_line = bool(line_now is not None and c[i] > line_now and c[i - 1] <= line_prev and c[i] < h[p])
        status = "breakout" if (bo_top or bo_line) else ("forming" if c[i] <= top else None)
        if status is None:
            continue
        stop = float(l[z]); trig = float(h[i] * 1.0015) if status == "breakout" else None
        d = x.index
        rows.append(dict(symbol=sym, ma=ma, status=status, breakout=("trendline" if bo_line else "base top") if status == "breakout" else None,
                         vol_x=round(float(v[i] / v20), 2) if v20 else None, vol_ok=bool(v20 and v[i] >= 1.5 * v20),
                         close=round(float(c[i]), 2), ma20=round(float(m[i]), 2), top=round(top, 2),
                         line_next=round(float(line_next), 2) if line_next else None, trigger=round(trig, 2) if trig else None, stop=round(stop, 2),
                         risk_pct=round((trig - stop) / trig * 100, 1) if trig else round((c[i] - stop) / c[i] * 100, 1),
                         lows=[str(d[k].date()) for k in (a, b, z)], best=bool(ma == "EMA" and bo_line and v20 and v[i] >= 1.5 * v20)))
    # one row per stock: prefer EMA, then SMA
    return rows[:1]


def main():
    P = FV.load()
    R = []
    for s, x in P.items():
        try:
            R += scan(s, x)
        except Exception as ex:  # noqa: BLE001
            print("skip", s, str(ex)[:60])
    R.sort(key=lambda r: (r["status"] != "breakout", not r["best"], -(r["vol_x"] or 0)))
    asof = max((str(x.index[-1].date()) for x in P.values()), default=None)
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=asof, rows=R,
               note="Watch only. Tested: no short-term edge; 20 EMA + falling trendline + volume held with the 9/21 exit +0.44R since 2021 (257 trades), last year -0.13R.")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=0)
    print("R| rows", len(R), "breakouts", sum(r["status"] == "breakout" for r in R), "best", sum(r["best"] for r in R))


if __name__ == "__main__":
    main()
