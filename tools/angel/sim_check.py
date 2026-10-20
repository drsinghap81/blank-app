"""Replay history through the LIVE bot logic and compare with the backtest engine.

Each day is turned into a price path (open -> low -> high -> close on up days,
open -> high -> low -> close on down days) and fed tick by tick to TradingDay,
exactly as the live runner feeds it Angel quotes.

    python tools/angel/sim_check.py 2024-01-01            # backtest-style entry-day stop (close)
    python tools/angel/sim_check.py 2024-01-01 intraday   # real 1% stop during the entry day
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import tb_live as tl                      # noqa: E402
import topbottom_backtest as tbb          # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))


class FakeBroker:
    def __init__(self):
        self.px = None
        self.n = 0

    def reference_contract(self, today):
        return "SIMFUT"

    def expiry(self, con):
        return None

    def next_contract(self, con):
        return con

    def lot_size(self, con):
        return 30

    def execute(self, con, side, qty, why, must_fill=False):
        return float(self.px)

    def stop_limit(self, con, side, qty, trig):
        self.n += 1
        return f"BS{self.n}"

    def cancel(self, oid):
        pass


class Quiet:
    def send(self, m):
        pass


class AutoYes:
    def ask(self, key, text):
        pass

    def get(self, key):
        return True


def path(o, h, l, c, steps=60):
    pts = [o, l, h, c] if c >= o else [o, h, l, c]
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        out.extend(np.linspace(a, b, steps, endpoint=False))
    out.append(c)
    return out


def run(start, mode="close", end=None, **over):
    df = pd.read_csv(os.path.join(REPO, "data/futures/BANKNIFTY.csv"), index_col=0, parse_dates=True)[["Open", "High", "Low", "Close"]]
    if end:
        df = df.loc[:end]
    cfg = dict(tl.DEFAULT_CFG, entry_day_sl=mode, dry_run=True, **over)
    st0 = tl.init_flat_state(df[df.index < start], cfg)
    st = st0
    br = FakeBroker()
    days = df.index[df.index >= start]
    for d in days:
        hist = df[df.index < d]
        bar = df.loc[d]
        day = tl.TradingDay(d.date(), hist, st, cfg, br, Quiet(), AutoYes(), log=lambda *a: None)
        day.start()
        hi = lo = None
        first = True
        for px in path(bar.Open, bar.High, bar.Low, bar.Close):
            br.px = px
            hi = px if hi is None else max(hi, px)
            lo = px if lo is None else min(lo, px)
            q = dict(ltp=px, open=bar.Open, high=hi, low=lo)
            if first:
                day.on_open(q)
                first = False
            else:
                day.tick(q)
        day.before_close(dict(ltp=bar.Close, open=bar.Open, high=bar.High, low=bar.Low))
        day.end_of_day(dict(Open=bar.Open, High=bar.High, Low=bar.Low, Close=bar.Close))
    bot = pd.DataFrame(st.trades)
    eng = tbb.run_live(df, tbb.Params(start_flat_on=str(pd.Timestamp(start).date())))
    eng = eng[pd.to_datetime(eng.EntryDate) >= start].reset_index(drop=True)
    return bot, eng


if __name__ == "__main__":
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2024-01-01")
    mode = sys.argv[2] if len(sys.argv) > 2 else "close"
    bot, eng = run(start, mode)
    bot["EntryDate"] = pd.to_datetime(bot.EntryDate)
    eng["EntryDate"] = pd.to_datetime(eng.EntryDate)
    m = bot.merge(eng, on=["EntryDate", "Side"], how="outer", suffixes=("_bot", "_eng"), indicator=True)
    both = m[m._merge == "both"]
    print(f"bot trades {len(bot)} | engine trades {len(eng)} | same date+side {len(both)}")
    print(f"entry price max diff {np.nanmax(np.abs(both.Entry_bot - both.Entry_eng)):.2f} pts")
    print(f"points: bot {bot.Points.sum():,.0f} | engine {eng.Points.sum():,.0f}")
    diff = m[m._merge != "both"][["EntryDate", "Side", "_merge"]]
    if len(diff):
        print("unmatched:\n", diff.to_string(index=False))
