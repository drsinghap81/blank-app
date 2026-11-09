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
import sys
from datetime import datetime, timezone

import numpy as np

DIR = {"NSE": "data/scan/", "US": "data/scan/us/", "ASX": "data/scan/asx/"}
MINPX = {"NSE": 100, "US": 10, "ASX": 1}   # 9/21: no penny stocks
MAX_LATE = 0.10        # skip ATH breakouts already > 10% above the entry
MAX_BELOW = 0.05       # ... or > 5% back below it (failing breakout; not what the backtest bought)
TOP = 10
BASE_MAIN = 24         # cup >= 24 months -> Momentum Investing; 12-24 months -> Trend Following 9/21
TF_SYS = "Trend 9/21"
LEGACY_921 = True      # 9/21 on any trend stock (trend_scan.json): its own bucket, on the cash the others leave idle


def buckets(mk):
    """Live systems as capital buckets (Amritpal, 9 Nov 2026). pct = the most of your capital the bucket may hold; buckets share
    one cash pool, Momentum first; the swing buckets leave 15% of capital in cash for new Momentum breakouts.
    NSE one-account test 2017-26 (1% risk of total capital each, 10% max a stock, 10 positions a bucket, 3 random fill orders):
      Momentum alone 17.3%/yr, worst fall -16.8% (49% invested on average)
      Momentum <= 60% + Trend 9/21 <= 40%: 23.1%, -21.4% (2022-26: 25.9%, -13.0%)   <- default
      Momentum <= 60% + Trend 9/21 <= 25%: 20.6%, -20.4%;  Trend 9/21 alone: 10.5%, -15.6%.
      + 9/21 on any trend stock on the cash still idle (15% kept for Momentum): 27.4%, -23.2% (2022-26 27.4%, -16.8%)  <- default
      (Momentum + that 9/21 without the cup 9/21: 26.3%, -20.2%)."""
    india = mk == "NSE"
    B = [dict(key="mom", name="Momentum Investing", system="Monthly ATH", status="active", pct=60,
              rules="Monthly close at an all-time high after a cup of 2+ years; buy when price crosses that month's high. "
                    "Stop: weekly close below the 30-week SMA, raised every week until it triggers.",
              test="NSE 2017-26 alone: 17.3%/yr, worst fall -16.8%." if india else "US/ASX 2008-26: did not beat the index (paper phase)."),
         dict(key="tf", name="Trend Following 9/21", system=TF_SYS, status="active", pct=40,
              rules="Same monthly breakout with a 1-2 year cup. Stop for sizing: EMA 21 (min 4% under the entry); "
                    "exit when a daily close has EMA 9 below EMA 21 (sell next open).",
              test="NSE 2017-26 alone 10.5%/yr, worst fall -15.6%; with Momentum (60/40, one account) 23.1%/yr, -21.4%. "
                   "Other exits tested worse: 5-day-low + Supertrend 11.5%/-20.6%, weekly 9/21 14.7%/-33.8%." if india else "Not tested on US/ASX yet (paper record tracks it)."),
         dict(key="t9", name="9/21 Trend (any stock)", system="9/21 trend", status="active", pct=40,
              rules="Daily EMA 9 crosses above EMA 21 on a stock in an uptrend (trend scan); buy next open; stop = 5-day low "
                    "(max 12% away); exit when price closes below Supertrend(10,3). Uses the cash the other systems leave idle.",
              test="NSE 2017-26 alone 20-26%/yr, worst fall -24 to -26%; Momentum + Trend 9/21 + this on idle cash: 27.4%/yr, -23.2%." if india
                   else "US/ASX: no edge over the index in the 2008-26 test (paper record tracks it)."),
         dict(key="rt", name="Breakout retest", system="Breakout retest", status="active", pct=15,
              rules="First return to an old breakout level; stop 1 ATR under it, 3R target, out after 120 days. "
                    + ("Skipped in Weak/Fading industries." if india else "Experimental."),
              test="NSE 2017-26: +0.17 to +0.24R a trade in Building/Strong/Middle industries vs +0.09R random." if india
                   else "US/ASX 2008-26: worse than a random stock the same day (+0.19R vs +0.25R)."),
         dict(key="pt", name="Bottom pattern", system="Bottom pattern", status="watch" if india else "active", pct=0 if india else 5,
              rules="Double/triple bottom, tilted W, inverse H&S neckline breakout; stop under the pattern, measured-move target, 120 days.",
              test="Lagged the average stock in every industry lane on NSE 2017-26 (watch list only)." if india
                   else "US/ASX 2008-26: +2.5% vs +5.0% for a random stock over 120 days (experimental)."),
         dict(key="s1", name="System 1", status="pending", pct=0, rules="Rules to come from Amritpal.", test="Not tested yet."),
         dict(key="s2", name="System 2", status="pending", pct=0, rules="Rules to come from Amritpal.", test="Not tested yet."),
         dict(key="s3", name="System 3", status="pending", pct=0, rules="Rules to come from Amritpal.", test="Not tested yet."),
         dict(key="wc", name="Wealth Creation", status="pending", pct=0, rules="Rules to come from Amritpal.", test="Not tested yet.")]
    if india:
        B.append(dict(key="tb", name="Top Bottom", system="Top Bottom", status="active", pct=15, margin=True,
                      rules="Index futures on the hourly Top Bottom rules (separate bot, its own card). Uses margin from pledged "
                            "holdings, not cash; % = the capital its lots are sized on.",
                      test="2017-26 with the stock book on pledge margin: see the Top Bottom tab (bot stays in DRY RUN until you switch it)."))
    return B


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


LANE_ORD = {"build": 0, "hold": 1, "mid": 2, None: 3, "bounce": 4, "fade": 5, "weak": 6}


def lanes(G):
    """Industry momentum-shift lane per group (same rule as the app): strong/weak = quarter Pulse top/bottom 40%;
    rising = week > month > quarter by 10+ pts. Building beat other groups by +1.7% over 3 months (2017-26)."""
    R = G.get("rows") or []
    if not R:
        return {}
    qs = sorted(r["p1q"] for r in R)
    qt = lambda f: qs[min(len(qs) - 1, int(f * (len(qs) - 1)))]  # noqa: E731
    hi, lo = qt(0.6), qt(0.4); out = {}
    for r in R:
        up = r["p1w"] > r["p1m"] > r["p1q"] and r["p1w"] - r["p1q"] >= 10
        dn = r["p1w"] < r["p1m"] < r["p1q"] and r["p1q"] - r["p1w"] >= 10
        out[r["group"]] = (("build" if up else "fade" if dn else "hold") if r["p1q"] >= hi else
                           (("bounce" if up else "weak") if r["p1q"] <= lo else "mid"), r["p1m"], r["rank"])
    return out


def main(mk="NSE"):
    D = DIR[mk]; OUT = D + "trade_plan.json"; india = mk == "NSE"
    ath, tr, sec = load(D + "ath.json"), load(D + "trend_scan.json"), load(D + "sectors.json")
    G = load(D + "group_pulse.json"); LN = lanes(G); GS = G.get("stock") or {}
    ix = sec.get("indices") or {}
    names = sec.get("names") or {}
    secname = lambda k: names.get(k) or ((k or "").replace("NIFTY ", "").title() if india else (k or ""))  # noqa: E731
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
        sc = (3 if r.get("main") else 2) - (1 if late > 0.05 else 0)
        if india:
            sc += (2 if t["aligned"] else 0) + (1 if (t["theme_rs"] or 0) > 0 else 0) - (3 if t["stock_rs"] is not None and t["stock_rs"] <= 0 else 0)
        if (r.get("base_months") or 0) < BASE_MAIN:   # cup 12-24 m -> Trend Following 9/21 (daily EMA exit)
            if r.get("tf_status", "open") != "open":
                continue
            E = round(close * 1.01, 2); s9 = min(num(r.get("ema21")) or E * 0.96, E * 0.96)
            C.append(dict(id=f"TF-{r['symbol']}-{r.get('date')}", symbol=r["symbol"], name=r.get("name", ""), system=TF_SYS, bucket="tf",
                          kind="TF_BRK", order="LIMIT", when="next open", side="BUY", price=E, ref=close, stop=round(s9, 2),
                          exit_rule="daily close with EMA 9 below EMA 21 -> sell next open",
                          note=f"{'close ' if r.get('kind') == 'close' else ''}cup breakout {r.get('date')}, cup {r.get('base_months')} m, "
                               f"{late * 100:+.1f}% vs entry {entry:.2f}; stop = EMA 21 (min 4%)",
                          base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
            continue
        C.append(dict(id=f"ATH-{r['symbol']}-{r.get('date')}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", bucket="mom",
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
        sc = 2 + (1 if r.get("main") else 0) - 1
        if india:
            sc += (2 if t["aligned"] else 0) + (1 if (t["theme_rs"] or 0) > 0 else 0) - (3 if t["stock_rs"] is not None and t["stock_rs"] <= 0 else 0)
        if (r.get("base_months") or 0) < BASE_MAIN:
            s9 = min(num(r.get("ema21")) or trig * 0.96, trig * 0.96)
            C.append(dict(id=f"TFSTOP-{r['symbol']}-{r.get('trigger')}", symbol=r["symbol"], name=r.get("name", ""), system=TF_SYS, bucket="tf",
                          kind="TF_STOP", order="STOPLOSS_LIMIT", when="day order, re-place each morning", side="BUY",
                          trigger=round(trig, 2), price=round(trig * 1.01, 2), ref=close, stop=round(s9, 2),
                          exit_rule="daily close with EMA 9 below EMA 21 -> sell next open",
                          note=f"buy-stop at the cup high {trig:.2f} ({r.get('gap_pct', 0):.1f}% above), cup {r.get('base_months')} m; stop = EMA 21 (min 4%)",
                          base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
            continue
        C.append(dict(id=f"STOP-{r['symbol']}-{r.get('trigger')}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", bucket="mom",
                      kind="ATH_STOP", order="STOPLOSS_LIMIT", when="day order, re-place each morning", side="BUY",
                      trigger=round(trig, 2), price=round(trig * 1.01, 2), ref=close, stop=round(stop, 2),
                      exit_rule="weekly close below the 30-week SMA",
                      note=f"buy-stop at the ATH-month high {trig:.2f} ({r.get('gap_pct', 0):.1f}% above), base {r.get('base_months')} m",
                      base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
    for r in (tr.get("early") or []) if LEGACY_921 else []:   # old 9/21 (any trend stock): replaced by Trend Following 9/21 on 9 Nov 2026
        if not str(r.get("status", "")).startswith("NEW - buy"):
            continue
        close, stop = num(r.get("signal_close") or r.get("close")), num(r.get("stop"))
        if not close or not stop or close <= stop or close < MINPX[mk] or (r.get("risk_pct") or 0) > 12:
            continue
        C.append(dict(id=f"T921-{r['symbol']}-{r.get('signal_date')}", symbol=r["symbol"], name=r.get("name", ""), system="9/21 trend", bucket="t9",
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
    for c in best.values():   # industry lane (tag + tiebreak only: as a filter it cut ATH returns in the 2017-26 test)
        g = GS.get(c["symbol"]); x = LN.get(g[0]) if g else None
        c.update(group=g[0] if g else None, lane=x[0] if x else None, group_pulse=x[1] if x else None, group_rank=x[2] if x else None)
    if india:
        C = sorted(best.values(), key=lambda c: (-c["score"], LANE_ORD[c["lane"]], -(c["stock_rs"] or -999), -(c["value_cr"] or 0)))
    else:
        # US / ASX (8 Nov 2026, Amritpal's choice): top-down order - number of levels passed (sector 6-month RS > 0,
        # industry Building/Strong, stock 1-year RS > 0) first, then sector, industry lane, system score, stock RS.
        # Not backtested as a ranking (top-down levels gave no lift as filters there); it only changes the order.
        def lv(c):   # top-down checks passed: sector beats the index, industry Building/Strong, stock beats its sector
            return ((c["sector_rs"] or 0) > 0) + (c["lane"] in ("build", "hold")) + ((c["stock_rs"] or 0) > 0)
        for c in best.values():
            c["td_levels"] = lv(c)
        C = sorted(best.values(), key=lambda c: (-lv(c), -((c["sector_rs"] or 0) > 0), LANE_ORD[c["lane"]], -c["score"],
                                                  -(c["stock_rs"] or -999), -(c["value_cr"] or 0)))
    # two sleeves (8 Nov 2026): ATH = momentum investing (wide 30-week stops, sized on capital);
    # 9/21 = swing on ATH's idle cash (5-day-low stop, Supertrend exit). Backtest 2017-26: ATH + 9/21 on idle cash 30.8%/yr, -24%.
    # India only: breakout retests at support join the swing sleeve when the industry is not Weak / Fading / Weak-bouncing.
    # Test 2017-26 (1-ATR stop, 3R target, 0.3% cost): Building +0.24R, Strong +0.17R, Middle +0.18R, no group +0.30R,
    # Weak +0.14R, Fading +0.09R, Weak bouncing +0.08R; random uptrend stock +0.09R. US/ASX retests were worse than random.
    # Bottom patterns lagged the average stock in EVERY lane (Building -2.4 pts over 120 days) -> watch list only.
    pat_watch = []
    if not india:
        # US / ASX (8 Nov 2026, Amritpal: "include all strategies"): breakout retests and bottom-pattern breakouts as EXPERIMENTAL
        # swing rows. Backtest 2008-26 there: both did worse than a random stock the same day (patterns +2.5% vs +5.0% over 120 days;
        # retests +0.19R vs +0.25R), so they rank after 9/21 and the paper record tracks them.
        sup, pat = load(D + "support.json"), load(D + "patterns.json")
        def lane_of(sym):
            g = GS.get(sym); x = LN.get(g[0]) if g else None
            return (g[0] if g else None, x[0] if x else None, x[1] if x else None, x[2] if x else None)
        for r in sup.get("rows") or []:
            if r.get("status") != "touched" or r.get("level_kind") != "breakout retest" or (r.get("days_ago") or 0) > 1 or r["symbol"] in best:
                continue
            close, stop = num(r.get("close")), num(r.get("stop"))
            g, ln, gp, gr = lane_of(r["symbol"])
            if not close or not stop or close <= stop or close < MINPX[mk] or ln in ("weak", "fade", "bounce"):
                continue
            E = round(close * 1.01, 2); tgt = round(E + 3 * (E - stop), 2)
            best[r["symbol"]] = dict(id=f"RET-{r['symbol']}-{r.get('touch_date')}", symbol=r["symbol"], name=r.get("name", ""), system="Breakout retest", bucket="rt",
                                     kind="RETEST", order="LIMIT", when="next open", side="BUY", price=E, ref=close, stop=round(stop, 2), target=tgt,
                                     exit_rule=f"3R target {tgt:.2f} or the stop, max 120 days", experimental=True,
                                     note=f"retest of the old breakout level {r.get('level'):.2f} on {r.get('touch_date')} · experimental: worse than random in the {mk} backtest",
                                     score=1, value_cr=None, sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                                     group=g, lane=ln, group_pulse=gp, group_rank=gr)
        PN = {"DB": "double bottom", "TW": "tilted W", "TB": "triple bottom", "IHS": "inverse H&S"}
        for r in pat.get("rows") or []:
            if r.get("kind") != "stock" or r.get("status") != "breakout" or (r.get("days_since") or 0) > 3 or r["symbol"] in best:
                continue
            close, stop, neck = num(r.get("close")), num(r.get("stop")), num(r.get("neck"))
            if not close or not stop or not neck or close <= stop or close < MINPX[mk]:
                continue
            E = round(close * 1.01, 2); tgt = round(neck * (1 + (r.get("height_pct") or 0) / 100), 2)
            if (E - stop) / E > 0.20 or (tgt - E) < (E - stop):          # skip stops > 20% away and targets under 1R
                continue
            g, ln, gp, gr = lane_of(r["symbol"])
            if ln in ("weak", "fade", "bounce"):
                continue
            best[r["symbol"]] = dict(id=f"PAT-{r['symbol']}-{r.get('signal_date')}", symbol=r["symbol"], name=r.get("name", ""), system="Bottom pattern", bucket="pt",
                                     kind="PATTERN", order="LIMIT", when="next open", side="BUY", price=E, ref=close, stop=round(stop, 2), target=tgt,
                                     exit_rule=f"measured-move target {tgt:.2f} or the stop, max 120 days", experimental=True,
                                     note=f"{PN.get(r.get('typ'), r.get('typ'))} broke the neckline {neck:.2f} on {r.get('signal_date')} · experimental: worse than random in the {mk} backtest",
                                     score=0, value_cr=None, sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                                     group=g, lane=ln, group_pulse=gp, group_rank=gr)
    if india:
        sup, pat = load(D + "support.json"), load(D + "patterns.json")
        for r in sup.get("rows") or []:
            if r.get("status") != "touched" or r.get("level_kind") != "breakout retest" or (r.get("days_ago") or 0) > 1:
                continue
            close, stop = num(r.get("close")), num(r.get("stop"))
            if not close or not stop or close <= stop or close < MINPX[mk] or r["symbol"] in best:
                continue
            g = GS.get(r["symbol"]); x = LN.get(g[0]) if g else None; ln = x[0] if x else None
            if ln in ("weak", "fade", "bounce"):
                continue
            E = round(close * 1.01, 2); res = num(r.get("resistance"))
            tgt = round(E + 3 * (E - stop), 2)
            best[r["symbol"]] = dict(id=f"RET-{r['symbol']}-{r.get('touch_date')}", symbol=r["symbol"], name=r.get("name", ""), system="Breakout retest", bucket="rt",
                                     kind="RETEST", order="LIMIT", when="next open", side="BUY", price=E, ref=close, stop=round(stop, 2), target=tgt,
                                     exit_rule=f"3R target {tgt:.2f} or the stop, max 120 days (as tested)",
                                     note=f"retest of the old breakout level {r.get('level'):.2f} on {r.get('touch_date')}"
                                          + (f", next resistance {res:.2f}" if res else ""), score=2, value_cr=None,
                                     sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                                     group=g[0] if g else None, lane=ln, group_pulse=x[1] if x else None, group_rank=x[2] if x else None)
        for r in pat.get("rows") or []:
            if r.get("kind") != "stock" or r.get("status") != "breakout":
                continue
            g = GS.get(r["symbol"]); x = LN.get(g[0]) if g else None
            pat_watch.append(dict(symbol=r["symbol"], name=r.get("name", ""), typ=r.get("typ"), close=num(r.get("close")), neck=num(r.get("neck")),
                                  stop=num(r.get("stop")), signal_date=r.get("signal_date"), group=g[0] if g else None, lane=x[0] if x else None,
                                  group_rank=x[2] if x else None))
        pat_watch.sort(key=lambda w: (LANE_ORD[w["lane"]], w.get("signal_date") or ""))
    trades = [c for c in best.values() if c.get("bucket") == "mom"]
    trades.sort(key=lambda c: C.index(c))
    KORD = {"TF_BRK": 0, "TF_STOP": 0, "T921": 1, "RETEST": 2, "PATTERN": 3}
    swing = sorted([c for c in best.values() if c["kind"] in KORD],
                   key=lambda c: (LANE_ORD[c["lane"]], KORD[c["kind"]], -(c["value_cr"] or 0)))
    if india:   # every Trend 9/21 signal, the best 8 retests
        keep = {id(x) for x in [c for c in swing if c["bucket"] in ("tf", "t9")] + [c for c in swing if c["kind"] == "RETEST"][:8]}
        swing = [c for c in swing if id(c) in keep]
    else:   # keep all 9/21, the best 8 retests and 6 patterns, then order the lot top-down (industry lane, then 9/21 > retest > pattern)
        keep = {id(x) for x in [c for c in swing if c["kind"] in ("T921", "TF_BRK", "TF_STOP")] + [c for c in swing if c["kind"] == "RETEST"][:8]
                + [c for c in swing if c["kind"] == "PATTERN"][:6]}
        swing = [c for c in swing if id(c) in keep]
    seen = {}
    for L in (trades, swing):
        for i, c in enumerate(L):
            b = c.get("bucket") if L is swing else "mom"; seen[b] = seen.get(b, 0) + 1
            c["rank"] = seen[b]                          # rank within its system
            c["risk_pct"] = round((c.get("trigger") or c["price"]) / c["stop"] * 100 - 100, 1) if c["stop"] else None
    exits = []
    for r in ath.get("tracked") or []:
        if r.get("status") == "exit next open":   # all bases: holdings bought as Monthly ATH before the 9 Nov split keep this exit
            exits.append(dict(id=f"EXIT-ATH-{r['symbol']}", symbol=r["symbol"], system="Monthly ATH", side="SELL", order="LIMIT",
                              when="next open", ref=num(r.get("close")), why="weekly close below the 30-week SMA"))
        if r.get("tf_status") == "exit next open":
            exits.append(dict(id=f"EXIT-TF-{r['symbol']}", symbol=r["symbol"], system=TF_SYS, side="SELL", order="LIMIT",
                              when="next open", ref=num(r.get("close")), why="daily close with EMA 9 below EMA 21"))
    for r in tr.get("early") or []:
        if str(r.get("status", "")).startswith("EXIT"):
            exits.append(dict(id=f"EXIT-T921-{r['symbol']}", symbol=r["symbol"], system="9/21 trend", side="SELL", order="LIMIT",
                              when="next open", ref=num(r.get("close")), why="Supertrend turned red"))
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), market=mk, watch_only=not india,
               asof=max(str(ath.get("asof") or ""), str(tr.get("asof") or "")),
               rules=dict(risk_pct=1.0, max_pos_pct=20.0, max_positions=10, max_late_pct=MAX_LATE * 100, max_below_pct=MAX_BELOW * 100, top=TOP,
                          limit_buffer_pct=1.0),
               buckets=buckets(mk), top=trades[:TOP], more=trades[TOP:30], swing=swing, pattern_watch=pat_watch[:20], watch=[c for c in C if c["kind"] == "WATCH"], exits=exits)
    json.dump(out, open(OUT, "w"), indent=0, default=str)
    print("trade plan:", len(trades), "ATH +", len(swing), "swing, top", [(c["symbol"], c["kind"], c["score"]) for c in trades[:TOP]], "exits", len(exits))


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["NSE"]):
        main(m)
