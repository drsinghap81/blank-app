"""25 Nov 2026 (Amritpal: "are any Top Bottom triggered in stocks on paper trading"): today's plan for the four Top Bottom stock bots
(BEL, L&T, TMPV, TCS - buy only, buffer 0.05%, gap rule 1.5%) recomputed with the bots' own code (tools/angel/tb_live.py) on Yahoo
daily SPOT closes (the bots use the near-month future, so levels differ slightly), and whether today's high has crossed the buy level."""
import os
import sys
from datetime import datetime, timedelta, timezone

import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "angel"))
import tb_live as T  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30)); today = datetime.now(IST).date()
cfg = dict(T.DEFAULT_CFG); cfg.update(long_only=True, buffer_pts=0, buffer_pct=0.05, glitch_pts=0, use_once=True)
for s in ("BEL", "LT", "TMPV", "TCS"):
    x = yf.download(s + ".NS", period="2y", interval="1d", auto_adjust=False, progress=False)
    x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
    x = x.dropna(); live = x.iloc[-1] if x.index[-1].date() == today else None; hist = x.iloc[:-1] if live is not None else x
    st = T.init_flat_state(hist, cfg); p = T.make_plan(hist, st, cfg)
    bl = p["buy_lvl"]; sl = p["sell_lvl"]
    txt = f"R| {s:5s} last close {float(hist.Close.iloc[-1]):,.2f} | top {p['top'] and round(p['top'], 2)} -> BUY above {bl and round(bl, 2)}"
    txt += f" | bottom {p['bot'] and round(p['bot'], 2)} (buy only: no short)"
    if bl is None:
        txt += " | top already used - waiting for a new top"
    if live is not None:
        o, h = float(live.Open), float(live.High)
        if bl and o > bl * 1.015:
            txt += f" | today opened {o:,.2f} > 1.5% beyond the level: no trade (gap rule)"
        elif bl and h > bl:
            txt += f" | TRIGGERED today: high {h:,.2f} > {bl:,.2f} (paper buy ~{max(o, bl):,.2f}), now {float(live.Close):,.2f}"
        else:
            txt += f" | not triggered: today high {h:,.2f}, now {float(live.Close):,.2f}" + (f" ({(bl / float(live.Close) - 1) * 100:.1f}% below the level)" if bl else "")
    print(txt, flush=True)
