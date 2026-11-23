"""Top Bottom: book profit on a favourable gap? (23 Nov 2026, Amritpal: "if there was a certain profit and the next day gaps up we
should try to book it - check what happened today").
Bank Nifty near-month futures from NSE F&O bhavcopies (data/futures/BANKNIFTY.csv), live rules as the bot (buffer 25, entry-day 1%,
max 2%, breakeven at 2%, gap rule 1%, event exit). Variant: when the trade was >= P% in profit at the previous close and the day
OPENS >= G% further in its favour, exit at the open (flat; next entry on a fresh level). Points per lot, 2 pts cost per trade.
Newest first: last 1/2/3/5 years, each year; bull/bear years (Bank Nifty up / down that year); ex-Covid (drops Mar-Jun 2020).
PILOT env = last 3 years only. Also prints today's Bank Nifty open vs Friday's close (Yahoo ^NSEBANK) when online."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def main():
    df = pd.read_csv("data/futures/BANKNIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]]
    if PILOT:
        df = df[df.index >= df.index[-1] - pd.DateOffset(years=3, months=3)]
    base = dict(buffer_pts=25, gap_pct=1.0, event_exit=True, cost_pts=2)
    yr = df.Close.groupby(df.index.year).agg(["first", "last"]); bull = set(yr.index[yr["last"] > yr["first"]])
    end = df.index[-1]; out = {}
    grid = [None] + [(g, pf) for g in (0.5, 1.0, 1.5) for pf in (0, 1, 2, 3)]
    for v in grid:
        p = tbb.Params(**base) if v is None else tbb.Params(**base, gap_book_pct=v[0], gap_book_profit_pct=v[1])
        t = tbb.run_live(df, p); t["ExitDate"] = pd.to_datetime(t.ExitDate)
        lab = "system as is" if v is None else f"gap >= {v[0]}% & profit >= {v[1]}%"
        r = dict(all=round(t.Points.sum()), trades=len(t), booked=int((t.Reason == "Gap profit booking").sum()),
                 dd=round((t.Points.cumsum() - t.Points.cumsum().cummax()).min()))
        for y in (1, 2, 3, 5):
            r[f"last{y}y"] = round(t[t.ExitDate > end - pd.DateOffset(years=y)].Points.sum())
        r["bull_yrs"] = round(t[t.ExitDate.dt.year.isin(bull)].Points.sum()); r["bear_yrs"] = round(t[~t.ExitDate.dt.year.isin(bull)].Points.sum())
        r["ex_covid"] = round(t[~((t.ExitDate >= "2020-03-01") & (t.ExitDate < "2020-07-01"))].Points.sum())
        r["years"] = {int(k): round(v_) for k, v_ in sorted(t.groupby(t.ExitDate.dt.year).Points.sum().items(), reverse=True)}
        bk = t[t.Reason == "Gap profit booking"]
        r["recent_bookings"] = [f"{d:%d %b %Y} {s} {e:.0f}->{x:.0f} ({pt:+.0f})" for d, s, e, x, pt in zip(bk.ExitDate, bk.Side, bk.Entry, bk.Exit, bk.Points)][-4:]
        out[lab] = r
        print(f"R| {lab} | {r}", flush=True)
    try:
        import yfinance as yf
        d = yf.download("^NSEBANK", period="5d", interval="1d", progress=False, auto_adjust=True)
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        print("R| today ^NSEBANK", d.tail(3).round(1).to_dict("index"), flush=True)
    except Exception as e:  # noqa: BLE001
        print("R| today: no Yahoo here", str(e)[:80])
    os.makedirs("data/research", exist_ok=True)
    pd.Series(out).to_json("data/research/tb_gap_book" + ("_pilot" if PILOT else "") + ".json", indent=1)


if __name__ == "__main__":
    main()
