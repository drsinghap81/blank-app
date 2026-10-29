"""Intraday watcher for the monthly ATH system (NSE market hours, every ~15 min via GitHub Actions).
Reads tonight's plan (data/scan/ath.json) and checks ~15-min-delayed Yahoo prices for:
  - near-trigger stocks: today's high above the trigger  -> BREAKOUT alert (buy-stop level, shares for your capital)
  - open positions with the add armed: high above the add level -> ADD alert
  - open positions: price below the 30-week SMA (warning only; the exit is the weekly CLOSE)
Writes data/live/ath_live.json (prices for the app, pushed to the 'live' branch) and sends each alert once a day
to WhatsApp/Telegram (tools/notify.py). Capital for share counts: env ALERT_CAPITAL (default Rs 20,00,000)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send  # noqa: E402

PLAN = "data/scan/ath.json"
OUT = "data/live"
SENT = f"{OUT}/ath_sent.json"
CAP = float(os.environ.get("ALERT_CAPITAL") or 2_000_000)


def shares(e, sma, held=0.0):
    if not e or not sma or e <= sma:
        return 0
    return max(0, int(min(0.02 * CAP * e / (e - sma), 0.2 * CAP - held * e) // e))


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    force = os.environ.get("FORCE") == "1"
    if not force and (now.weekday() > 4 or not (9 * 60 + 15 <= now.hour * 60 + now.minute <= 15 * 60 + 40)):
        print("outside NSE hours", now); return
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(PLAN))
    near = plan.get("near") or []
    opn = [r for r in (plan.get("tracked") or []) if r.get("status") == "open"]
    syms = sorted({r["symbol"] for r in near} | {r["symbol"] for r in opn})
    if not syms:
        print("nothing to watch"); return
    d = yf.download([s + ".NS" for s in syms], period="5d", interval="1d", auto_adjust=False, progress=False,
                    group_by="column", threads=True)
    today = pd.Timestamp(now.date())
    live = {}
    for s in syms:
        try:
            x = pd.DataFrame({k: d[k][s + ".NS"] for k in ("High", "Low", "Close")}).dropna()
        except Exception:  # noqa: BLE001
            continue
        if not len(x) or x.index[-1].normalize() != today:
            continue
        live[s] = dict(price=round(float(x.Close.iloc[-1]), 2), high=round(float(x.High.iloc[-1]), 2),
                       low=round(float(x.Low.iloc[-1]), 2))
    try:
        sent = json.load(open(SENT))
    except Exception:  # noqa: BLE001
        sent = {}
    if sent.get("date") != str(now.date()):
        sent = {"date": str(now.date()), "keys": []}
    alerts = []
    for r in near:
        q = live.get(r["symbol"]); k = f"brk:{r['symbol']}"
        if q and q["high"] > r["trigger"] and k not in sent["keys"]:
            sh = shares(r["trigger"], r.get("sma30"))
            alerts.append(f"🟢 BREAKOUT {r['symbol']}: traded above the ATH-month high {r['trigger']:,.2f} (now {q['price']:,.2f}). "
                          f"Base {r['base_months']} months. Plan: buy {sh:,} shares at ~{r['trigger']:,.2f}; exit on a weekly close "
                          f"below the 30-week SMA ({r.get('sma30') or 0:,.2f}).")
            sent["keys"].append(k); live[r["symbol"]]["event"] = "breakout"
    for r in opn:
        q = live.get(r["symbol"])
        if not q:
            continue
        if r.get("add_status") == "armed" and r.get("add_level") and q["high"] > r["add_level"]:
            k = f"add:{r['symbol']}"
            if k not in sent["keys"]:
                sh0 = shares(r["entry"], r.get("sma_entry") or r.get("sma30"))
                sh = shares(r["add_level"], r.get("sma30"), sh0)
                alerts.append(f"➕ ADD {r['symbol']}: above {r['add_level']:,.2f} (highest since entry; now {q['price']:,.2f}). "
                              f"Plan: add {sh:,} shares (first buy was {sh0:,}), keeping the stock ≤ 20% of capital.")
                sent["keys"].append(k); live[r["symbol"]]["event"] = "add"
        if r.get("sma30") and q["price"] < r["sma30"]:
            k = f"sma:{r['symbol']}"
            if k not in sent["keys"]:
                alerts.append(f"⚠️ {r['symbol']} is below its 30-week SMA {r['sma30']:,.2f} (now {q['price']:,.2f}). "
                              "Not an exit yet — the exit is a weekly CLOSE below it (Friday).")
                sent["keys"].append(k); live[r["symbol"]]["event"] = "below_sma"
    out = dict(time=now.strftime("%Y-%m-%d %H:%M IST"), delayed_min=15, prices=live)
    json.dump(out, open(f"{OUT}/ath_live.json", "w"), indent=0)
    json.dump(sent, open(SENT, "w"))
    print(len(live), "prices,", len(alerts), "alerts")
    if alerts:
        send(f"Monthly ATH alerts {now:%d %b %H:%M} IST (prices ~15 min delayed)\n\n" + "\n\n".join(alerts))


if __name__ == "__main__":
    main()
