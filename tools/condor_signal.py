"""Neutral option setup watch: "pause after a big move" iron condor (tested on Nifty weekly options 2019-26,
claude/quiet-market-condor-test.md in the project).

Rule: index moved >= 3.5% (up or down) over the last 10 trading days AND the last 3 days' high-low range < 2%
-> sell an iron condor with short strikes ~2% from the price and 1% wings, entered 2-4 trading days before a weekly
expiry, held to expiry. Nifty test: ~7 trades a year, 89% win, avg +Rs 793 per lot, worst -Rs 5.2k (t 3.8).

Writes data/scan/condor_signal.json for the app (Today card) and the live server (phone alerts). Watch only: the user
places every order himself. Other indices use the same rule but are NOT backtested (labelled in the app)."""
import json
import math
import os
from datetime import date, datetime, timedelta, timezone

import yfinance as yf

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "scan", "condor_signal.json")
MOVE, PAUSE, SHORT, WING = 0.035, 2.0, 0.02, 0.01
# key, name, yahoo, market, weekly expiry weekday (0=Mon; None = daily expiries), strike step, lot, how to trade it, tested
IDX = [   # grade from the 2010-26 test (research/condor_world.json): good = alert, weak/fail = shown only
    ("NIFTY", "Nifty 50", "^NSEI", "NSE", 1, 50, 65, "NSE options (Angel)", "good", "real prices 2019-26: 89% win, t 3.8; model 2010-26: 87% win, 14/17 years up"),
    ("SENSEX", "Sensex", "^BSESN", "NSE", 3, 100, 20, "BSE options (Angel)", "good", "model 2010-26: 88% win, t 2.8, 13/17 years up"),
    ("SX5E", "Euro Stoxx 50", "^STOXX50E", "EU", 4, 25, 10, "Eurex weekly options (not on your brokers)", "good", "model 2010-26: 85% win, t 2.5, 12/17 years up (no vol index: rough)"),
    ("SPX", "S&P 500", "^GSPC", "US", None, 5, 100, "SPY or SPX options (moomoo), daily expiries", "weak", "model 2010-26: +0.02% a trade, t 0.7, 7/16 years up: no real edge"),
    ("NDX", "Nasdaq 100", "^NDX", "US", None, 25, 100, "QQQ options (moomoo), daily expiries", "weak", "model 2010-26: t 1.1, 10/17 years up: weak"),
    ("RUT", "Russell 2000", "^RUT", "US", 4, 5, 100, "IWM options (moomoo)", "weak", "model: positive 2010-18, negative 2019-26"),
    ("DAX", "DAX", "^GDAXI", "EU", 4, 50, 5, "Eurex weekly options (not on your brokers)", "weak", "model: t 1.35, flat since 2019"),
    ("N225", "Nikkei 225", "^N225", "ASIA", 4, 125, 1000, "Osaka weekly options (not on your brokers)", "weak", "model: t 1.3, 12/17 years up"),
    ("HSI", "Hang Seng", "^HSI", "ASIA", 4, 100, 50, "HKEX weekly options (not on your brokers)", "fail", "model: loses money with the signal (5/17 years up)"),
]


def tdays_between(a, b):
    """Weekdays after a up to and including b (holidays ignored)."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def next_expiry(last, wd):
    if wd is None:                      # daily expiries: pick the one 3 trading days out
        d, n = last, 0
        while n < 3:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return d
    d = last + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


def rnd(x, step, up):
    return (math.ceil(x / step) if up else math.floor(x / step)) * step


def main():
    prev = {}
    try:
        prev = {r["key"]: r for r in json.load(open(OUT)).get("rows", [])}
    except Exception:  # noqa: BLE001
        pass
    rows = []
    for key, name, yh, mk, wd, step, lot, how, grade, gnote in IDX:
        tested = grade == "good"
        try:
            h = yf.download(yh, period="3mo", interval="1d", auto_adjust=False, progress=False)
            if hasattr(h.columns, "levels"):
                h.columns = h.columns.get_level_values(0)
            h = h.dropna(subset=["Close"])
            c, hi, lo = h["Close"].values, h["High"].values, h["Low"].values
            last = h.index[-1].date()
        except Exception as e:  # noqa: BLE001
            rows.append(dict(key=key, name=name, market=mk, status="no data", error=str(e)[:100])); continue
        if len(c) < 15:
            continue
        mv = c[-1] / c[-11] - 1
        rg = (hi[-3:].max() - lo[-3:].min()) / c[-1] * 100
        exp = next_expiry(last, wd); dte = tdays_between(last, exp)
        big, pause, window = abs(mv) >= MOVE, rg < PAUSE, 2 <= dte <= 4
        if big and pause and window:
            status = "ON"
        elif big and pause:
            status = "wait"            # setup there, entry window not open (too far from / too close to expiry)
        elif big:
            status = "watch"           # big move, no pause yet
        else:
            status = "off"
        px = float(c[-1])
        sc, sp = rnd(px * (1 + SHORT), step, True), rnd(px * (1 - SHORT), step, False)
        lc, lp = rnd(px * (1 + SHORT + WING), step, True), rnd(px * (1 - SHORT - WING), step, False)
        p = prev.get(key, {})
        since = p.get("on_since") if status == "ON" and p.get("status") == "ON" else (last.isoformat() if status == "ON" else None)
        rows.append(dict(key=key, name=name, market=mk, how=how, tested=tested, grade=grade, grade_note=gnote, date=last.isoformat(), close=round(px, 2),
                         move10=round(mv * 100, 2), range3=round(rg, 2), expiry=exp.isoformat(), expiry_day=exp.strftime("%a %d %b"),
                         days_to_expiry=dte, status=status, on_since=since,
                         short_call=sc, short_put=sp, long_call=lc, long_put=lp, step=step, lot=lot))
    order = {"ON": 0, "wait": 1, "watch": 2, "off": 3, "no data": 4}
    rows.sort(key=lambda r: ({"good": 0, "weak": 1, "fail": 2}.get(r.get("grade"), 3), order.get(r["status"], 9), r["key"]))
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               rule=f"Index moved {MOVE * 100:.1f}%+ over 10 trading days, then the last 3 days' high-low range is under {PAUSE:.0f}%. "
                    f"Sell an iron condor: short call and put about {SHORT * 100:.0f}% from the price, {WING * 100:.0f}% wings, "
                    "entered 2-4 trading days before a weekly expiry, held to expiry.",
               test="Nifty weekly options, Feb 2019 - Oct 2026, real NSE prices and costs: ~7 trades a year, 89% win, "
                    "avg +Rs 793 per lot, worst -Rs 5.2k, about Rs 5.7k a year per lot (more at today's Nifty level). "
                    "Tight (1%) condors and iron flies lost money with the same signal. All 9 indices 2010-26 (options priced from each "
                    "index's volatility, checked against Nifty's real prices): works on Nifty, Sensex and Euro Stoxx 50; weak on the US "
                    "indices, DAX and Nikkei; fails on Hang Seng. Alerts only for the ones that work.",
               rows=rows)
    json.dump(out, open(OUT, "w"), indent=1)
    for r in rows:
        print(r["key"], r["status"], r.get("move10"), r.get("range3"), r.get("expiry_day"), r.get("days_to_expiry"))


if __name__ == "__main__":
    main()
