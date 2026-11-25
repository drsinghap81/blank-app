"""25 Nov 2026: dry check of the new close-confirmation entries in tools/ath_scan.py on a few named stocks (no files written)."""
import os
import sys
from datetime import date

sys.argv = ["ath_scan.py", "NSE"]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402
import ath_scan as A  # noqa: E402

for s in ["AGARWALEYE", "POONAWALLA", "HONASA", "ANGELONE", "TECHM", "SAREGAMA", "LALPATHLAB", "ZYDUSLIFE", "DCBBANK", "DRREDDY", "INDHOTEL", "ASAHIINDIA"]:
    x = yf.download(s + ".NS", period="max", interval="1d", auto_adjust=False, progress=False)
    x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
    ev, nr, _ = A.analyse(s, x[["Open", "High", "Low", "Close", "Volume"]], date.today())
    op = [e for e in ev if e["status"] != "exited"]
    print("R|", s, "| open:", [(str(e["date"].date()), round(e["entry"], 2), round(e["trigger"], 2), e["kind"], e["base_months"]) for e in op][-2:],
          "| near:", nr and {k: (round(v, 2) if isinstance(v, float) else v) for k, v in nr.items() if k in ("kind", "trigger", "level", "close", "ath_high", "base_months")}, flush=True)
