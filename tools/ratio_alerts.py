"""Intraday alerts for the Nifty weekly ratio system (runs inside the 15-minute ath-intraday workflow).
Reads the plan published by tools/ratio_weekly.py (data/ratio/ratio_weekly.json) and the Nifty index from Yahoo (~15 min delay).
Alerts (each sent once per expiry):
  - entry window: on the first trading day after the plan's expiry evening, from 14:45 IST, if the week is TRADE -
    strikes re-centred on the live index
  - shift-rule trigger: Nifty at/through a side's long strike (that long is no longer ITM)
  - danger: Nifty within 0.3% of, or beyond, a far breakeven (the side with 5 extra shorts)
Writes data/live/ratio_live.json for the apps. Nothing places orders."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send  # noqa: E402

PLAN, OUT, SENT = "data/ratio/ratio_weekly.json", "data/live/ratio_live.json", "data/live/ratio_sent.json"
ITM_PTS, D1, D2 = 150, 0.0144, 0.0171


def strikes(F):
    r = lambda x: round(x / 50) * 50
    return dict(CE=[r(F - ITM_PTS), r(F * (1 + D1)), r(F * (1 + D2))], PE=[r(F + ITM_PTS), r(F * (1 - D1)), r(F * (1 - D2))])


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    force = os.environ.get("FORCE") == "1"
    mins = now.hour * 60 + now.minute
    if not force and (now.weekday() > 4 or not (9 * 60 + 15 <= mins <= 15 * 60 + 40)):
        print("outside NSE hours"); return
    if not os.path.exists(PLAN):
        print("no plan yet"); return
    p = json.load(open(PLAN))
    if not p.get("expiry") or now.date().isoformat() > p["expiry"]:
        print("plan expired"); return
    h = yf.download("^NSEI", period="2d", interval="5m", progress=False, auto_adjust=False)
    if h is None or h.empty:
        print("no price"); return
    nifty = float(np.ravel(h["Close"].dropna().values)[-1])
    sent = json.load(open(SENT)) if os.path.exists(SENT) else {}
    key = p["expiry"]; done = set(sent.get(key, []))
    legs = (p.get("entered") or {}).get("legs") or p["legs"]
    ce, pe = legs["CE"], legs["PE"]
    far_hi, far_lo = p["legs"]["CE"]["breakeven_far"], p["legs"]["PE"]["breakeven_far"]
    msgs = []
    entry_day = now.date().isoformat() > p["asof"] and not p.get("entered")
    if p["decision"] == "TRADE" and entry_day and mins >= 14 * 60 + 45 and "entry" not in done:
        k = strikes(nifty)
        msgs.append(("entry", f"Nifty weekly ratio - ENTRY WINDOW (expiry {p['expiry']}), Nifty {nifty:.0f}:\n"
                              f"CALL: +1 {k['CE'][0]}CE, -2 {k['CE'][1]}CE, -4 {k['CE'][2]}CE\n"
                              f"PUT:  +1 {k['PE'][0]}PE, -2 {k['PE'][1]}PE, -4 {k['PE'][2]}PE\n"
                              f"Place both before the close. Lot {p.get('lot', 65)} per leg-lot."))
    if p["decision"] == "TRADE" and not entry_day:
        if nifty <= ce["long"] and "shift_CE" not in done:
            msgs.append(("shift_CE", f"Nifty weekly ratio: Nifty {nifty:.0f} reached the CALL long strike {ce['long']:.0f} - shift rule: re-set the call side 150 pts ITM (optional)."))
        if nifty >= pe["long"] and "shift_PE" not in done:
            msgs.append(("shift_PE", f"Nifty weekly ratio: Nifty {nifty:.0f} reached the PUT long strike {pe['long']:.0f} - shift rule: re-set the put side 150 pts ITM (optional)."))
        for side, lvl, beyond in (("hi", far_hi, nifty >= far_hi), ("lo", far_lo, nifty <= far_lo)):
            near = abs(nifty / lvl - 1) <= 0.003
            if beyond and f"beyond_{side}" not in done:
                msgs.append((f"beyond_{side}", f"Nifty weekly ratio DANGER: Nifty {nifty:.0f} is beyond the {'upper' if side == 'hi' else 'lower'} breakeven {lvl:.0f} - 5 net short options on that side. Decide: hold (system rule) or cut."))
            elif near and f"near_{side}" not in done:
                msgs.append((f"near_{side}", f"Nifty weekly ratio: Nifty {nifty:.0f} is within 0.3% of the {'upper' if side == 'hi' else 'lower'} breakeven {lvl:.0f}."))
    for tag, text in msgs:
        print(text)
        if send(text) or force:
            done.add(tag)
    sent[key] = sorted(done)
    os.makedirs("data/live", exist_ok=True)
    json.dump(sent, open(SENT, "w"))
    json.dump(dict(time=now.strftime("%Y-%m-%d %H:%M IST"), nifty=round(nifty, 1), expiry=p["expiry"], decision=p["decision"],
                   entry_day=entry_day, live_strikes=strikes(nifty), far_breakevens=[far_lo, far_hi],
                   long_strikes=dict(CE=ce["long"], PE=pe["long"]), alerts_sent=sorted(done)), open(OUT, "w"), indent=1)


if __name__ == "__main__":
    main()
