"""Monthly all-time-high momentum scanner (NSE), daily Yahoo data over the full history.

System (backtest 2017-Oct 2026, all NSE incl. delisted: 26.9%/yr, worst fall -30%, 10 stocks equal weight):
  trigger : HIGH of the all-time-high closing month (highest monthly close of all completed months)
  entry   : price trades above the trigger during the month -> buy at the trigger (or the open if it gaps above)
            base >= 24 months since that ATH month (>= 12 months shown as secondary), stock above a RISING 30-week SMA
            (higher than 4 weeks earlier) at the last completed week, >= Rs 2 cr/day traded
  exit    : weekly CLOSE below the 30-week SMA -> sell next open
  size    : risk 2% of capital to the 30-week SMA (shares = 2% x capital / (entry - SMA30)), max 20% of capital per stock
  add     : once, after a completed week whose low is within 3% of the SMA30 but closes above it, when price trades above
            the highest high since entry; same 2% risk to the SMA30, total stock <= 20% of capital
Lists written to data/scan/ath.json:
  breakouts : triggered this month or last month, still open
  near      : within 5% below the trigger, base >= 12 months, above the 30-week SMA
  tracked   : every signal of the last 18 months followed with the exit rule (open / exit next open / exited)
Charts: data/scan/ath_charts/SYM.json (monthly bars, full history; weekly bars, last 5 years, with the 30-week SMA).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_scan import nse_symbols, telegram  # noqa: E402

OUT = "data/scan"
CH = f"{OUT}/ath_charts"
MINVAL = 2e7          # Rs 2 cr/day
BASE_MAIN, BASE_MIN = 24, 12
NEAR = 0.05


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o.date())
    return o


def add_state(x, W, Wc, dt, w_entry, exit_dt):
    """One add: after a completed week whose LOW is within 3% of the 30-week SMA (or below) but CLOSES at/above it,
    buy when price trades above the highest high since entry. Returns the add status for the app."""
    end = exit_dt if exit_dt is not None else x.index[-1] + pd.Timedelta(days=1)
    tested_week = None
    for wk_, r in Wc[Wc.index > w_entry].iterrows():
        if wk_.end_time >= end:
            break
        if np.isfinite(r.sma) and r.l <= r.sma * 1.03 and r.c >= r.sma:
            tested_week = wk_
            break
    if tested_week is None:
        return dict(add_status="none", add_level=None, add_date=None, add_price=None, add_sma=None, test_week=None)
    since = x[(x.index >= dt) & (x.index <= tested_week.end_time)]
    hh = float(since.High.max())
    after = x[(x.index > tested_week.end_time) & (x.index < end)]
    for d_, r in after.iterrows():
        if r.High > hh:
            sm = W.sma.shift(1).loc[d_.to_period("W-FRI")]
            return dict(add_status="added", add_level=hh, add_date=d_, add_price=float(max(r.Open, hh)),
                        add_sma=float(sm) if np.isfinite(sm) else None, test_week=str(tested_week.end_time.date()))
    return dict(add_status="armed", add_level=hh, add_date=None, add_price=None, add_sma=None,
                test_week=str(tested_week.end_time.date()))


def analyse(sym, x, today):
    """x: daily OHLCV (DatetimeIndex). Returns (events, near_row or None, chart dict) ."""
    from session import drop_partial
    x = drop_partial(x.dropna(subset=["Close"]))
    x = x[(x.Close > 0) & (x.High > 0)]
    if len(x) < 300:
        return [], None, None
    from adjust import fix_gaps
    o_, h_, l_, c_, v_ = fix_gaps(x.Open, x.High, x.Low, x.Close, x.Volume)
    x = pd.DataFrame({"Open": o_, "High": h_, "Low": l_, "Close": c_, "Volume": v_}, index=x.index)
    val20 = (x.Close * x.Volume).rolling(20, min_periods=10).mean()
    mon = x.index.to_period("M")
    M = pd.DataFrame({"o": x.Open.groupby(mon).first(), "h": x.High.groupby(mon).max(), "l": x.Low.groupby(mon).min(),
                      "c": x.Close.groupby(mon).last()})
    cur_m = mon[-1]
    done = M.index < cur_m                               # completed months
    best = M.c.where(done).cummax()
    isb = (M.c >= best) & done
    k = pd.Series(np.arange(len(M)), index=M.index)
    trig_m = M.h.where(isb).ffill().shift(1)             # trigger valid during each month (completed months only)
    athk = k.where(isb).ffill().shift(1)
    age_m = k - athk
    hist_ok = athk >= 3                                  # ATH month not in the first months of Yahoo history
    runmin = M.c.groupby(isb.cumsum()).cummin()
    depth_m = runmin.shift(1) / best.shift(1) - 1
    ath_month = pd.Series(M.index.astype(str), index=M.index).where(isb).ffill().shift(1)
    # weekly bars + SMA30 (last week may be partial)
    wk = x.index.to_period("W-FRI")
    W = pd.DataFrame({"o": x.Open.groupby(wk).first(), "h": x.High.groupby(wk).max(), "l": x.Low.groupby(wk).min(),
                      "c": x.Close.groupby(wk).last()})
    W["sma"] = W.c.rolling(30, min_periods=30).mean()
    last_complete = W.index[-1] if x.index[-1].weekday() == 4 or (today - x.index[-1].date()).days >= 3 else W.index[-2]
    Wc = W.loc[:last_complete]
    # last completed week: close above SMA30 AND the SMA30 higher than 4 weeks earlier (rising)
    above_prev = ((W.c > W.sma) & (W.sma > W.sma.shift(4))).shift(1)
    # daily mapping
    d = pd.DataFrame({"o": x.Open, "h": x.High, "c": x.Close, "val": val20.values}, index=x.index)
    d["trig"] = trig_m.reindex(mon).values
    d["age"] = age_m.reindex(mon).values
    d["hist_ok"] = hist_ok.reindex(mon).values
    d["depth"] = depth_m.reindex(mon).values
    d["ath_month"] = ath_month.reindex(mon).values
    d["above"] = above_prev.reindex(wk).values
    d["mon"] = mon
    cross = (d.h > d.trig) & (d.hist_ok == True)  # noqa: E712
    first = cross & (cross.groupby(d.mon).cumsum() == 1)
    ev = d[first & (d.above == True) & (d.val >= MINVAL) & (d.age >= BASE_MIN)]  # noqa: E712
    ev = ev[ev.index >= pd.Timestamp(today) - pd.Timedelta(days=550)]
    events = []
    for dt, r in ev.iterrows():
        entry = max(r.o, r.trig)
        w_entry = dt.to_period("W-FRI")
        after = Wc[(Wc.index >= w_entry)]
        brk = after[after.c < after.sma]
        if len(brk):
            ex_w = brk.index[0]
            nxt = x[x.index.to_period("W-FRI") > ex_w]
            if len(nxt):
                status, exit_px, exit_dt = "exited", float(nxt.Open.iloc[0]), nxt.index[0]
            else:
                status, exit_px, exit_dt = "exit next open", None, None
        else:
            status, exit_px, exit_dt = "open", None, None
        last = float(x.Close.iloc[-1])
        ret = (exit_px if exit_px else last) / entry - 1
        sma_entry = float(W.sma.shift(1).loc[w_entry]) if np.isfinite(W.sma.shift(1).loc[w_entry]) else None
        add = add_state(x, W, Wc, dt, w_entry, exit_dt)
        events.append(dict(symbol=sym, date=dt, entry=entry, trigger=r.trig, ath_month=r.ath_month, base_months=int(r.age),
                           depth=r.depth, status=status, exit_date=exit_dt, exit_price=exit_px, close=last,
                           ret=ret, peak=float(x.Close[x.index >= dt].max() / entry - 1),
                           weeks=int(((exit_dt or x.index[-1]) - dt).days / 7), main=bool(r.age >= BASE_MAIN),
                           sma_entry=sma_entry, **add,
                           sma30=float(W.sma.loc[last_complete]) if np.isfinite(W.sma.loc[last_complete]) else None,
                           value_cr=float(r.val) / 1e7))
    # near trigger (current month, not crossed yet)
    near = None
    t_now = d.trig.iloc[-1]
    if np.isfinite(t_now) and d.hist_ok.iloc[-1] and not cross[d.mon == cur_m].any():
        c = float(x.Close.iloc[-1])
        lastw = W.loc[last_complete]
        sma4 = W.sma.shift(4).loc[last_complete]
        if c >= (1 - NEAR) * t_now and d.age.iloc[-1] >= BASE_MIN and np.isfinite(lastw.sma) and lastw.c > lastw.sma \
                and np.isfinite(sma4) and lastw.sma > sma4 \
                and val20.iloc[-1] >= MINVAL:
            near = dict(symbol=sym, trigger=t_now, close=c, gap_pct=(t_now / c - 1) * 100, ath_month=d.ath_month.iloc[-1],
                        base_months=int(d.age.iloc[-1]), depth=d.depth.iloc[-1], sma30=float(lastw.sma),
                        main=bool(d.age.iloc[-1] >= BASE_MAIN), value_cr=float(val20.iloc[-1]) / 1e7)
    Mc = M.tail(240); Wt = W.tail(260)
    chart = dict(m=dict(t=[str(p) for p in Mc.index], o=Mc.o.round(2).tolist(), h=Mc.h.round(2).tolist(),
                        l=Mc.l.round(2).tolist(), c=Mc.c.round(2).tolist()),
                 w=dict(t=[str(p.end_time.date()) for p in Wt.index], o=Wt.o.round(2).tolist(), h=Wt.h.round(2).tolist(),
                        l=Wt.l.round(2).tolist(), c=Wt.c.round(2).tolist(), sma=Wt.sma.round(2).tolist()),
                 trigger=float(t_now) if np.isfinite(t_now) else None, ath_month=d.ath_month.iloc[-1])
    return events, near, chart


def main():
    os.makedirs(CH, exist_ok=True)
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    u = nse_symbols()
    u = u[u.board == "main"] if "board" in u else u
    name = dict(zip(u.symbol, u.name)) if "name" in u else {}
    tick = [s + ".NS" for s in u.symbol]
    print("symbols", len(tick), flush=True)
    events, near, charts, vals = [], [], {}, {}
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]
        dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=True, progress=False, group_by="column",
                                 threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            sym = t[:-3]
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                if len(x) and x.index.max() < pd.Timestamp(today) - pd.Timedelta(days=10):
                    continue
                vals[sym] = float((x.Close * x.Volume).tail(20).mean())
                ev, nr, ch = analyse(sym, x, today)
            except Exception as e:  # noqa: BLE001
                print("fail", sym, e); continue
            events += ev
            if nr:
                near.append(nr)
            if ev or nr:
                charts[sym] = ch
        print(a + len(chunk), "done;", len(events), "signals,", len(near), "near", flush=True)
        time.sleep(1)
    rk = pd.Series(vals).rank(ascending=False, method="first")
    size = pd.cut(rk, [0, 100, 250, 500, 1e9], labels=["Large", "Mid", "Small", "Micro"]).astype(str).to_dict()
    E = pd.DataFrame(events)
    N = pd.DataFrame(near)
    for df in (E, N):
        if len(df):
            df["name"] = df.symbol.map(name).fillna("")
            df["size"] = df.symbol.map(size)
    cur = pd.Timestamp(today).to_period("M")
    if len(E):
        E["date"] = pd.to_datetime(E.date)
        E = E.sort_values("date").groupby("symbol").tail(1)          # latest signal per stock
        E["order"] = np.select([E.status == "exit next open", E.status == "open"], [0, 1], 2)
        E = E.sort_values(["order", "date"], ascending=[True, False]).drop(columns="order")
        brk = E[(E.status == "open") & (E.date.dt.to_period("M") >= cur - 1)]
    else:
        brk = E
    if len(N):
        N = N.sort_values("gap_pct")
    keep = set(E.symbol) | set(N.symbol) if len(E) or len(N) else set()
    for f in os.listdir(CH):
        if f[:-5] not in keep:
            os.remove(os.path.join(CH, f))
    for s_, ch in charts.items():
        if s_ in keep:
            json.dump(clean(ch), open(f"{CH}/{s_}.json", "w"), separators=(",", ":"), allow_nan=False)
    out = dict(asof=str(today), generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), scanned=len(vals),
               rules=dict(base_main=BASE_MAIN, base_min=BASE_MIN, near_pct=NEAR * 100, min_value_cr=MINVAL / 1e7),
               breakouts=clean(brk.to_dict("records")) if len(brk) else [],
               near=clean(N.to_dict("records")) if len(N) else [],
               tracked=clean(E.to_dict("records")) if len(E) else [])
    json.dump(out, open(f"{OUT}/ath.json", "w"), indent=0, allow_nan=False)
    print("breakouts", len(brk), "near", len(N), "tracked", len(E))
    nb = brk[brk.main] if len(brk) else brk
    ex = E[E.status == "exit next open"] if len(E) else E
    msg = [f"Monthly ATH scan {today}", f"New breakouts this/last month (base >= 2 y): {len(nb)}"]
    msg += [f"  {r.symbol} above {r.trigger:.2f} (ATH {r.ath_month}, base {r.base_months} m)" for r in nb.head(10).itertuples()]
    msg += [f"Sell next open (weekly close < 30-wk SMA): {', '.join(ex.symbol.head(15))}" if len(ex) else "No exits."]
    msg += [f"Near trigger (<= 5%): {', '.join(N[N.main].symbol.head(15))}" if len(N) else ""]
    telegram("\n".join(m for m in msg if m))


if __name__ == "__main__":
    main()
