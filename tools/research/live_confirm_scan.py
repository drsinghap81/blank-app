"""Live check of the close-confirmation rules during the session (25 Nov 2026, Amritpal: "scan stocks as of current market that are
trading now as per these rules"). All NSE stocks, Yahoo daily (today's bar = live, ~15 min delayed).
 1) CONFIRMED at the last close (ath_scan.analyse 'confirm' / VCP 'confirm'): today's buy-stop = that candle's high + 0.15%;
    TRIGGERED if today's high is above it.
 2) Trading ABOVE the level now, not confirmed yet (ath 'wait' level = ATH-month high for Momentum, the wick high for Cup 9/21;
    VCP forming = pivot): would confirm if it closes above the level today, then buy tomorrow above today's high + 0.15%.
No files written."""
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.argv = ["ath_scan.py", "NSE"]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402
import ath_scan as A  # noqa: E402
import pattern_scan as PS  # noqa: E402
from global_universe import symbols  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30)); today = datetime.now(IST).date()
U = symbols("NSE"); tick = list(U.ticker); names = dict(zip(U.ticker, U.get("name", U.ticker)))
if os.environ.get("PILOT"):
    tick = sorted(tick)[:150]
conf, above = [], []
for a in range(0, len(tick), 100):
    ch = tick[a:a + 100]; dd = None
    for _ in range(3):
        try:
            dd = yf.download(ch, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
        except Exception as e:  # noqa: BLE001
            print("retry", e); time.sleep(15)
    if dd is None or dd.empty:
        continue
    for t in ch:
        try:
            x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
        except Exception:  # noqa: BLE001
            continue
        if len(x) < 300:
            continue
        x.index = pd.to_datetime(x.index).tz_localize(None)
        live = x.iloc[-1] if x.index[-1].date() == today else None
        hist = x.iloc[:-1] if live is not None else x
        sym = t.replace(".NS", "")
        if (hist.Close * hist.Volume).tail(20).mean() < 2e7:
            continue
        try:
            ev, nr, _ = A.analyse(sym, hist, today)
        except Exception:  # noqa: BLE001
            ev, nr = [], None
        lp = float(live.Close) if live is not None else None; lh = float(live.High) if live is not None else None
        if nr and nr.get("kind") == "confirm":
            sysn = "Cup 9/21" if nr["base_months"] < A.BASE_MAIN else "Momentum"
            conf.append(dict(sym=sym, sys=sysn, level=nr["level"], buy=nr["trigger"], last=lp, high=lh,
                             st="TRIGGERED" if lh and lh > nr["trigger"] else "not yet"))
        elif nr and nr.get("kind") == "wait" and lp and lp > nr["level"]:
            sysn = "Cup 9/21" if nr["base_months"] < A.BASE_MAIN else "Momentum"
            above.append(dict(sym=sym, sys=sysn, level=nr["level"], last=lp, pct=(lp / nr["level"] - 1) * 100, base=nr["base_months"]))
        try:
            vr = PS.vcp(hist.rename(columns=str), sym, names.get(t, sym))
        except Exception:  # noqa: BLE001
            vr = None
        if vr and vr.get("status") == "confirm":
            conf.append(dict(sym=sym, sys="VCP", level=vr["pivot"], buy=vr["trigger"], last=lp, high=lh, st="TRIGGERED" if lh and lh > vr["trigger"] else "not yet"))
        elif vr and vr.get("status") == "forming" and lp and lp > vr["pivot"]:
            above.append(dict(sym=sym, sys="VCP (needs 1.4x volume)", level=vr["pivot"], last=lp, pct=(lp / vr["pivot"] - 1) * 100, base=None))
    print("R| scanned", a + len(ch), flush=True)
print(f"R| as of {datetime.now(IST).strftime('%H:%M')} IST (Yahoo ~15 min delayed); last completed close = previous session", flush=True)
print(f"R| ===== 1) CONFIRMED at the last close - buy-stop live today ({len(conf)}) =====", flush=True)
for r in sorted(conf, key=lambda r: (r["st"] != "TRIGGERED", r["sys"])):
    print(f"R| {r['sym']:12s} {r['sys']:9s} closed above {r['level']:,.2f} | buy above {r['buy']:,.2f} | today high {r['high'] or 0:,.2f} last {r['last'] or 0:,.2f} | {r['st']}", flush=True)
print(f"R| ===== 2) ABOVE the level now, not confirmed - needs today's CLOSE above it ({len(above)}) =====", flush=True)
for r in sorted(above, key=lambda r: -r["pct"]):
    print(f"R| {r['sym']:12s} {r['sys']:24s} level {r['level']:,.2f} | now {r['last']:,.2f} ({r['pct']:+.1f}%)", flush=True)
