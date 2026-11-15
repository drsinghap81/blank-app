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
Sector tag (data/scan/sectors.json from tools/sector_state.py): leading / uptrend / mixed / weak for the stock's sector index;
  backtest: breakouts in up-trending sectors won 54% vs 40%, 'weak' sectors 31%, but average returns were not higher -> a tag only.
Charts: data/scan/ath_charts/SYM.json (monthly bars, full history; weekly bars, last 5 years, with the 30-week SMA).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

SEC, BENCH = None, None
LAST_BAR = [None]
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_scan import nse_symbols, telegram  # noqa: E402

# market: NSE (default), US or ASX (python ath_scan.py US). US/ASX added 5 Nov 2026 - same rules, own outputs.
MARKET = (sys.argv[1] if len(sys.argv) > 1 else "NSE").upper()
OUT = "data/scan" if MARKET == "NSE" else f"data/scan/{MARKET.lower()}"
CH = f"{OUT}/ath_charts"
MINVAL = {"NSE": 2e7, "US": 5e6, "ASX": 1e6, "UK": 1e8}[MARKET]          # Rs 2 cr / $5 m / A$1 m a day
UNIT = {"NSE": 1e7, "US": 1e6, "ASX": 1e6, "UK": 1e8}[MARKET]            # value_cr field = traded value in Rs cr / $ m / A$ m
MIN_CLOSE = {"NSE": 100.0, "US": 30.0, "ASX": 30.0, "UK": 100.0}[MARKET]   # no penny stocks (30 Oct 2026)
MCL_MIN = {"ASX": 1.0}.get(MARKET, MIN_CLOSE)   # 15 Nov 2026: month-close list only goes down to A$1 on the ASX (A$1 m/day still applies)
BASE_MAIN, BASE_MIN = 24, 12
WCLOSE, DCLOSE = [], []   # 15 Nov 2026: week / day CLOSED above the all-time high (cup >= 26 weeks & 20% / >= 20 days & 15%)
WK_MIN, WK_DEP, DY_MIN, DY_DEP, WK_K, DY_K = 26, -0.20, 20, -0.15, 104, 250
MCLOSE = []   # month-end list (15 Nov 2026): last completed month CLOSED above the old all-time closing high
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


def analyse(sym, x, today, lookback_days=550):
    """x: daily OHLCV (DatetimeIndex). Returns (events, near_row or None, chart dict) ."""
    from session import drop_partial
    x = drop_partial(x.dropna(subset=["Close"]), MARKET)
    x = x[(x.Close > 0) & (x.High > 0)]
    if len(x) < 300:
        return [], None, None
    if MARKET == "NSE":   # Yahoo NSE history misses some splits; US/ASX history is adjusted (and big gaps are real there)
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
    sig = [(dt, max(r.o, r.trig), r.trig, r.age, r.ath_month, "high") for dt, r in ev.iterrows()]
    # close breakout (5 Nov 2026): a completed month CLOSES above the old ATH close without trading above the trigger
    # (the old ATH month had a long upper wick) after a base >= BASE_MIN -> buy the next month's first open.
    # NSE 2017-26 backtest at 1% risk: 16.0-17.3%/yr vs 14.8-15.4% without (132 extra trades, avg +16.6%).
    cbrk = isb & done & (M.h <= trig_m) & (age_m >= BASE_MIN) & (hist_ok == True)  # noqa: E712
    for m_ in M.index[cbrk.fillna(False).values]:
        nxt = d[d.mon == m_ + 1]
        if not len(nxt):
            continue
        dt = nxt.index[0]; r = nxt.iloc[0]
        if r.above == True and r.val >= MINVAL:  # noqa: E712
            sig.append((dt, r.o, float(M.c.loc[m_]), float(age_m.loc[m_]), str(ath_month.loc[m_]), "close"))
    if lookback_days:
        sig = [x_ for x_ in sig if x_[0] >= pd.Timestamp(today) - pd.Timedelta(days=lookback_days)]
    sig.sort(key=lambda x_: x_[0])
    # Trend Following 9/21 (9 Nov 2026): cup 12-24 m breakouts are traded with a daily EMA 9/21 exit instead of the
    # 30-week SMA. Initial stop = EMA21 on the day before entry (at least 4% under the entry); exit = first daily close
    # with EMA9 below EMA21 -> sell next open. NSE 2017-26: 10.5%/yr alone, worst fall -15.6%; with Momentum in one account
    # see tools/trade_plan.py.
    e9 = x.Close.ewm(span=9, adjust=False, min_periods=21).mean(); e21 = x.Close.ewm(span=21, adjust=False, min_periods=21).mean()
    below = e9 < e21

    def tf_state(dt, entry):
        prev = e21[e21.index < dt]
        s0 = float(prev.iloc[-1]) if len(prev) and np.isfinite(prev.iloc[-1]) else entry * 0.96
        s0 = min(s0, entry * 0.96)
        hit = below[(below.index >= dt) & below]
        if len(hit):
            nx = x[x.index > hit.index[0]]
            if len(nx):
                return dict(tf_status="exited", tf_exit_date=nx.index[0], tf_exit_price=float(nx.Open.iloc[0]), tf_stop0=s0)
            return dict(tf_status="exit next open", tf_exit_date=None, tf_exit_price=None, tf_stop0=s0)
        return dict(tf_status="open", tf_exit_date=None, tf_exit_price=None, tf_stop0=s0)
    events = []
    busy = None
    for dt, entry, trig_v, age_v, athm_v, kind in sig:
        if busy is not None and dt <= busy:
            continue
        r = pd.Series(dict(trig=trig_v, age=age_v, ath_month=athm_v, depth=d.depth.loc[dt], val=d.val.loc[dt]))
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
        busy = exit_dt if exit_dt is not None else x.index[-1] + pd.Timedelta(days=1)
        events.append(dict(symbol=sym, date=dt, entry=entry, trigger=r.trig, ath_month=r.ath_month, base_months=int(r.age), kind=kind,
                           depth=r.depth, status=status, exit_date=exit_dt, exit_price=exit_px, close=last,
                           ret=ret, peak=float(x.Close[x.index >= dt].max() / entry - 1),
                           weeks=int(((exit_dt or x.index[-1]) - dt).days / 7), main=bool(r.age >= BASE_MAIN),
                           sma_entry=sma_entry, **add, **(tf_state(dt, entry) if r.age < BASE_MAIN else {}),
                           ema9=float(e9.iloc[-1]) if np.isfinite(e9.iloc[-1]) else None,
                           ema21=float(e21.iloc[-1]) if np.isfinite(e21.iloc[-1]) else None,
                           sma30=float(W.sma.loc[last_complete]) if np.isfinite(W.sma.loc[last_complete]) else None,
                           value_cr=float(r.val) / UNIT))
    # near trigger (current month, not crossed yet)
    near = None
    t_now = d.trig.iloc[-1]
    if np.isfinite(t_now) and d.hist_ok.iloc[-1] and not cross[d.mon == cur_m].any():
        c = float(x.Close.iloc[-1])
        lastw = W.loc[last_complete]
        sma4 = W.sma.shift(4).loc[last_complete]
        best_c = float(best.iloc[-2]) if len(best) > 1 and np.isfinite(best.iloc[-2]) else np.nan   # old ATH close
        close_near = np.isfinite(best_c) and c < best_c and c >= (1 - NEAR) * best_c and c < (1 - NEAR) * t_now
        if close_near and d.age.iloc[-1] >= BASE_MIN and np.isfinite(lastw.sma) and lastw.c > lastw.sma \
                and np.isfinite(sma4) and lastw.sma > sma4 and val20.iloc[-1] >= MINVAL:
            # within 5% of the old ATH CLOSE (trigger is a far-away wick high): a month close above it is the signal
            near = dict(symbol=sym, trigger=best_c, close=c, gap_pct=(best_c / c - 1) * 100, ath_month=d.ath_month.iloc[-1],
                        base_months=int(d.age.iloc[-1]), depth=d.depth.iloc[-1], sma30=float(lastw.sma), kind="close",
                        wick_high=float(t_now), main=bool(d.age.iloc[-1] >= BASE_MAIN), value_cr=float(val20.iloc[-1]) / UNIT,
                        ema21=float(e21.iloc[-1]) if np.isfinite(e21.iloc[-1]) else None, ema9=float(e9.iloc[-1]) if np.isfinite(e9.iloc[-1]) else None)
        elif c >= (1 - NEAR) * t_now and d.age.iloc[-1] >= BASE_MIN and np.isfinite(lastw.sma) and lastw.c > lastw.sma \
                and np.isfinite(sma4) and lastw.sma > sma4 \
                and val20.iloc[-1] >= MINVAL:
            near = dict(symbol=sym, trigger=t_now, close=c, gap_pct=(t_now / c - 1) * 100, ath_month=d.ath_month.iloc[-1],
                        base_months=int(d.age.iloc[-1]), depth=d.depth.iloc[-1], sma30=float(lastw.sma), kind="high",
                        main=bool(d.age.iloc[-1] >= BASE_MAIN), value_cr=float(val20.iloc[-1]) / UNIT,
                        ema21=float(e21.iloc[-1]) if np.isfinite(e21.iloc[-1]) else None, ema9=float(e9.iloc[-1]) if np.isfinite(e9.iloc[-1]) else None)
    # month-end close list (15 Nov 2026): the last COMPLETED month closed above the old all-time closing high after a base
    # >= BASE_MIN months. Long cup = base >= 36 m and a fall of >= 30% inside the base. NSE 2017-26 (buy next month's open,
    # weekly SMA30 exit, 10 stocks): base >= 24 m 26.7%/yr -40% (equal wt) / 21.4% -39% (2% risk); long cups 24.4% -27% /
    # 25.3% -29%; the live intramonth cross: 26.1% -32% / 29.1% -26%.
    mcl = None
    # 15 Nov 2026 (Amritpal): the ATH level is the all-time HIGH price (wicks included), as on TradingView. The list = the last
    # completed month CLOSED above the highest price of all earlier months, after a base >= BASE_MIN months since that high.
    lm_ = M.index[np.asarray(done)][-1] if np.asarray(done).any() else None
    if lm_ is not None and lm_ == pd.Timestamp(today).to_period("M") - 1:
        i_ = M.index.get_loc(lm_); prior = M.iloc[:i_]
        if len(prior) >= 13 and float(M.c.loc[lm_]) > float(prior.h.max()):
            a_ = int(np.argmax(prior.h.to_numpy())); old_h = float(prior.h.iloc[a_]); base_ = int(i_ - a_)
            dm = d[d.mon == lm_]; v_me = float(dm.val.iloc[-1]) if len(dm) else np.nan
            if base_ >= BASE_MIN and a_ >= 3 and np.isfinite(v_me) and v_me >= MINVAL:
                wme = W[W.index.end_time.normalize() <= dm.index[-1]]
                sm_ = float(wme.sma.iloc[-1]) if len(wme) and np.isfinite(wme.sma.iloc[-1]) else None
                sm4 = float(wme.sma.iloc[-5]) if len(wme) > 5 and np.isfinite(wme.sma.iloc[-5]) else None
                seg = prior.c.iloc[a_ + 1:]; dep_ = float(seg.min() / old_h - 1) if len(seg) else None
                mcl = dict(symbol=sym, month=str(lm_), close_m=float(M.c.loc[lm_]), old_ath=old_h, ath_month=str(prior.index[a_]),
                           above_pct=(float(M.c.loc[lm_]) / old_h - 1) * 100, base_months=base_, depth=dep_, high_m=float(M.h.loc[lm_]),
                           long_cup=bool(base_ >= 36 and dep_ is not None and dep_ <= -0.30), main=bool(base_ >= BASE_MAIN),
                           sma30=sm_, sma_rising=bool(sm_ is not None and sm4 is not None and sm_ > sm4 and float(wme.c.iloc[-1]) > sm_),
                           close=float(x.Close.iloc[-1]), since_pct=(float(x.Close.iloc[-1]) / float(M.c.loc[lm_]) - 1) * 100,
                           value_cr=v_me / UNIT)
                MCLOSE.append(mcl)
    # 15 Nov 2026: weekly and daily cup closes. Rim = highest high of the last WK_K weeks / DY_K days (excluding the signal bar),
    # at least WK_MIN / DY_MIN bars old; cup depth = lowest close since the rim; next resistance = highest high BEFORE the rim.
    # Kept when the room to that resistance is at least the cup depth (Amritpal), or the rim is the all-time high.
    # NSE 2017-26 at 1% risk + add: weekly 9.0%/yr -26% (equal weight 20.4% -34%); daily (ATH cups) 12.7% -35%;
    # live monthly cross 21.5% -20%. Watch lists only.
    lists = mcl is not None

    def cupclose(hh, cc, K, B, D):
        n_ = len(hh)
        if n_ < B + 3:
            return None
        lo = max(0, n_ - 1 - K); win = hh[lo:n_ - 1]
        a_ = lo + int(np.nanargmax(win)); rim = float(hh[a_]); age = n_ - 1 - a_
        if not (cc[-1] > rim and age >= B):
            return None
        seg = cc[a_ + 1:n_ - 1]; dep = float(np.nanmin(seg) / rim - 1) if len(seg) else 0.0
        if dep > D:
            return None
        # next resistance = the nearest older peak above today's close: walk back from the rim to the first bar trading above
        # the close, then take the local peak around it (+/- B bars). None = nothing older above the close.
        res = None; c_ = float(cc[-1]); above = np.flatnonzero(hh[:a_] > c_)
        if len(above):
            j = int(above[-1]); lo_, hi_ = max(0, j - B), min(a_, j + B + 1)
            res = float(np.nanmax(hh[lo_:hi_]))
        room = (res / cc[-1] - 1) if res else None
        if room is not None and room < -dep:
            return None
        return a_, rim, age, dep, res, room
    try:
        Wc = W.loc[:last_complete]
        r_ = cupclose(Wc.h.to_numpy(float), Wc.c.to_numpy(float), WK_K, WK_MIN, WK_DEP)
        wend = Wc.index[-1].end_time.normalize(); vw = val20.loc[:wend]
        if r_ and len(vw) and float(vw.iloc[-1]) >= MINVAL:
            a_, rim, age, dep, res, room = r_; lw = Wc.iloc[-1]
            sm = float(lw.sma) if np.isfinite(lw.sma) else None; sm4 = W.sma.shift(4).loc[Wc.index[-1]]
            WCLOSE.append(dict(symbol=sym, kind="W", period=str(Wc.index[-1].end_time.date()), close_p=float(lw.c), high_p=float(lw.h), old_ath=rim,
                               ath_date=str(Wc.index[a_].end_time.date()), base=int(age), depth=round(dep, 4), above_pct=(float(lw.c) / rim - 1) * 100,
                               resistance=res, room_pct=None if room is None else round(room * 100, 2), ath=res is None,
                               long_cup=bool(age >= 52 and dep <= -0.30), sma_rising=bool(sm is not None and np.isfinite(sm4) and sm > sm4 and float(lw.c) > sm),
                               close=float(x.Close.iloc[-1]), value_cr=float(vw.iloc[-1]) / UNIT, first=str(x.index[0].date())))
            lists = True
        r_ = cupclose(x.High.to_numpy(float), x.Close.to_numpy(float), DY_K, DY_MIN, DY_DEP)
        if r_ and float(val20.iloc[-1]) >= MINVAL:
            a_, rim, age, dep, res, room = r_; cc = float(x.Close.iloc[-1])
            sm = W.sma.loc[last_complete]; sm4 = W.sma.shift(4).loc[last_complete]
            DCLOSE.append(dict(symbol=sym, kind="D", period=str(x.index[-1].date()), close_p=cc, high_p=float(x.High.iloc[-1]), old_ath=rim,
                               ath_date=str(x.index[a_].date()), base=int(age), depth=round(dep, 4), above_pct=(cc / rim - 1) * 100,
                               resistance=res, room_pct=None if room is None else round(room * 100, 2), ath=res is None,
                               long_cup=bool(age >= 120 and dep <= -0.30), sma_rising=bool(np.isfinite(sm) and np.isfinite(sm4) and sm > sm4 and float(Wc.c.iloc[-1]) > sm),
                               close=cc, value_cr=float(val20.iloc[-1]) / UNIT, first=str(x.index[0].date())))
            lists = True
    except Exception as e:  # noqa: BLE001
        print("w/d close fail", sym, str(e)[:60])
    Mc = M.tail(240); Wt = W.tail(260)
    chart = dict(m=dict(t=[str(p) for p in Mc.index], o=Mc.o.round(2).tolist(), h=Mc.h.round(2).tolist(),
                        l=Mc.l.round(2).tolist(), c=Mc.c.round(2).tolist()),
                 w=dict(t=[str(p.end_time.date()) for p in Wt.index], o=Wt.o.round(2).tolist(), h=Wt.h.round(2).tolist(),
                        l=Wt.l.round(2).tolist(), c=Wt.c.round(2).tolist(), sma=Wt.sma.round(2).tolist()),
                 trigger=float(t_now) if np.isfinite(t_now) else None, ath_month=d.ath_month.iloc[-1])
    if lists:
        chart["mclose"] = True
    return events, near, chart


def daily_block(x, n=320):
    """Last n daily bars with EMA 9/21/50 for the app's setup chart (Today tab)."""
    c = x.Close
    e = {k: c.ewm(span=k, adjust=False).mean() for k in (9, 21, 50)}
    x = x.tail(n)
    rd = lambda a: [None if not np.isfinite(v) else round(float(v), 2) for v in np.asarray(a, dtype=float)[-n:]]  # noqa: E731
    return dict(t=[str(i.date()) for i in x.index], o=rd(x.Open), h=rd(x.High), l=rd(x.Low), c=rd(x.Close),
                e9=rd(e[9]), e21=rd(e[21]), e50=rd(e[50]))


def main():
    os.makedirs(CH, exist_ok=True)
    from zoneinfo import ZoneInfo
    today = datetime.now(timezone.utc).astimezone(ZoneInfo({"NSE": "Asia/Kolkata", "US": "America/New_York", "ASX": "Australia/Sydney", "UK": "Europe/London"}[MARKET])).date()
    global SEC, BENCH
    try:
        from sector_state import load_bench, stock_rs
        SEC = json.load(open(f"{OUT}/sectors.json")); BENCH = load_bench(f"{OUT}/sector_hist.csv.gz")
    except Exception:  # noqa: BLE001
        SEC, BENCH = None, None
        stock_rs = lambda *a_: {}  # noqa: E731
    if MARKET == "NSE":
        u = nse_symbols()
        u = u[u.board == "main"] if "board" in u else u
        u["ticker"] = u.symbol + ".NS"
    else:
        from global_universe import symbols
        u = symbols(MARKET)
    name = dict(zip(u.symbol, u.name)) if "name" in u else {}
    sym_of = dict(zip(u.ticker, u.symbol))
    tick = list(u.ticker)
    print("symbols", len(tick), flush=True)
    events, near, charts, vals = [], [], {}, {}
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]
        dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column",
                                 threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            sym = sym_of.get(t, t)
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                if len(x):
                    from session import drop_partial as _dp
                    _xl = _dp(x, MARKET)
                    if len(_xl):
                        LAST_BAR[0] = max(LAST_BAR[0], _xl.index[-1].date()) if LAST_BAR[0] else _xl.index[-1].date()
                if len(x) and x.index.max() < pd.Timestamp(today) - pd.Timedelta(days=10):
                    continue
                if not len(x) or float(x.Close.iloc[-1]) < MCL_MIN:
                    continue
                low_px = float(x.Close.iloc[-1]) < MIN_CLOSE
                if not low_px:
                    vals[sym] = float((x.Close * x.Volume).tail(20).mean())
                ev, nr, ch = analyse(sym, x, today)
                if low_px:          # below the tested price floor: month-close list only, no signals
                    ev, nr = [], None
                    if not (ch and ch.get("mclose")):
                        continue
                    for L_ in (MCLOSE, WCLOSE, DCLOSE):
                        if L_ and L_[-1]["symbol"] == sym:
                            L_[-1]["low_price"] = True
                if ev or nr:
                    rsd = stock_rs(sym, x.Close, SEC, BENCH)
                    for e_ in ev:
                        e_.update(rsd)
                    if nr:
                        nr.update(rsd)
            except Exception as e:  # noqa: BLE001
                print("fail", sym, e); continue
            events += ev
            if nr:
                near.append(nr)
            if ch and ch.get("mclose") and SEC:
                rsd_ = stock_rs(sym, x.Close, SEC, BENCH)
                for L_ in (MCLOSE, WCLOSE, DCLOSE):
                    if L_ and L_[-1]["symbol"] == sym:
                        L_[-1].update(rsd_)
            if ev or nr or (ch and ch.get("mclose")):
                ch["d"] = daily_block(x)                        # daily bars for the app's Today chart (11 Nov 2026)
                charts[sym] = ch
        print(a + len(chunk), "done;", len(events), "signals,", len(near), "near", flush=True)
        time.sleep(1)
    rk = pd.Series(vals).rank(ascending=False, method="first")
    size = pd.cut(rk, {"NSE": [0, 100, 250, 500, 1e9], "US": [0, 500, 1500, 3000, 1e9], "ASX": [0, 100, 300, 600, 1e9], "UK": [0, 100, 200, 300, 1e9]}[MARKET], labels=["Large", "Mid", "Small", "Micro"]).astype(str).to_dict()
    E = pd.DataFrame(events)
    N = pd.DataFrame(near)
    try:
        from sector_state import tag_for, stock_rs, topdown  # noqa: F401
        sec = json.load(open(f"{OUT}/sectors.json"))
    except Exception:  # noqa: BLE001
        sec = None
    for df in (E, N):
        if len(df):
            df["name"] = df.symbol.map(name).fillna("")
            df["size"] = df.symbol.map(size)
            if sec:
                t = [tag_for(s_, sec) for s_ in df.symbol]
                df["industry"], df["sector_index"], df["sector_tag"] = [x[0] for x in t], [x[1] for x in t], [x[2] for x in t]
                ix_ = sec.get("indices") or {}
                df["sector_rs"] = [(ix_.get(x[1]) or {}).get("rs_6m") if x[1] else None for x in t]
                df["sector_rs_up"] = [(ix_.get(x[1]) or {}).get("rs_6m_up") if x[1] else None for x in t]
                df = topdown(df, sec)
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
    def tagsort(rows, base_col):
        D_ = pd.DataFrame(rows)
        if not len(D_):
            return D_
        D_["name"] = D_.symbol.map(name).fillna(""); D_["size"] = D_.symbol.map(size)
        if sec:
            t_ = [tag_for(s_, sec) for s_ in D_.symbol]
            D_["industry"], D_["sector_index"], D_["sector_tag"] = [x[0] for x in t_], [x[1] for x in t_], [x[2] for x in t_]
            ix_ = sec.get("indices") or {}
            D_["sector_rs"] = [(ix_.get(x[1]) or {}).get("rs_6m") if x[1] else None for x in t_]
        # 15 Nov 2026: strongest sectors first (leading > uptrend > mixed > weak > untagged), then sector RS, long cups, base
        D_["_o"] = D_.get("sector_tag", pd.Series(index=D_.index, dtype=object)).map({"leading": 0, "uptrend": 1, "mixed": 2, "weak": 3}).fillna(4)
        D_["_r"] = pd.to_numeric(D_.get("sector_rs", pd.Series(index=D_.index, dtype=float)), errors="coerce").fillna(-999)
        return D_.sort_values(["_o", "_r", "long_cup", base_col], ascending=[True, False, False, False]).drop(columns=["_o", "_r"])
    MC = tagsort(MCLOSE, "base_months"); WC = tagsort(WCLOSE, "base"); DC = tagsort(DCLOSE, "base")
    keep = (set(E.symbol) if len(E) else set()) | (set(N.symbol) if len(N) else set()) | (set(MC.symbol) if len(MC) else set()) | (set(WC.symbol) if len(WC) else set()) | (set(DC.symbol) if len(DC) else set())
    for f in os.listdir(CH):
        if f[:-5] not in keep:
            os.remove(os.path.join(CH, f))
    for s_, ch in charts.items():
        if s_ in keep:
            json.dump(clean(ch), open(f"{CH}/{s_}.json", "w"), separators=(",", ":"), allow_nan=False)
    data_asof = str(LAST_BAR[0]) if LAST_BAR[0] else str(today)   # last completed market close in the data
    out = dict(market=MARKET, asof=data_asof, scan_date=str(today), generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), scanned=len(vals),
               rules=dict(base_main=BASE_MAIN, base_min=BASE_MIN, near_pct=NEAR * 100, min_value_cr=MINVAL / UNIT, min_close=MIN_CLOSE),
               breakouts=clean(brk.to_dict("records")) if len(brk) else [],
               near=clean(N.to_dict("records")) if len(N) else [],
               tracked=clean(E.to_dict("records")) if len(E) else [],
               month_close=clean(MC.to_dict("records")) if len(MC) else [],
               week_close=clean(WC.to_dict("records")) if len(WC) else [], day_close=clean(DC.to_dict("records")) if len(DC) else [],
               wd_rules=dict(week_min=WK_MIN, week_depth=WK_DEP, week_window=WK_K, day_min=DY_MIN, day_depth=DY_DEP, day_window=DY_K))
    json.dump(out, open(f"{OUT}/ath.json", "w"), indent=0, allow_nan=False)
    print("breakouts", len(brk), "near", len(N), "tracked", len(E))
    nb = brk[brk.main] if len(brk) else brk
    ex = E[E.status == "exit next open"] if len(E) else E
    msg = [f"Monthly ATH scan {MARKET} {today}", f"New breakouts this/last month (base >= 2 y): {len(nb)}"]
    msg += [f"  {r.symbol} above {r.trigger:.2f} (ATH {r.ath_month}, base {r.base_months} m)" for r in nb.head(10).itertuples()]
    msg += [f"Sell next open (weekly close < 30-wk SMA): {', '.join(ex.symbol.head(15))}" if len(ex) else "No exits."]
    msg += [f"Near trigger (<= 5%): {', '.join(N[N.main].symbol.head(15))}" if len(N) else ""]
    telegram("\n".join(m for m in msg if m))


if __name__ == "__main__":
    main()
