"""Top Bottom PAPER trading on Bitcoin and Ether (27 Nov 2026, Amritpal: "meanwhile can you start paper trading on BTC and ETH top bottom").
No exchange, no account: Yahoo BTC-USD / ETH-USD daily candles (UTC days, 7 a week) through the same engine as the backtest
(tools/topbottom_backtest.run_live, index rules 1/2/2, buffer 0.05%, entry-day stop on the close, 0.1% cost a round trip).
Paper starts FLAT on 27 Nov 2026 (UTC): only trades entered from then count. Two books per coin:
  both sides (what futures would trade)  and  buy only (what spot would trade).
Notional US$10,000 per book, compounded per trade. Trades come from COMPLETED daily candles only; the running day is used just for
the live price / open P&L. Writes paper/crypto_tb.json (read by the app's Bots tab). Run every few hours by .github/workflows/paper-crypto-tb.yml."""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import topbottom_backtest as tbb  # noqa: E402

START = pd.Timestamp("2026-11-27")
RULES = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0)
COST = 0.001
CAP = 10000.0
OUT = os.path.join(os.path.dirname(HERE), "paper", "crypto_tb.json")


def bars(t):
    d = yf.download(t, start="2014-01-01", progress=False, auto_adjust=False, interval="1d")
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    x = d[["Open", "High", "Low", "Close"]].dropna(); return x[(x.High >= x.Low) & (x.Low > 0)]


def book(df_done, last_px, both):
    p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=not both, **RULES)
    t = tbb.run_live(df_done, p)
    c = df_done.Close.to_numpy(float)
    T, B, _ = tbb.confirmed_swings(c, 0.0)
    top, bot = T[-1], B[-1]
    t = t[pd.to_datetime(t.EntryDate) >= START] if len(t) else t
    closed = t[~t.Open] if len(t) else t
    eq = CAP; rows = []
    for _, r in closed.iterrows():
        ret = r.Pct / 100 - COST; pnl = eq * ret; eq += pnl
        rows.append(dict(side=r.Side, entry_date=str(pd.Timestamp(r.EntryDate).date()), entry=round(float(r.Entry), 2),
                         exit_date=str(pd.Timestamp(r.ExitDate).date()), exit=round(float(r.Exit), 2), why=str(r.Reason),
                         pct=round(ret * 100, 2), pnl=round(pnl, 2)))
    pos = None
    op = t[t.Open] if len(t) else t
    if len(op):
        r = op.iloc[-1]; side = 1 if r.Side == "BUY" else -1; ent = float(r.Entry)
        since = df_done[df_done.index >= pd.Timestamp(r.EntryDate)]
        prot = ent * (1 - side * RULES["max_sl_pct"] / 100)
        if side > 0 and not np.isnan(bot):
            prot = max(prot, bot * (1 - 0.0005))
        if side < 0 and not np.isnan(top):
            prot = min(prot, top * (1 + 0.0005))
        fav = ((since.High.max() - ent) / ent if side > 0 else (ent - since.Low.min()) / ent) * 100 if len(since) else 0
        if fav >= RULES["be_pct"]:
            prot = max(prot, ent) if side > 0 else min(prot, ent)
        upnl = eq * (side * (last_px / ent - 1))
        pos = dict(side=r.Side, entry_date=str(pd.Timestamp(r.EntryDate).date()), entry=round(ent, 2), stop=round(prot, 2),
                   open_pct=round(side * (last_px / ent - 1) * 100, 2), open_pnl=round(upnl, 2))
    buy_lvl = round(top * 1.0005, 2) if not np.isnan(top) else None
    sell_lvl = round(bot * (1 - 0.0005), 2) if (both and not np.isnan(bot)) else None
    wins = sum(1 for x in rows if x["pnl"] > 0)
    return dict(equity=round(eq, 2), ret_pct=round((eq / CAP - 1) * 100, 2), n=len(rows), wins=wins, trades=rows[::-1][:30], pos=pos,
                buy_lvl=None if pos else buy_lvl, sell_lvl=None if pos else sell_lvl, top=None if np.isnan(top) else round(top, 2),
                bot=None if np.isnan(bot) else round(bot, 2))


def main():
    now = datetime.now(timezone.utc); today = pd.Timestamp(now.date())
    out = dict(updated=now.strftime("%Y-%m-%dT%H:%M:%SZ"), start=str(START.date()), capital=CAP, rules="index 1/2/2, buffer 0.05%, cost 0.1%",
               note="Paper only - no orders. Daily UTC candles; trades from completed days.", coins={})
    for tk, nm in (("BTC-USD", "BTC"), ("ETH-USD", "ETH")):
        df = bars(tk)
        done = df[df.index < today]
        print(nm, 'last rows:', [(str(i.date()), round(float(c), 2)) for i, c in df.Close.tail(3).items()], flush=True)
        last = float(df.Close.iloc[-1])
        out["coins"][nm] = dict(price=round(last, 2), last_day=str(done.index[-1].date()),
                                both=book(done, last, True), buy=book(done, last, False))
        print(nm, last, {k: (v["n"], v["ret_pct"], bool(v["pos"])) for k, v in out["coins"][nm].items() if isinstance(v, dict)})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)


if __name__ == "__main__":
    main()
