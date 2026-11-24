"""Nightly Top Bottom levels for the moomoo markets (24 Nov 2026, Amritpal: "set up moomoo API and enable auto trading like Angel").
Buy only, ETF rules 1/2/2, buffer 0.05% - the tested versions (claude/top-bottom-us-screen.md, claude/top-bottom-asx-etf-test.md).
Writes data/scan/tb_world.json: per market the last session date, and per ETF the last bar, last swing top / bottom and today's
buy-stop level (None when the last top is already spent). The live server (tools/live_server/mm_tb.py) places and trails the orders."""
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "angel"))
import tb_live as tl  # noqa: E402

TZ = {"US": ZoneInfo("America/New_York"), "AU": ZoneInfo("Australia/Sydney")}
MARKETS = {"US": ("", ["QQQ", "SMH", "XLF", "XLE", "XLK", "SLV"]),
           "AU": (".AX", ["TECH", "HACK", "OZR", "QRE", "ASIA", "ACDC", "ATEC", "MNRS", "QFN"])}
CFG = dict(tl.DEFAULT_CFG, buffer_pts=0, buffer_pct=0.05, day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0, long_only=True, event_exit=False)


def one(tk, mk):
    d = yf.download(tk, start="2015-01-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    d = d[["Open", "High", "Low", "Close"]].dropna(); d = d[(d.High >= d.Low) & (d.Low > 0)]
    now = datetime.now(TZ[mk])                       # a session that hasn't closed yet (+20 min) is not a finished bar
    if (now.hour, now.minute) < (16, 20):
        d = d[d.index.date < now.date()]
    if len(d) < 300:
        return None
    top, bot = tl.levels(d); st = tl.init_flat_state(d, CFG); p = tl.make_plan(d, st, CFG)
    b = d.iloc[-1]
    return dict(date=str(d.index[-1].date()), open=round(float(b.Open), 4), high=round(float(b.High), 4), low=round(float(b.Low), 4),
                close=round(float(b.Close), 4), top=round(top, 4) if top else None, bot=round(bot, 4) if bot else None,
                buy_lvl=round(p["buy_lvl"], 4) if p["buy_lvl"] else None,
                bot_stop=round(bot * (1 - CFG["buffer_pct"] / 100), 4) if bot else None)


def main():
    out = dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), rules=dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0,
               gap_pct=1.0, buffer_pct=0.05, side="buy only"), markets={})
    for mk, (sfx, syms) in MARKETS.items():
        rows = {}
        for s in syms:
            try:
                r = one(s + sfx, mk)
                if r:
                    rows[s] = r
            except Exception as ex:  # noqa: BLE001
                print("skip", s, ex)
        asof = max((r["date"] for r in rows.values()), default=None)
        out["markets"][mk] = dict(asof=asof, symbols=rows)
        print(mk, asof, {k: v["buy_lvl"] for k, v in rows.items()})
    json.dump(out, open("data/scan/tb_world.json", "w"), indent=1)


if __name__ == "__main__":
    main()
