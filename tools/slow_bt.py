"""Slower trend systems for US / ASX / NSE stocks, 2017 -> today.
  W   : the 9/21 EMA cross on WEEKLY bars. Signal at the week's close: weekly EMA9 crosses above EMA21, weekly
        Supertrend(10,3) green, close > weekly EMA40 (~200-day) which is rising, weekly RSI >= 55, close >= 70% of the
        52-week high. Buy next open; stop = lowest low of the last 3 weeks (skip if > 20% away); exit when the weekly
        Supertrend turns red (sell next open).
  S30 : Weinstein stage 2. Weekly close crosses above a rising 30-week average and is within 30% of the 52-week high.
        Stop = 4-week low (skip if > 20%); exit on a weekly close below the 30-week average.
  M   : 12-1 month momentum. At each month end rank liquid stocks by the return from 12 months ago to 1 month ago;
        hold the top N equally weighted; keep a holding while it ranks in the top 2N. Variant F goes to cash when
        fewer than half of the stocks are above their 200-day average.
Costs/slippage per market from global_universe.MARKETS. Yahoo data = surviving stocks only (flattering);
market NSE_PIT uses the local point-in-time NSE panel instead (includes delisted stocks).
Usage: python slow_bt.py MARKET [panel.parquet] -> data/slow/<MARKET>.json
"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import MARKETS  # noqa: E402
from trend_bt_global import run, stats, supertrend_dir  # noqa: E402

MINPX = {"NSE": 20.0, "US": 5.0, "ASX": 0.5}
START = "2016-06-01"


# ---------------------------------------------------------------- data
def load_yahoo(market):
    import yfinance as yf
    from global_universe import symbols
    u = symbols(market)
    out = {}
    tick = list(u.ticker)
    for i in range(0, len(tick), 200):
        chunk = tick[i:i + 200]
        d = None
        for _ in range(3):
            try:
                d = yf.download(chunk, start="2015-01-01", auto_adjust=True, progress=False, group_by="column", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", i, e, flush=True); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in chunk:
            try:
                x = pd.DataFrame({"OPEN": d["Open"][t], "HIGH": d["High"][t], "LOW": d["Low"][t], "CLOSE": d["Close"][t],
                                  "VOL": d["Volume"][t]}).dropna()
            except Exception:  # noqa: BLE001
                continue
            x = x[(x.CLOSE > 0) & (x.OPEN > 0)]
            if len(x) < 260:
                continue
            x["VAL"] = x.CLOSE * x.VOL
            out[t] = x.drop(columns="VOL").astype("float32")
        print(market, i + len(chunk), "downloaded", len(out), "kept", flush=True)
        time.sleep(2)
    return out


def load_panel(path, keep=None):
    d = pd.read_parquet(path, columns=["Date", "SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "VALUE"])
    if keep is not None:
        d = d[d.SYMBOL.isin(keep)]
    out = {}
    for s, x in d.groupby("SYMBOL"):
        x = x.set_index("Date").sort_index()
        x = x[(x.CLOSE > 0) & (x.OPEN > 0)]
        if len(x) >= 260:
            out[s] = x.rename(columns={"VALUE": "VAL"})[["OPEN", "HIGH", "LOW", "CLOSE", "VAL"]].astype("float32")
    return out


# ---------------------------------------------------------------- weekly systems -> daily frame for run()
def weekly_frame(sym, x, minval, minpx):
    val20 = x.VAL.rolling(20).mean()
    wk = x.index.to_period("W-FRI")
    last = ~wk.duplicated(keep="last")                       # last trading day of each week
    W = pd.DataFrame({"O": x.OPEN.groupby(wk).first(), "H": x.HIGH.groupby(wk).max(), "L": x.LOW.groupby(wk).min(),
                      "C": x.CLOSE.groupby(wk).last()})
    W["day"] = x.index[last]
    W = W.iloc[:-1] if x.index[-1].weekday() < 4 and len(W) > 1 else W   # drop an unfinished last week
    if len(W) < 60:
        return None
    c = W.C
    e9, e21, e40 = (c.ewm(span=n, adjust=False).mean() for n in (9, 21, 40))
    dl = c.diff()
    up = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    st = pd.Series(supertrend_dir(W.H.values.astype(float), W.L.values.astype(float), c.values.astype(float)), index=W.index)
    hi52 = c.rolling(52, min_periods=26).max()
    sma30 = c.rolling(30).mean()
    n = pd.Series(np.arange(len(W)), index=W.index)
    v = pd.Series(val20.reindex(W.day).values, index=W.index)
    liquid = (v >= minval) & (c >= minpx) & (n >= 40)
    sigW = (e9 > e21) & (e9.shift(1) <= e21.shift(1)) & (st == 1) & (c > e40) & (e40 > e40.shift(4)) & (rsi >= 55) \
        & (c >= 0.7 * hi52) & liquid
    sigS = (c > sma30) & (c.shift(1) <= sma30.shift(1)) & (sma30 > sma30.shift(4)) & (c >= 0.7 * hi52) & liquid
    low3, low4 = W.L.rolling(3).min(), W.L.rolling(4).min()
    exS = np.where(c < sma30, -1, 1)
    res = {}
    for name, sig, ex, stop in (("W", sigW, st.values, low3), ("S30", sigS, exS, low4)):
        f = pd.DataFrame({"sig": sig.values, "st": ex, "low5": stop.values}, index=W.day)
        g = x[["OPEN", "HIGH", "LOW", "CLOSE"]].join(f)
        g["st"] = g.st.ffill().fillna(1).astype("int8")
        g["sig"] = g.sig.fillna(False).astype(bool)
        g["low5"] = g.low5.ffill()
        g["val"] = val20.values
        g = g.reset_index().rename(columns={g.index.name or "index": "Date"})
        g["SYMBOL"] = sym
        res[name] = g
    return res


# ---------------------------------------------------------------- momentum
def momentum(C, O, V, cfg, N, filt, minval, minpx, cap0=2_000_000):
    cost, slip = cfg["cost"], cfg["slip"]
    score = C.ffill().shift(21) / C.ffill().shift(252) - 1
    sma200 = C.rolling(200, min_periods=150).mean()
    above = (C > sma200).sum(1) / sma200.notna().sum(1).replace(0, np.nan)
    hist = C.notna().cumsum()
    dates = C.index
    mend = pd.Series(dates.to_period("M"), index=dates)
    mend = (mend != mend.shift(-1)).values
    cash, hold, last, gone, eq, target = cap0, {}, {}, {}, {}, None
    buys, sells, turn = 0, 0, 0.0
    Cv, Ov = C.values, O.values
    cols = list(C.columns)
    ci = {s: j for j, s in enumerate(cols)}
    for i, dt in enumerate(dates):
        if target is not None:
            e = cash + sum(q * last[s] for s, q in hold.items())
            for s in [s for s in hold if s not in target]:
                px = Ov[i, ci[s]]
                px = last[s] if np.isnan(px) else px
                cash += hold.pop(s) * px * (1 - slip) * (1 - cost / 2); turn += px * 0; sells += 1
            for s in target:
                if s in hold:
                    continue
                px = Ov[i, ci[s]]
                if np.isnan(px):
                    continue
                fill = px * (1 + slip) * (1 + cost / 2)
                q = min(e / N, cash) / fill
                if q <= 0:
                    continue
                cash -= q * fill; hold[s] = q; last[s] = px; buys += 1
            target = None
        for s in list(hold):
            px = Cv[i, ci[s]]
            if np.isnan(px):
                gone[s] = gone.get(s, 0) + 1
                if gone[s] >= 20:
                    cash += hold.pop(s) * last[s] * (1 - slip) * (1 - cost / 2); sells += 1
                continue
            gone[s] = 0; last[s] = px
        eq[dt] = cash + sum(q * last[s] for s, q in hold.items())
        if mend[i] and dt >= pd.Timestamp(START) and i < len(dates) - 1:
            if filt and not (above.iloc[i] >= 0.5):
                target = []
                continue
            ok = (V.iloc[i] >= minval) & (C.iloc[i] >= minpx) & (hist.iloc[i] >= 260) & score.iloc[i].notna()
            sc = score.iloc[i][ok].sort_values(ascending=False)
            rank = {s: k for k, s in enumerate(sc.index)}
            keep = [s for s in hold if rank.get(s, 1e9) < 2 * N]
            new = [s for s in sc.index if s not in keep][: max(0, N - len(keep))]
            target = keep + new
    return pd.Series(eq), dict(buys=buys, sells=sells)


# ---------------------------------------------------------------- main
def summarise(name, curves, extra):
    rows = []
    for eq, T in curves:
        eq = eq[eq.index >= pd.Timestamp(START)]
        a = stats(eq, "2017-01-01", "2030-01-01"); b = stats(eq, "2017-01-01", "2021-12-31"); c = stats(eq, "2022-01-01", "2030-01-01")
        r = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_17_21=b["cagr"], cagr_22_26=c["cagr"])
        if isinstance(T, pd.DataFrame):
            r.update(trades=len(T), win=round((T.pnl > 0).mean() * 100) if len(T) else None,
                     pf=round(T.pnl[T.pnl > 0].sum() / max(-T.pnl[T.pnl < 0].sum(), 1), 2) if len(T) else None,
                     hold_days=float((T.exit - T.entry).dt.days.median()) if len(T) else None)
        else:
            r.update(trades=T["buys"])
        rows.append(r)
    R = pd.DataFrame(rows)
    med = {k: (float(R[k].median()) if R[k].notna().any() else None) for k in R.columns}
    out = dict(system=name, **extra, **med, cagr_min=float(R.cagr.min()), cagr_max=float(R.cagr.max()))
    print(out, flush=True)
    return out, curves[int((R.cagr - R.cagr.median()).abs().values.argmin())][0]


def main():
    market = sys.argv[1]
    base = "NSE" if market == "NSE_PIT" else market
    cfg = MARKETS[base]
    minval, minpx = cfg["min_value"], MINPX[base]
    if market == "NSE_PIT":
        keep = set(pd.read_parquet(sys.argv[3], columns=["SYMBOL"]).SYMBOL.unique()) if len(sys.argv) > 3 else None
        data = load_panel(sys.argv[2], keep)
    else:
        data = load_yahoo(market)
    print("stocks", len(data), flush=True)
    os.makedirs("data/slow", exist_ok=True)
    results, curves = [], {}

    # weekly systems
    frames = {"W": [], "S30": []}
    for s, x in data.items():
        r = weekly_frame(s, x, minval, minpx)
        if r:
            for k in frames:
                frames[k].append(r[k])
    for k, label in (("W", "Weekly 9/21 EMA cross + weekly Supertrend"), ("S30", "30-week average breakout (Weinstein)")):
        d = pd.concat(frames[k], ignore_index=True)
        d = d[d.Date >= pd.Timestamp(START) - pd.Timedelta(days=10)]
        print(k, "signals", int(d.sig.sum()), flush=True)
        for risk in (0.01, 0.015):
            runs = [run(d, cfg, risk=risk, skip=0.20, seed=sd) for sd in range(3)]
            o, eq = summarise(f"{k} {int(risk * 1000) / 10}%", runs, dict(label=label, risk=risk, positions=10))
            results.append(o); curves[o["system"]] = eq
        del d

    # momentum
    C = pd.DataFrame({s: x.CLOSE for s, x in data.items()}).sort_index()
    C = C[C.index >= "2015-01-01"]
    O = pd.DataFrame({s: x.OPEN for s, x in data.items()}).reindex(C.index)
    V = pd.DataFrame({s: x.VAL.rolling(20).mean() for s, x in data.items()}).reindex(C.index)
    for N, filt in ((10, False), (20, False), (20, True)):
        eq, t = momentum(C, O, V, cfg, N, filt, minval, minpx)
        name = f"M{N}{' F' if filt else ''}"
        lbl = f"12-1 month momentum, top {N}, monthly" + (", cash when < 50% of stocks above 200-day" if filt else "")
        o, e = summarise(name, [(eq, t)], dict(label=lbl, positions=N))
        results.append(o); curves[name] = e

    out = dict(market=market, label=cfg["label"], asof=str(date.today()), stocks=len(data), systems=results)
    json.dump(out, open(f"data/slow/{market}.json", "w"), indent=1, default=str)
    pd.DataFrame(curves).to_csv(f"data/slow/{market}_equity.csv")


if __name__ == "__main__":
    main()
