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
  ties: industry results-season score (21 Nov 2026), then industry lane, stock RS, traded value
Exits: ATH signals with "exit next open" and 9/21 trades whose Supertrend turned red (the server matches them to holdings).
Writes data/scan/trade_plan.json. Sizing is done in the apps / server from your capital: risk 1% to the stop, max 20% a stock,
max 10 positions."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DIR = {"NSE": "data/scan/", "US": "data/scan/us/", "ASX": "data/scan/asx/", "UK": "data/scan/uk/"}
MINPX = {"NSE": 100, "US": 10, "ASX": 20, "UK": 100}   # UK in pence   # no penny stocks (ASX A$20 floor, Amritpal 10 Nov 2026)
MAX_LATE = 0.10        # skip ATH breakouts already > 10% above the entry
MAX_BELOW = 0.05       # ... or > 5% back below it (failing breakout; not what the backtest bought)
TOP = 10
BASE_MAIN = 24         # cup >= 24 months -> Momentum Investing; 12-24 months -> Trend Following 9/21
TF_SYS = "Trend 9/21"
LEGACY_921 = True      # 9/21 on any trend stock (trend_scan.json): its own bucket, on the cash the others leave idle


def buckets(mk):
    """Live systems as capital buckets. pct = the most of your capital the bucket may hold; buckets share one cash pool,
    Momentum first; the other stock buckets leave 15% of capital in cash for new Momentum breakouts.
    Optimised 9 Nov 2026 (scratchpad combo/alloc.py: one NSE account 2017-26, every bucket simulated with real positions,
    1% risk of total capital, 10% max a stock, 10 positions a bucket, 3 random fill orders; 80 cap combinations, then
    Top Bottom added on pledge margin at realistic fills):
      Momentum <= 60% + Trend 9/21 <= 40%                       23.1%/yr, worst fall -21.4% (2022-26 25.9%, -13.2%)
      + Top Bottom 1x (Rs 20L notional per Rs 20L)  <- default 33.2%/yr, -15.9% (2022-26 29.6%, -15.9%; without 2020 25.2%)
      + 9/21 any stock <= 40% (instead of off)                    36.2%, -23.3% at TB 1x / 24.8%, -28.0% without TB
      Breakout retests in the portfolio: -1.3%/yr alone (slots fill with the weak clusters) -> off.
    Systems 1-3 (tested 9 Nov) did not beat the Nifty or duplicated Momentum -> System 2/3 removed, System 1 off."""
    india = mk == "NSE"
    # 24 Nov 2026 (Amritpal: "Remove capital split" -> no caps, same systems): Momentum and Trend 9/21 may each use all capital;
    # each buy is still 1% risk, max 10% a stock, the cash reserve stays; the off systems stay off.
    B = [dict(key="mom", name="Momentum Investing", system="Monthly ATH", status="active", pct=100,
              rules="Monthly close at an all-time high after a cup of 2+ years; buy when price crosses that month's high. "
                    "Stop: weekly close below the 30-week SMA, raised every week until it triggers."
                    + (" Entry needs a daily close above that high on at least 1.5x the 50-day volume, then a buy-stop next session at that day's high + 0.15%; "
                       "skipped when the stock's industry is in a Weak, Fading or Turning Pulse lane." if india else ""),
              test="NSE 2017-26 alone: 17.3%/yr, worst fall -16.8%. With close confirmation + industry-lane skip (2008-26, shared with Trend 9/21): 20.5%/yr vs 17.9%." if india else "US/ASX 2008-26: did not beat the index (paper phase)." if mk in ("US", "ASX") else "UK 2008-26: about 1%/yr vs the FTSE 100 2.8% (price) - no edge (paper phase)."),
         dict(key="tf", name="Trend Following 9/21", system=TF_SYS, status="active", pct=100,
              rules="Same monthly breakout with a 1-2 year cup. Stop for sizing: EMA 21 (min 4% under the entry); "
                    "exit when a daily close has EMA 9 below EMA 21 (sell next open)."
                    + (" Entry needs a daily close above the highest wick so far, then a buy-stop next session at that day's high + 0.15%; "
                       "skipped when the industry is in a Weak, Fading or Turning Pulse lane." if india else ""),
              test="NSE 2017-26 alone 10.5%/yr, worst fall -15.6%; with Momentum (60/40, one account) 23.1%/yr, -21.4%." if india
                   else "Not tested on this market yet (paper record tracks it)."),
         dict(key="t9", name="9/21 Trend (any stock)", system="9/21 trend", status="off", pct=0,
              rules="Daily EMA 9 crosses above EMA 21 on a stock in an uptrend; stop = 5-day low (max 12%); exit on Supertrend(10,3) red.",
              test="Off: in the full one-account test it adds about 1.7 points a year but deepens the worst fall from -21% to -28% "
                   "(with Top Bottom: 36.2%, -23.3% vs 33.2%, -15.9%). Alone 20.7%/yr, -22.9%."),
         dict(key="rt", name="Breakout retest", system="Breakout retest", status="off", pct=0,
              rules="First return to an old breakout level; stop 1 ATR under it, 3R target, out after 120 days.",
              test="Off: +0.2R a trade on average, but as a 10-slot portfolio -1.3%/yr (the trades it can take cluster in falling markets)."),
         dict(key="pt", name="Bottom pattern", system="Bottom pattern", status="off", pct=0,
              rules="Double/triple bottom, tilted W, inverse H&S neckline breakout; stop under the pattern, measured-move target, 120 days.",
              test="Off: lagged the average stock in every industry lane (NSE 2017-26) and a random stock in the US/ASX test."),
         dict(key="vcp", name="VCP", system="VCP", status="watch", pct=0,
              rules="Volatility contraction pattern in a Stage 2 uptrend: >= 2 shrinking pullbacks with higher lows, volume drying up; "
                    "buy-stop above the last pullback's high on 1.4x volume; stop = that pullback's low (max 10%); sell after a daily close below EMA 50.",
              test=("NSE 2017-26: +4.9% a trade (221 trades, 37% win), robust across rule variants; added to Momentum + Trend it gave "
                    "24.2-24.7%/yr vs 23.1% with a similar worst fall and nothing extra in 2022-26, so it is a watch bucket - your call.") if india
                   else ("US 2008-26: +2.0% a trade (396 trades, 36% win); alone 8.5-8.9%/yr in 2017-26 vs the S&P 500 13.3%, weak 2008-16. "
                         "Weaker than NSE - watch bucket, your call." if mk == "US" else "UK: not backtested yet - watch only." if mk == "UK" else
                         "ASX 2008-26: about 3 setups a year (56 trades, +1.8% a trade) - too few to trust. Watch bucket - your call.")),
         dict(key="pr", name="Pulse rotation", system="Pulse rotation", status="active", pct=0,
              rules="Each Friday close: NSE industries in the top 10% by 1-month Pulse AND rotation Leading/Improving; hold the 10 strongest trending "
                    "stocks of those industries by 3-month return (kept while in the top 20 and the industry stays selected); equal weight "
                    "(the % you set / 10 a stock); buy and sell at Monday's open. RED traffic light at the Friday close: no basket that week (cash). "
                    "Safety stop 20% below the buy (not in the test).",
              test="NSE 2016-26 (survivors), Monday-open fills, 0.2% a side, RED-light skip: 37.4%/yr, worst fall -23.0%; last 1/2/3/5 years +19.7/+16.7/+40.6/+45.9% (without the skip 34.5% / -35.9%). "
                   "Trial: starts at 0% - set a small % to trade it.") if india else None,
         dict(key="fl", name="Flags", system="Flag breakout", status="active", pct=0,
              rules="Flag, pennant or rectangle after a 15%+ pole in an uptrend: tight pause (<= 8%), volume drying up, breakout close on 1.5x volume "
                    "with room >= 0.8 x the pole to the next resistance. Buy next open (within 3% of the breakout close); stop the flag low; "
                    "sell next open after a daily close below the 21-day EMA.",
              test="NSE 2016-26: +3.2% a trade (1,151 trades, PF 1.79); in the New mix (Mom+Cup 40, Flags 20, Pulse 10, gold 10, US 20) "
                   "since 2017 35.7%/yr with Top Bottom, worst fall -14%. Weak in 2025-26. Starts at 0% - set 20% for the New mix.") if india else None,
         dict(key="gd", name="Gold", system="Gold", status="active", pct=0,
              rules="GOLDBEES held at your % of capital as a hedge, no stop. Topped up when it is more than 15% under the target "
                    "(buy next open). Never sold by the app.",
              test="Gold moves against stocks; 10% gold in the New mix cut the worst fall since 2017 (-14% vs -22.6% for the old mix). "
                   "Starts at 0% - set 10% for the New mix.") if india else None,
         dict(key="s1", name="System 1", status="off", pct=0, rules="Weekly RSI system (rules kept privately).",
              test="Off on NSE: below the Nifty in every version tested; a US paper candidate."),
         dict(key="wc", name="Wealth Creation", status="sip", pct=0, rules="ETF Pie funded by a monthly SIP, outside the systems' capital: Nifty 50, Midcap 150, Gold and US Nasdaq 100 ETFs at fixed weights (Equal, Balanced or Aggressive) rebalanced each quarter, or the monthly rotation (best 2 by 3-month return).", test="2016-26 monthly, price indices, 0.2% per switch: Equal 25% each 18.3%/yr, worst -15.7%; Balanced 30/20/30/20 17.6%, -14.7%; Aggressive 30/30/10/30 18.4%, -20.2%; rotation 17.7%, -12.8%; Nifty 50 11.6%, -29.3%.")]
    B = [b for b in B if b]
    if india:
        B.append(dict(key="tb", name="Top Bottom", system="Top Bottom", status="active", pct=100, margin=True,
                      rules="Bank Nifty futures on the Top Bottom rules (separate bot, its own card). Uses margin from pledged holdings, "
                            "not cash. % = futures notional as a share of capital: 100% = Rs 20L notional on Rs 20L (about 1 lot).",
                      test="Alone 2017-26: about 8%/yr at realistic fills, worst fall -12.5%; moves against stocks (correlation -0.1 to -0.2), "
                           "so it cuts the book's worst fall from -21% to -16%. Bot stays in DRY RUN until you switch it."))
    return B


_BOARDS = {}


def load(p):
    """17 Nov 2026: the scans now include NSE SME and liquid BSE-only stocks; they stay in the scan lists (Momentum, Trading,
    Bottoms) but are left out of the trade plan: SME trades in fixed lots and BSE-only can't be sent through Angel's NSE
    route, and neither was in the backtests."""
    try:
        d = json.load(open(p))
    except Exception:  # noqa: BLE001
        return {}
    if not _BOARDS and p.endswith(("ath.json", "trend_scan.json", "support.json", "patterns.json", "vcp.json")):
        try:
            _BOARDS.update(json.load(open(os.path.join(os.path.dirname(p), "boards.json"))))
        except Exception:  # noqa: BLE001
            _BOARDS["_none"] = "main"
    if isinstance(d, dict) and len(_BOARDS) > 1:
        off = lambda r: isinstance(r, dict) and (_BOARDS.get(r.get("symbol")) in ("SME", "BSE") or r.get("board") in ("SME", "BSE")  # noqa: E731
                                                 or str(r.get("symbol", "")).endswith(".BO"))
        d = {k: ([r for r in v if not off(r)] if isinstance(v, list) else v) for k, v in d.items()}
    return d


def num(v):
    try:
        v = float(v)
        return v if np.isfinite(v) else None
    except Exception:  # noqa: BLE001
        return None


MOM_VOL_X = 1.5     # 26 Nov 2026: Momentum breakout candle must trade >= 1.5x its 50-day average volume
LANE_ORD = {"build": 0, "hold": 1, "mid": 2, None: 3, "bounce": 4, "fade": 5, "weak": 6}
LANE_SKIP = ("weak", "fade", "bounce")
LANE_NAME = {"weak": "Weak", "fade": "Fading", "bounce": "Turning / weak-bouncing"}


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
    C = []; missed = []

    def td(r):
        return dict(sector=secname(r.get("sector_index")), sector_rs=num(r.get("sector_rs")), theme=secname(r.get("theme")),
                    theme_rs=num(r.get("theme_rs")), stock_rs=num(r.get("stock_rs")), aligned=bool(r.get("aligned")),
                    td_score=r.get("td_score"), rs_rating=r.get("rs_rating"), sector_pct=r.get("sector_pct"), theme_pct=r.get("theme_pct"))

    for r in ath.get("breakouts") or []:
        if r.get("status") != "open":
            continue
        entry, close, stop = num(r.get("entry")), num(r.get("close")), num(r.get("sma30"))
        if not entry or not close or not stop or close <= stop:
            continue
        late = close / entry - 1
        if late > MAX_LATE or late < -MAX_BELOW:   # fresh breakouts only: near the price the backtest bought
            if (r.get("base_months") or 0) >= BASE_MAIN or r.get("tf_status", "open") == "open":   # Today's "missed" list (11 Nov 2026)
                missed.append(dict(symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH" if (r.get("base_months") or 0) >= BASE_MAIN else TF_SYS,
                                   date=r.get("date"), entry=round(entry, 2), ref=close, late_pct=round(late * 100, 1), base_months=r.get("base_months"),
                                   why=(f"ran {late * 100:+.1f}% past the breakout entry: the tests bought within +{MAX_LATE * 100:.0f}%, so skip it"
                                        if late > 0 else f"back {late * 100:.1f}% below the entry: a failing breakout, skip it")))
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
                          base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), entry0=round(entry, 2), late_pct=round(late * 100, 1), **t))
            continue
        C.append(dict(id=f"ATH-{r['symbol']}-{r.get('date')}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", bucket="mom",
                      kind="ATH_BRK", order="LIMIT", when="next open", side="BUY", price=round(close * 1.01, 2), ref=close,
                      stop=round(stop, 2), exit_rule="weekly close below the 30-week SMA",
                      note=f"{'close ' if r.get('kind') == 'close' else ''}breakout {r.get('date')}, base {r.get('base_months')} m, "
                           f"{late * 100:+.1f}% vs entry {entry:.2f}",
                      base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), entry0=round(entry, 2), late_pct=round(late * 100, 1), **t))
    for r in ath.get("near") or []:
        trig, close, stop = num(r.get("trigger")), num(r.get("close")), num(r.get("sma30"))
        if not trig or not stop or trig <= stop:
            continue
        t = td(r)
        if r.get("kind") == "wait":   # 25 Nov 2026: traded near/above the level but no confirming daily close yet -> watch only
            lvl = num(r.get("level")) or trig; wick_rule = (r.get("base_months") or 0) < BASE_MAIN
            C.append(dict(id=f"WAIT-{r['symbol']}", symbol=r["symbol"], name=r.get("name", ""), system=TF_SYS if wick_rule else "Monthly ATH",
                          bucket="tf" if wick_rule else "mom", kind="WATCH", order=None, when="daily close", side="BUY", price=round(lvl, 2), ref=close,
                          stop=round(stop, 2), note=(f"waiting for a daily CLOSE above {lvl:.2f} ({'the highest wick so far' if wick_rule else 'the ATH-month high'}), "
                                                      f"then buy next session above that day's high + 0.15%"),
                          base_months=r.get("base_months"), score=-99, value_cr=num(r.get("value_cr")), **t))
            continue
        if r.get("kind") == "confirm":   # 25 Nov 2026: confirmed at the last close -> buy-stop for the NEXT session only
            sc = 3 + (1 if r.get("main") else 0)
            if india:
                sc += (2 if t["aligned"] else 0) + (1 if (t["theme_rs"] or 0) > 0 else 0) - (3 if t["stock_rs"] is not None and t["stock_rs"] <= 0 else 0)
            lvl = num(r.get("level")) or trig
            if (r.get("base_months") or 0) < BASE_MAIN:
                s9 = min(num(r.get("ema21")) or trig * 0.96, trig * 0.96)
                C.append(dict(id=f"TFCONF-{r['symbol']}-{trig}", symbol=r["symbol"], name=r.get("name", ""), system=TF_SYS, bucket="tf",
                              kind="TF_STOP", order="STOPLOSS_LIMIT", when="next session only (lapses if not triggered)", side="BUY",
                              trigger=round(trig, 2), price=round(trig * 1.01, 2), ref=close, stop=round(s9, 2),
                              exit_rule="daily close with EMA 9 below EMA 21 -> sell next open",
                              note=f"closed above the wick high {lvl:.2f}; buy above today's high + 0.15% = {trig:.2f}, cup {r.get('base_months')} m; stop = EMA 21 (min 4%)",
                              base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
            elif india and r.get("vol_x") is not None and float(r["vol_x"]) < MOM_VOL_X:
                # 26 Nov 2026 (Amritpal: "breakout candle volume should be extraordinary"; tools/research/breakout_volume_test.py):
                # Momentum confirms on less than 1.5x the 50-day volume are skipped. NSE 2017-26 with the lane: 31.0%/yr, worst fall
                # -23.4% vs 28.9% / -30.0%; since 2024 +7.0% a trade vs +3.0%. Cup 9/21 keeps no volume rule (it lowered its return).
                C.append(dict(id=f"CONF-{r['symbol']}-{trig}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", kind="WATCH",
                              order=None, when="daily close", side="BUY", price=round(trig, 2), ref=close, stop=round(stop, 2), vol_skip=True,
                              note=f"closed above the ATH-month high {lvl:.2f} on only {float(r['vol_x']):.1f}x the 50-day volume - "
                                   f"skipped (Momentum needs {MOM_VOL_X:g}x on the breakout candle)",
                              base_months=r.get("base_months"), score=-99, value_cr=num(r.get("value_cr")), **t))
            else:
                C.append(dict(id=f"CONF-{r['symbol']}-{trig}", symbol=r["symbol"], name=r.get("name", ""), system="Monthly ATH", bucket="mom",
                              kind="ATH_STOP", order="STOPLOSS_LIMIT", when="next session only (lapses if not triggered)", side="BUY",
                              trigger=round(trig, 2), price=round(trig * 1.01, 2), ref=close, stop=round(stop, 2),
                              exit_rule="weekly close below the 30-week SMA",
                              note=f"closed above the ATH-month high {lvl:.2f}; buy above today's high + 0.15% = {trig:.2f}, base {r.get('base_months')} m",
                              base_months=r.get("base_months"), score=sc, value_cr=num(r.get("value_cr")), **t))
            continue
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
        # 25 Nov 2026 (Amritpal: "be in the right sector", OK after the portfolio check): India Cup 9/21 + Momentum buys skip industries
        # in the Weak / Fading / Weak-bouncing ("Turning") lanes. Test NSE 2008-26 with the close-confirm entries, one 10-slot pool:
        # 20.5%/yr vs 17.9%, 2021-26 39.2% vs 31.4%, max DD -20.9% vs -18.2% (claude/pulse-lane-filter-close-confirm-test.md).
        if india and c.get("bucket") in ("tf", "mom") and c.get("kind") != "WATCH" and c["lane"] in LANE_SKIP:
            c.update(kind="WATCH", order=None, score=-99, lane_skip=True,
                     note=f"not bought: its industry ({c['group']}) is in the {LANE_NAME[c['lane']]} lane - the test skips these. " + c.get("note", ""))
    if india:
        # 21 Nov 2026 (Amritpal: "All 3"): first tiebreak after the score = the industry's latest results season
        # (share of its stocks with profit > 20% y/y + half the share accelerating; data/scan/results_season.json).
        # Tested 2016-26 as the ATH buying order (10 equal, no RED buys): 25.2% CAGR vs random 24.7%, 3-month strength 23.2%,
        # best in every window (last 1/3/5 y 18/21/25% vs 16/18/24%); same max DD. Project doc rank-by-industry-test.md.
        RSN = load(D + "results_season.json").get("rows") or []
        rsc = {r["basic"]: (r.get("strong") or 0) + 0.5 * (r.get("accel") or 0) for r in RSN if r.get("strong") is not None}
        med = float(np.median(list(rsc.values()))) if rsc else 0.0
        basic = {m["symbol"]: r["basic"] for r in ((G.get("nse") or {}).get("rows") or []) for m in r.get("members") or []}
        for c in best.values():
            b = basic.get(c["symbol"])
            c["results_score"] = round(rsc[b], 2) if b in rsc else None
            c["results_ind"] = b
        C = sorted(best.values(), key=lambda c: (-c["score"], -(c["results_score"] if c["results_score"] is not None else med),
                                                  LANE_ORD[c["lane"]], -(c["stock_rs"] or -999), -(c["value_cr"] or 0)))
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
            # 25 Nov 2026: only the breakout of the last close, bought next session above that candle's high + 0.15%
            if r.get("kind") != "stock" or r.get("status") != "breakout" or (r.get("days_since") or 0) > 0 or not r.get("takeout") or r["symbol"] in best:
                continue
            close, stop, neck = num(r.get("close")), num(r.get("stop")), num(r.get("neck"))
            if not close or not stop or not neck or close <= stop or close < MINPX[mk]:
                continue
            TK = num(r.get("takeout")); E = round(TK * 1.01, 2); tgt = round(neck * (1 + (r.get("height_pct") or 0) / 100), 2)
            if (E - stop) / E > 0.20 or (tgt - E) < (E - stop):          # skip stops > 20% away and targets under 1R
                continue
            g, ln, gp, gr = lane_of(r["symbol"])
            if ln in ("weak", "fade", "bounce"):
                continue
            best[r["symbol"]] = dict(id=f"PAT-{r['symbol']}-{r.get('signal_date')}", symbol=r["symbol"], name=r.get("name", ""), system="Bottom pattern", bucket="pt",
                                     kind="PAT_STOP", order="STOPLOSS_LIMIT", when="next session only (lapses if not triggered)", side="BUY", trigger=TK,
                                     price=E, ref=close, stop=round(stop, 2), target=tgt,
                                     exit_rule=f"measured-move target {tgt:.2f} or the stop, max 120 days", experimental=True,
                                     note=f"{PN.get(r.get('typ'), r.get('typ'))} broke the neckline {neck:.2f} on {r.get('signal_date')} · experimental: worse than random in the {mk} backtest",
                                     score=0, value_cr=None, sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                                     group=g, lane=ln, group_pulse=gp, group_rank=gr)
    if india:
        # 26 Nov 2026 (Amritpal: "Yes" - make Flags automatable so live matches the tested New mix, Flags 20%): the live flag rule
        # (tight <= 8%, volume dries up, breakout candle >= 1.5x the 50-day average, room >= 0.8 x pole) on the LAST close only.
        # Tested: buy the breakout close, stop the flag low, sell after a daily close below the 21-day EMA (+3.2% a trade, 1,151
        # trades 2016-26). Live: a limit at the next open, at most 3% over that close (the app's chase rule). Starts at 0%.
        for r in load(D + "flags.json").get("rows") or []:
            if r.get("kind", "stock") != "stock" or r.get("status") != "breakout" or (r.get("days_since") or 0) > 0 or r["symbol"] in best:
                continue
            close, stop = num(r.get("close")), num(r.get("stop"))
            if not close or not stop or close <= stop or close < MINPX[mk] or (close - stop) / close > 0.20:
                continue
            g0 = GS.get(r["symbol"]); x0 = LN.get(g0[0]) if g0 else None
            g, ln, gp, gr = (g0[0] if g0 else None, x0[0] if x0 else None, x0[1] if x0 else None, x0[2] if x0 else None)
            best[r["symbol"]] = dict(id=f"FL-{r['symbol']}-{r.get('bo_date')}", symbol=r["symbol"], name=r.get("name", ""), system="Flag breakout", bucket="fl",
                                     kind="FLAG", order="LIMIT", when="next open", side="BUY", price=round(close * 1.01, 2), ref=close, stop=round(stop, 2),
                                     target=num(r.get("target")), exit_rule="sell next open after a daily close below the 21-day EMA; stop at the flag low",
                                     note=f"{r.get('shape') or 'Flag'} breakout {r.get('bo_date')} on {r.get('bo_vol_x')}x volume, pole +{r.get('pole_pct')}%",
                                     score=1, value_cr=None, sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                                     group=g, lane=ln, group_pulse=gp, group_rank=gr)
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
    # VCP watch bucket (10 Nov 2026), all markets: forming setups within 5% of the pivot -> buy-stop; breakouts of the last
    # 2 sessions still within 3% of the entry -> limit. Exits: tested rule (daily close below EMA 50) for anyone holding it.
    vc = load(D + "vcp.json"); vexits = []
    for r in vc.get("rows") or []:
        sym, close, stop, piv = r["symbol"], num(r.get("close")), num(r.get("stop")), num(r.get("pivot"))
        if not close or not stop or not piv or close < MINPX[mk]:
            continue
        if r.get("status") == "exit":
            vexits.append(dict(id=f"EXIT-VCP-{sym}", symbol=sym, system="VCP", side="SELL", order="LIMIT", when="next open", ref=close,
                               why=r.get("exit_why") or "daily close below EMA 50"))
            continue
        if sym in best:
            continue
        cs = " → ".join(f"{c['depth']:.0f}%" for c in r.get("contractions") or [])
        base = dict(symbol=sym, name=r.get("name", ""), system="VCP", bucket="vcp", stop=round(stop, 2), experimental=True,
                    exit_rule="sell after a daily close below EMA 50, or the stop", pivot=piv, contractions=r.get("contractions"),
                    score=0, value_cr=None, sector=None, sector_rs=None, theme=None, theme_rs=None, stock_rs=None, aligned=False, td_score=None,
                    group=None, lane=None, group_pulse=None, group_rank=None)
        if r.get("status") == "confirm":   # 25 Nov 2026: closed above the pivot on volume -> buy-stop for the NEXT session only
            T = num(r.get("trigger"))
            best[sym] = dict(base, id=f"VCP-{sym}-{r.get('setup_date')}-c", kind="VCP_STOP", order="STOPLOSS_LIMIT", when="next session only (lapses if not triggered)",
                             side="BUY", trigger=T, price=round(T * 1.01, 2), ref=close,
                             note=f"VCP {cs}: closed above the pivot {piv:,.2f} on {r.get('bo_vol')}x volume; buy above that day's high + 0.15% = {T:,.2f}")
        elif r.get("status") == "forming" and (r.get("to_pivot_pct") or 99) <= 5:   # 25 Nov 2026: watch until a close above the pivot
            best[sym] = dict(base, id=f"VCP-{sym}-{r.get('setup_date')}", kind="WATCH", order=None, when="daily close", side="BUY",
                             price=round(piv, 2), ref=close, score=-99,
                             note=f"VCP {cs}: waiting for a daily CLOSE above the pivot {piv:,.2f} on 1.4x volume ({r.get('to_pivot_pct')}% above), then buy next session above that day's high + 0.15%")
        elif r.get("status") == "breakout" and (r.get("days_since") or 0) <= 1 and close <= num(r.get("entry")) * 1.03:
            best[sym] = dict(base, id=f"VCP-{sym}-{r.get('bo_date')}", kind="VCP", order="LIMIT", when="next open", side="BUY",
                             price=round(close * 1.01, 2), ref=close,
                             note=f"VCP {cs} broke the pivot {piv:,.2f} on {r.get('bo_date')} on {r.get('bo_vol')}x volume")
    trades = [c for c in best.values() if c.get("bucket") == "mom"]
    trades.sort(key=lambda c: C.index(c))
    KORD = {"TF_BRK": 0, "TF_STOP": 0, "T921": 1, "FLAG": 1, "RETEST": 2, "PATTERN": 3, "PAT_STOP": 3, "VCP": 4, "VCP_STOP": 4}
    swing = sorted([c for c in best.values() if c["kind"] in KORD],
                   key=lambda c: (LANE_ORD[c["lane"]], KORD[c["kind"]], -(c["value_cr"] or 0)))
    if india:   # every Trend 9/21 signal, the best 8 retests
        keep = {id(x) for x in [c for c in swing if c["bucket"] in ("tf", "t9", "fl")] + [c for c in swing if c["kind"] == "RETEST"][:8]
                + [c for c in swing if c["bucket"] == "vcp"][:12]}
        swing = [c for c in swing if id(c) in keep]
    else:   # keep all 9/21, the best 8 retests and 6 patterns, then order the lot top-down (industry lane, then 9/21 > retest > pattern)
        keep = {id(x) for x in [c for c in swing if c["kind"] in ("T921", "TF_BRK", "TF_STOP")] + [c for c in swing if c["kind"] == "RETEST"][:8]
                + [c for c in swing if c["kind"] in ("PATTERN", "PAT_STOP")][:6] + [c for c in swing if c["bucket"] == "vcp"][:12]}
        swing = [c for c in swing if id(c) in keep]
    seen = {}
    for L in (trades, swing):
        for i, c in enumerate(L):
            b = c.get("bucket") if L is swing else "mom"; seen[b] = seen.get(b, 0) + 1
            c["rank"] = seen[b]                          # rank within its system
            c["risk_pct"] = round((c.get("trigger") or c["price"]) / c["stop"] * 100 - 100, 1) if c["stop"] else None
    # 26 Nov 2026 (Amritpal: market + size index gate, "check as per size"; tools/research/size_index_trend_test.py): each Momentum row
    # carries whether the Nifty 500 AND its own size index (Nifty 50 for Nifty 100 stocks, Midcap 150, else Smallcap 250) pass the
    # Pulse trend rules 2-4 (EMA 9 > EMA 21, above a rising 150-day average, within 25% of the 52-week high). The server skips the
    # failing ones only when the Momentum index gate is switched on (Live > Systems & allocation). NSE 2017-26: Momentum 23.4%/yr,
    # worst fall -12.8% with the gate vs 28.9% / -30.0% without.
    idx_gate = {}
    if india:
        try:
            Hh = pd.read_csv(D + "sector_hist.csv.gz", parse_dates=["Date"]).pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index().ffill()
            for k in ("NIFTY 500", "NIFTY 50", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"):
                x_ = Hh[k].dropna(); e9_ = x_.ewm(span=9, adjust=False).mean(); e21_ = x_.ewm(span=21, adjust=False).mean(); s150_ = x_.rolling(150).mean()
                hi_ = x_.rolling(250, min_periods=120).max()
                idx_gate[k] = dict(ok=bool(e9_.iloc[-1] > e21_.iloc[-1] and x_.iloc[-1] > s150_.iloc[-1] and s150_.iloc[-1] > s150_.iloc[-21] and x_.iloc[-1] >= 0.75 * hi_.iloc[-1]),
                                   e921=bool(e9_.iloc[-1] > e21_.iloc[-1]), stage2=bool(x_.iloc[-1] > s150_.iloc[-1] and s150_.iloc[-1] > s150_.iloc[-21]),
                                   from_high=round(float(x_.iloc[-1] / hi_.iloc[-1] - 1) * 100, 1), asof=str(x_.index[-1].date()))
            big = set(pd.read_csv("data/universe/nifty50.csv").Symbol) | set(pd.read_csv("data/universe/niftynext50.csv").Symbol)
            mid = set(pd.read_csv("data/universe/niftymidcap150.csv").Symbol)
            for c_ in trades:
                sz = "large" if c_["symbol"] in big else "mid" if c_["symbol"] in mid else "small"
                ix_ = {"large": "NIFTY 50", "mid": "NIFTY MIDCAP 150", "small": "NIFTY SMALLCAP 250"}[sz]
                bad = [k for k in ("NIFTY 500", ix_) if not idx_gate[k]["ok"]]
                c_.update(size=sz, size_index=ix_, idx_ok=not bad, idx_why=(" and ".join(b_.title() for b_ in bad) + " not trending") if bad else "")
            # 26 Nov 2026 (Amritpal: "Yes" to weekly RSI >= 60 as a gate mode): weekly RSI(14) of the last week COMPLETED before the
            # signal day's week, on the Nifty 500, the stock's size index and its sector index (no sector index -> not blocked).
            # NSE 2017-26 with the lane: Momentum 19.0%/yr, worst fall -5.6% vs 28.9% / -30.0% (tools/research/size_index_trend_test.py)
            asof_ = pd.Timestamp(Hh.index[-1]); wk_end = asof_ + pd.Timedelta(days=(4 - asof_.weekday()) % 7)

            def wrsi(k):
                w_ = Hh[k].dropna().resample("W-FRI").last(); d_ = w_.diff()
                up_ = d_.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn_ = (-d_.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
                r_ = (100 - 100 / (1 + up_ / dn_)); r_ = r_[r_.index < wk_end].dropna()
                return round(float(r_.iloc[-1]), 1) if len(r_) else None
            wr = {k: wrsi(k) for k in Hh.columns}
            for k in idx_gate:
                idx_gate[k]["wrsi"] = wr.get(k)
            SECJ = load(D + "sectors.json"); s_ind, i_ix = SECJ.get("symbols") or {}, SECJ.get("industries") or {}
            for c_ in trades:
                sx = i_ix.get(s_ind.get(c_["symbol"]))
                chk = [("NIFTY 500", wr.get("NIFTY 500")), (c_["size_index"], wr.get(c_["size_index"]))] + ([(sx, wr.get(sx))] if sx and wr.get(sx) is not None else [])
                bad = [f"{k.title()} weekly RSI {v:.0f}" for k, v in chk if v is None or v < 60]
                c_.update(sector_index=sx, rsi_ok=not bad, rsi_why=(", ".join(bad) + " (needs 60)") if bad else "")
        except Exception as ex:  # noqa: BLE001
            print("index gate failed", ex)
    exits = list(vexits)
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
    # 22 Nov 2026 (Amritpal: "try live too with a small allocation"): Pulse rotation - the week's 10 holdings as buy rows (the
    # server skips what you already hold and sizes each at your % / 10) and the stocks dropped on Friday as sells
    if india:
        try:
            PRJ = json.load(open("data/scan/pulse_rot.json"))
            prow = {x["symbol"]: x for x in PRJ.get("rows") or []}
            for sym in PRJ.get("picks") or []:
                x = prow.get(sym) or {}; cl = num(x.get("close"))
                if not cl:
                    continue
                swing.append(dict(id=f"PR-{sym}-{PRJ.get('decided')}", symbol=sym, name="", system="Pulse rotation", bucket="pr", kind="PR",
                                  order="LIMIT", when="next open (Monday after the Friday pick)", side="BUY", price=round(cl * 1.01, 2), ref=cl,
                                  stop=round(cl * 0.80, 2), exit_rule="sold at the Monday open when it leaves the weekly top 20 or its industry drops out",
                                  note=f"industry {x.get('industry')} (top-10% Pulse + Leading/Improving), 3-month {x.get('r3m')}%, rank {x.get('rank')}"
                                       f"{' · NEW this week' if sym in (PRJ.get('buys') or []) else ''}; equal weight; safety stop 20% below",
                                  score=0, value_cr=None, rank=(x.get("rank") or 99), risk_pct=20.0, lane=None, group=x.get("industry")))
            for sym in PRJ.get("sells") or []:
                exits.append(dict(id=f"EXIT-PR-{sym}-{PRJ.get('decided')}", symbol=sym, system="Pulse rotation", side="SELL", order="LIMIT",
                                  when="next open (Monday)", ref=None, why=f"left the Pulse rotation top 20 / its industry dropped out ({PRJ.get('decided')})"))
        except FileNotFoundError:
            pass
        except Exception as ex:  # noqa: BLE001
            print("pulse rotation rows failed", ex)
    # 22 Nov 2026 (Amritpal: morning check "1, 2 and all triggers worldwide"): each India buy row carries its NSE basic industry and
    # up to 30 liquid members, so the server can read the industry's opening gap at 09:09 (pre-open price) - tested skip rule for
    # 9/21 any stock (t9) and Pulse rotation (pr); information for the other systems (claude/morning-check-pulse-rotation-and-systems.md)
    if india:
        try:
            GN = json.load(open("data/scan/group_pulse.json"))["nse"]["rows"]
            S2I = {m["symbol"]: r["basic"] for r in GN for m in r["members"]}
            I2M = {r["basic"]: [m["symbol"] for m in r["members"] if m.get("liquid")][:30] for r in GN}
            for c_ in trades[:30] + swing:
                i_ = S2I.get(c_["symbol"])
                if i_ and len(I2M.get(i_) or []) >= 3:
                    c_["ind"] = i_; c_["ind_members"] = I2M[i_]
                    c_["morning_rule"] = c_.get("bucket") in ("t9", "pr")
        except Exception as ex:  # noqa: BLE001
            print("industry members failed", ex)
    # 18 Nov 2026: 3-month price change of every candidate - the "strongest 3-month gain" pick for the Best 5 card
    # (concentrated 9/21 test: 5 positions at 1% risk, ranked by 3-month strength = about the 10-position return)
    allc = trades[:30] + swing
    r3 = {r["symbol"]: num(r.get("r3m")) for r in (tr.get("rows") or [])}
    if india:
        try:
            import yfinance as yf
            import nse_bhav; nse_bhav.install()  # noqa: E402,E702  20 Nov 2026 (Amritpal: always use bhavcopy): recent NSE sessions from NSE's bhavcopy
            syms = sorted({c["symbol"] for c in allc})
            tick = {s_: s_ + (".BO" if (c_.get("board") == "BSE") else ".NS") for c_ in allc for s_ in [c_["symbol"]]}
            Y = yf.download([tick[s_] for s_ in syms], period="6mo", auto_adjust=True, progress=False, group_by="column", threads=True)["Close"]
            for s_ in syms:
                try:
                    c_ = Y[tick[s_]].dropna() if hasattr(Y, "columns") and tick[s_] in Y.columns else Y.dropna()
                    if len(c_) > 63:
                        r3[s_] = round(float(c_.iloc[-1] / c_.iloc[-64] - 1) * 100, 1)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as ex:  # noqa: BLE001
            print("r3m download failed", ex)
    for c_ in allc:
        c_["r3m"] = r3.get(c_["symbol"])
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), market=mk, watch_only=not india,
               asof=max(str(ath.get("asof") or ""), str(tr.get("asof") or "")),
               rules=dict(risk_pct=1.0, max_pos_pct=20.0, max_positions=10, max_late_pct=MAX_LATE * 100, max_below_pct=MAX_BELOW * 100, top=TOP,
                          limit_buffer_pct=1.0),
               index_gate=idx_gate, buckets=buckets(mk), top=trades[:TOP], more=trades[TOP:30], swing=swing, pattern_watch=pat_watch[:20], watch=[c for c in C if c["kind"] == "WATCH"], exits=exits,
               missed=sorted(missed, key=lambda x: -abs(x["late_pct"]))[:15])
    json.dump(out, open(OUT, "w"), indent=0, default=str)
    print("trade plan:", len(trades), "ATH +", len(swing), "swing, top", [(c["symbol"], c["kind"], c["score"]) for c in trades[:TOP]], "exits", len(exits))


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["NSE"]):
        main(m)
