"""Top Bottom on SILVER futures (24 Nov 2026, Amritpal: "backtest top bottom on silver futures").
Price: MCX-equivalent rupees per kg built from COMEX front-month silver (Yahoo SI=F, USD/oz) x USD/INR x 32.1507 oz/kg, 2010 -> today.
(MCX bhavcopy history isn't reachable from here; MCX silver = COMEX x USD/INR + import duty, so levels differ when the duty changes,
but daily swings - what Top Bottom trades - track closely.) Roll gaps in SI=F are small (silver contango ~0.5%/2 months).
Engine: tools/topbottom_backtest.run_live, long + short, buffer 0.05% (as Bank Nifty's 25 pts ~ 0.05%), event exits off.
Parameter sets: INDEX (entry-day SL 1%, max SL 2%, breakeven 2%, gap 1%) as the live Bank Nifty bot; STOCK (1.5/3/3); VOL (silver is
~1.7x Bank Nifty's volatility: 1.7/3.4/3.4). Cost 0.05% of price per round trip. Also Bank Nifty futures (bhavcopy) on the same
years for comparison. Newest first, years, bull/bear (price vs its 200-day), ex-Covid. Rs per lot: SILVERMIC 1 kg / SILVERM 5 kg."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402


def yh(t):
    d = yf.download(t, start="2009-01-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d.index = pd.to_datetime(d.index).tz_localize(None); return d


def main():
    s = yh("SI=F"); fx = yh("USDINR=X")["Close"].reindex(s.index).ffill()
    k = fx * 32.1507
    df = pd.DataFrame({c: s[c] * k for c in ("Open", "High", "Low", "Close")}).dropna()
    df = df[(df.High >= df.Low) & (df.Close > 0)]; df = df[df.index >= "2010-01-01"]
    print(f"R| silver Rs/kg {df.index[0].date()} {df.Close.iloc[0]:,.0f} -> {df.index[-1].date()} {df.Close.iloc[-1]:,.0f} ({len(df)} days)", flush=True)
    s200 = df.Close.rolling(200).mean()
    bn = pd.read_csv("data/futures/BANKNIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]]
    bn = bn[bn.index >= "2010-01-01"]
    sets = {"INDEX 1/2/2": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0),
            "STOCK 1.5/3/3": dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5),
            "VOL 1.7/3.4/3.4": dict(day_sl_pct=1.7, max_sl_pct=3.4, be_pct=3.4, gap_pct=1.7)}
    for name, data, extra in (("SILVER", df, {}), ("BANKNIFTY (bhavcopy)", bn, {})):
        for lab, kw in sets.items():
            if name.startswith("BANK") and lab != "INDEX 1/2/2":
                continue
            p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **kw)
            t = tbb.run_live(data, p); t["ExitDate"] = pd.to_datetime(t.ExitDate); t["EntryDate"] = pd.to_datetime(t.EntryDate)
            t["ret"] = t.Pct / 100 - 0.0005                       # % of price per trade after 0.05% cost
            end = t.ExitDate.max()
            def s_(x):
                if not len(x):
                    return "-"
                yrs = max((x.ExitDate.max() - x.EntryDate.min()).days / 365.25, 0.5)
                eq = (1 + x.ret).cumprod(); cagr = (eq.iloc[-1] ** (1 / yrs) - 1) * 100; dd = ((eq / eq.cummax()) - 1).min() * 100
                g, b = x.ret[x.ret > 0].sum(), -x.ret[x.ret < 0].sum()
                return f"n {len(x)} win {(x.ret > 0).mean() * 100:.0f}% PF {g / b if b else 0:.2f} | {cagr:+.1f}%/yr DD {dd:.1f}%"
            print(f"R| {name} | {lab} | ALL {s_(t)}", flush=True)
            for y in (1, 2, 3, 5):
                print(f"R| {name} | {lab} | last {y}y {s_(t[t.ExitDate > end - pd.DateOffset(years=y)])}", flush=True)
            if name == "SILVER":
                bull = t.EntryDate.map(lambda d: bool(df.Close.asof(d) > s200.asof(d)) if np.isfinite(s200.asof(d)) else True)
                print(f"R| {name} | {lab} | long {s_(t[t.Side == 'BUY'])} | short {s_(t[t.Side == 'SELL'])}", flush=True)
                print(f"R| {name} | {lab} | bull {s_(t[bull])} | bear {s_(t[~bull])}", flush=True)
                print(f"R| {name} | {lab} | ex-Covid {s_(t[~((t.EntryDate >= '2020-02-15') & (t.EntryDate < '2021-01-01'))])}", flush=True)
                t["rs1kg"] = t.Points - t.Entry * 0.0005
                yr = t.groupby(t.ExitDate.dt.year).agg(ret=("ret", lambda r: round(((1 + r).prod() - 1) * 100, 1)), rs1kg=("rs1kg", "sum"), n=("ret", "size"))
                print(f"R| {name} | {lab} | years % / Rs per 1 kg lot: " + "; ".join(f"{y}: {r.ret:+.1f}% Rs{r.rs1kg:+,.0f} ({int(r.n)})" for y, r in yr.sort_index(ascending=False).iterrows()), flush=True)
                print(f"R| {name} | {lab} | worst trade {t.ret.min() * 100:.1f}% best {t.ret.max() * 100:.1f}% | max losing streak {int(max((t.ret < 0).astype(int).groupby((t.ret >= 0).cumsum()).sum()))}", flush=True)
            else:
                yr = t.groupby(t.ExitDate.dt.year).ret.apply(lambda r: round(((1 + r).prod() - 1) * 100, 1))
                print(f"R| {name} | {lab} | years % " + "; ".join(f"{y}: {v:+.1f}" for y, v in yr.sort_index(ascending=False).items()), flush=True)
    last = tbb.run_live(df, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **sets["INDEX 1/2/2"]))
    print("R| last silver trades (INDEX):", last.tail(4)[["EntryDate", "Side", "Entry", "ExitDate", "Exit", "Reason", "Pct"]].to_dict("records"), flush=True)


if __name__ == "__main__":
    main()
