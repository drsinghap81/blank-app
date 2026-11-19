"""Morning metals clue for India (20 Nov 2026; tools/research/asx_metal_filter.py, intermarket.py): ASX 200 Materials vs ASX 200
today so far, written before / soon after India's 09:15 open. > +0.5% = metals favoured, < -0.5% = avoid metal longs. Info only for
the app card; the option trader on the server checks the same thing itself before a metal-stock CE / PE.
Output: data/scan/asx_clue.json"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_server"))
import opt_trader  # noqa: E402

v = opt_trader.asx_clue()
IST = timezone(timedelta(hours=5, minutes=30))
out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), date=str(datetime.now(IST).date()), ist=datetime.now(IST).strftime("%H:%M"), **(v or {}))
if v:
    out["call"] = "metals favoured" if v["diff"] > 0.5 else "avoid metal longs" if v["diff"] < -0.5 else "neutral"
json.dump(out, open("data/scan/asx_clue.json", "w"), indent=1)
print(out)
