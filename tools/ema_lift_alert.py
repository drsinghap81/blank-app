"""EMA 9 lift-off alert (19 Nov 2026, Amritpal: "can an alert be generated if a candle leaves a rising EMA").
INFORMATION ONLY. Tested in tools/research/ema_liftoff.py (project doc ema-liftoff-candle-test), daily futures 2007-26:
  lift-off = first candle whose LOW is above a RISING EMA 9 (EMA above its value 3 sessions ago), none in the previous 10 sessions
  ride until the first candle whose HIGH is below EMA 9 ("left below") -> out next open
  Bank Nifty: 5 trades/yr, 42% win, avg +1.95% (median -0.6%), profit factor 2.1; 2017-26 avg +0.94%. Nifty avg +0.96%, PF 2.0.
  53 F&O stocks: avg +1.46%, PF 1.6. The candle alone does not predict direction (10-day return = any day); the gain comes from
  riding the few big trends. Short side (candle fully below a falling EMA) LOST money - not alerted as a short.
Data: data/futures/*.csv (continuous near-month futures, refreshed nightly by paper-trade.yml). Output: data/scan/ema_lift.json"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = "data/scan/ema_lift.json"
N, K = 9, 10


def state(x):
    o, h, l, c = x.Open, x.High, x.Low, x.Close
    e = c.ewm(span=N, adjust=False).mean()
    above = (l > e).values; below = (h < e).values; rising = (e > e.shift(3)).values
    m = len(c); pos, ent_i = None, None
    for i in range(60, m):
        if pos is None and above[i] and rising[i] and not above[i - K:i].any():
            pos, ent_i = "riding", i
        elif pos == "riding" and below[i]:
            last_exit = i
            pos = None
            if i == m - 1:
                return dict(status="left below", signal=str(x.index[ent_i].date()), signal_close=round(float(c.iloc[ent_i]), 2),
                            gain=round(float(c.iloc[i] / c.iloc[ent_i] - 1) * 100, 1), days=int(i - ent_i), ema=round(float(e.iloc[-1]), 2), close=round(float(c.iloc[-1]), 2))
    if pos == "riding":
        return dict(status="lift-off today" if ent_i == m - 1 else "riding", signal=str(x.index[ent_i].date()), signal_close=round(float(c.iloc[ent_i]), 2),
                    gain=round(float(c.iloc[-1] / c.iloc[ent_i] - 1) * 100, 1), days=int(m - 1 - ent_i), ema=round(float(e.iloc[-1]), 2),
                    close=round(float(c.iloc[-1]), 2), low=round(float(l.iloc[-1]), 2))
    return None


def main():
    rows, asof = [], None
    for f in sorted(glob.glob("data/futures/*.csv")):
        sym = os.path.basename(f)[:-4].replace("M_M", "M&M")
        x = pd.read_csv(f, parse_dates=["Date"]).set_index("Date").sort_index()[["Open", "High", "Low", "Close"]].dropna()
        x = x[(x > 0).all(axis=1)]
        if len(x) < 120 or (pd.Timestamp.today() - x.index[-1]).days > 7:
            continue
        asof = max(asof or x.index[-1], x.index[-1])
        s = state(x)
        if s and x.index[-1] == asof:
            rows.append(dict(symbol=sym, index=sym in ("NIFTY", "BANKNIFTY"), **s))
    order = {"lift-off today": 0, "left below": 1, "riding": 2}
    rows.sort(key=lambda r: (not r["index"], order[r["status"]], -r["gain"]))
    prev = {}
    try:
        prev = json.load(open(OUT))
    except Exception:  # noqa: BLE001
        pass
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), asof=str(asof.date()) if asof is not None else None,
               ema=N, rows=rows, rule=__doc__.split("Data:")[0].strip())
    json.dump(out, open(OUT, "w"), indent=1)
    new = [r for r in rows if r["status"] in ("lift-off today", "left below")]
    for r in rows:
        print(r["symbol"], r["status"], r["signal"], r["gain"])
    if new and os.environ.get("SEND_TELEGRAM") == "1" and prev.get("asof") != out["asof"]:
        try:
            import notify
            def msg(r):
                what = ("candle left the rising 9 EMA (whole candle above)" if r["status"] == "lift-off today"
                        else f"whole candle below the 9 EMA - ride over ({r['gain']:+}% since {r['signal']})")
                return f"{r['symbol']}: {what} · close {r['close']:,.2f}, EMA9 {r['ema']:,.2f}"
            lines = [msg(r) for r in new]
            notify.send("EMA 9 lift-off alert (info only):\n" + "\n".join(lines))
        except Exception as e:  # noqa: BLE001
            print("notify failed", e)


if __name__ == "__main__":
    main()
