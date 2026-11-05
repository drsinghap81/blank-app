"""Daily trade plan for the Live tab: the most probable India trades for the next session, ranked by backtest evidence.

Inputs (written by the evening scans): data/scan/ath.json (monthly ATH, incl. close breakouts), data/scan/trend_scan.json
(9/21 system), data/scan/sectors.json (top-down). US/ASX are not included: their backtests showed no edge (watch only).

Candidates
  ATH_BRK  : monthly-ATH breakout this month or last, trade still open, price within -5% / +10% of the entry (the backtest
             bought at the breakout; late buys have less room). Stop = 30-week SMA. Exit rule: weekly close below it.
  ATH_STOP : within 5% below the ATH-month-high trigger -> a buy-stop order at the trigger (stop-limit, day order).
  T921     : 9/21 EMA cross "NEW - buy next open" (stop <= 12% away). Stop = 5-day low. Exit: Supertrend red.
  (near rows whose trigger is a month CLOSE are listed as 'watch' - a month close cannot be a resting order.)
Score (points from the backtests; the combination itself is a ranking rule, not a separately tested system)
  base : ATH base >= 24 m 3, 12-24 m 2; buy-stop at trigger 2; 9/21 new buy 3
  ATH only (top-down did not help 9/21): +2 aligned (sector RS > 0 and stock RS > 0; 54% win / +29% vs 48% / +15%),
        +1 best theme RS > 0, -3 stock RS <= 0 (29% win), -1 if bought > 5% above the breakout
  ties: stock RS, then traded value
Exits: ATH signals with "exit next open" and 9/21 trades whose Supertrend turned red (the server matches them to holdings).
Writes data/scan/trade_plan.json. Sizing is done in the apps / server from your capital: risk 1% to the stop, max 20% a stock,
max 10 positions."""
import json
from datetime import datetime, timezone

import numpy as np

OUT = "data/scan/trade_plan.json"
MAX_LATE = 0.10        # skip ATH breakouts already > 10% above the entry
MAX_BELOW = 0.05       # ... or > 5% back below it (failing breakout; not what the backtest bought)
TOP = 10


def load(p):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {}


def num(v):
    try:
        v = float(v)
        return v if np.isfinite(v) else None
    except Exception:  # noqa: BLE001
        return None


def main():
    ath, tr, sec = load("data/scan/ath.json"), load("data/scan/trend_scan.json"), load("data/scan/sectors.json")
    ix = sec.get("indices") or {}
    secname = lambda k: (k or "").replace("NIFTY ", "").title()  # noqa: E731
    C = []

    def td(r):
        return dict(sector=secname(r.get("sector_index")), sector_rs=num(r.get("sector_rs")), theme=secname(r.get("theme")),
                    theme_rs=num(r.get("theme_rs")), stock_rs=num(r.get("stock_rs")), aligned=bool(r.get("aligned")),
                    td_score=r.get("td_score"))

    for r in ath.get("breakouts") or []:
        if r.get("status") != "open":
            continue
        entry, close, stop = num(r.get("entry")), num(r.get("close")), num(r.get("sma30"))
        if not entry or not close or not stop or close <= stop:
            continue
        late = close / entry - 1
        if late > MAX_LATE or late < -MAX_BELOW:   # fresh breakouts only: near the price the backtest bought
            continue
        t = td(r)
        sc = (3 if r.get("main") else 2) + (2 if t["aligned"] else 0) + (1 if (t["theme_rs"] or 0) > 0 else 0) \
            - (3 if t["stock_rs"] is not None and t["stock_rs"] <= 0 else 0) - (1 if late > 0.05 else 0)
        C.append(dict(id=f"ATH-{r['symbol']}-{r.get('date')}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH",
                      kind="ATH_BRK", order="LIMIT", when="next open", side="BUY", price=round(close * 1.01, 2), ref=close,
                      stop=round(stop, 2), exit_rule="weekly close below the 30-week SMA",
                      note=f"{'close ' if r.get('kind') == 'close' else ''}breakout {r.get('date')}, base {r.get('base_months')} m, "
                           f"{late * 100:+.1f}% vs entry {entry:.2f}",
                      base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
    for r in ath.get("near") or []:
        trig, close, stop = num(r.get("trigger")), num(r.get("close")), num(r.get("sma30"))
        if not trig or not stop or trig <= stop:
            continue
        t = td(r)
        if r.get("kind") == "close":
            C.append(dict(id=f"WATCH-{r['symbol']}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", kind="WATCH",
                          order=None, when="month close", side="BUY", price=trig, ref=close, stop=round(stop, 2),
                          note=f"signal = a month CLOSE above {trig:.2f} (old ATH close), then buy next month's open",
                          base_months=r.get("base_months"), score=-99, value_cr=num(r.get("value_cr")), **t))
            continue
        sc = 2 + (1 if r.get("main") else 0) + (2 if t["aligned"] else 0) + (1 if (t["theme_rs"] or 0) > 0 else 0) \
            - (3 if t["stock_rs"] is not None and t["stock_rs"] <= 0 else 0) - 1
        C.append(dict(id=f"STOP-{r['symbol']}-{r.get('trigger')}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH",
                      kind="ATH_STOP", order="STOPLOSS_LIMIT", when="day order, re-place each morning", side="BUY",
                      trigger=round(trig, 2), price=round(trig * 1.01, 2), ref=close, stop=round(stop, 2),
                      exit_rule="weekly close below the 30-week SMA",
                      note=f"buy-stop at the ATH-month high {trig:.2f} ({r.get('gap_pct', 0):.1f}% above), base {r.get('base_months')} m",
                      base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
    for r in tr.get("early") or []:
        if not str(r.get("status", "")).startswith("NEW - buy"):
            continue
        close, stop = num(r.get("signal_close") or r.get("close")), num(r.get("stop"))
        if not close or not stop or close <= stop or close < 100:
            continue
        C.append(dict(id=f"T921-{r['symbol']}-{r.get('signal_date')}", symbol=r["symbol"], name=r.get("name", ""), system="9/21 trend",
                      kind="T921", order="LIMIT", when="next open", side="BUY", price=round(close * 1.01, 2), ref=close,
                      stop=round(stop, 2), exit_rule="Supertrend(10,3) turns red -> sell next open",
                      note=f"EMA 9/21 cross {r.get('signal_date')}, stop {r.get('risk_pct', 0):.1f}% below", score=3,
                      value_cr=num(r.get("value_cr")), sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None,
                      aligned=False, td_score=None))
    # one row per stock (keep the higher score)
    best = {}
    for c in C:
        if c["symbol"] not in best or c["score"] > best[c["symbol"]]["score"]:
            best[c["symbol"]] = c
    C = sorted(best.values(), key=lambda c: (-c["score"], -(c["stock_rs"] or -999), -(c["value_cr"] or 0)))
    trades = [c for c in C if c["kind"] != "WATCH"]
    for i, c in enumerate(trades):
        c["rank"] = i + 1
        c["risk_pct"] = round((c.get("trigger") or c["price"]) / c["stop"] * 100 - 100, 1) if c["stop"] else None
    exits = []
    for r in ath.get("tracked") or []:
        if r.get("status") == "exit next open":
            exits.append(dict(id=f"EXIT-ATH-{r['symbol']}", symbol=r["symbol"], system="Monthly ATH", side="SELL", order="LIMIT",
                              when="next open", ref=num(r.get("close")), why="weekly close below the 30-week SMA"))
    for r in tr.get("early") or []:
        if str(r.get("status", "")).startswith("EXIT"):
            exits.append(dict(id=f"EXIT-T921-{r['symbol']}", symbol=r["symbol"], system="9/21 trend", side="SELL", order="LIMIT",
                              when="next open", ref=num(r.get("close")), why="Supertrend turned red"))
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), market="NSE",
               asof=max(str(ath.get("asof") or ""), str(tr.get("asof") or "")),
               rules=dict(risk_pct=1.0, max_pos_pct=20.0, max_positions=10, max_late_pct=MAX_LATE * 100, max_below_pct=MAX_BELOW * 100, top=TOP,
                          limit_buffer_pct=1.0),
               top=trades[:TOP], more=trades[TOP:30], watch=[c for c in C if c["kind"] == "WATCH"], exits=exits)
    json.dump(out, open(OUT, "w"), indent=0, default=str)
    print("trade plan:", len(trades), "candidates, top", [(c["symbol"], c["kind"], c["score"]) for c in trades[:TOP]], "exits", len(exits))


if __name__ == "__main__":
    main()
