"""Brian Shannon's anchored-VWAP "pinch" (21 Nov 2026, Amritpal pasted the rules). Daily version on NSE stocks 2016 -> today
(60/30-minute history is only ~2 years on Yahoo; the 5-day SMA on the hourly chart is the same line as the daily 5-day average).

Signal day t (all on the close):
  trend   : close > SMA50, SMA50 above its value 10 sessions ago; swing high = highest high of the last 20 sessions, 3-20 sessions
            ago and the highest high of the last 60 (a higher high); swing low = lowest low in the 60 sessions before the swing high
  AVWAPs  : AV_lo anchored at the swing low (typical price x volume), AV_hi anchored at the swing high
  pinch   : the previous close sat between them (AV_lo < close < AV_hi) with the gap <= 6% of price (variant: any gap)
  trigger : close above AV_hi and above a rising 5-day SMA
Entry: buy-stop 0.1% above the trigger day's high, next session only. Stop: below the lowest low of the last 3 sessions (the most recent
higher low) and not above AV_lo; skip if > 10% away. Exit: half at 2R (variant: at the swing high), the rest on the first close below the
5-day SMA (next open); the stop guards both halves. Same-bar stop and target -> stop first.
Control: same trend + trigger (close back above the 5-day SMA after a 3-20 session pullback) without the AVWAP conditions.
Portfolio Rs 20 L, 1% risk, max 10 positions, <= 20% each, 0.2% cost. Survivors (Yahoo). PILOT env = 200 stocks.
Output data/research/shannon_avwap.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402
from holy_grail import portfolio, report, tstats  # noqa: E402
from qullamaggie import download  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002


def trades_for(sym, x, mode, max_gap, tgt_mode):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")); n = len(c); dts = x.index
    tp = (h + l + c) / 3; cpv = np.cumsum(tp * v); cv = np.cumsum(v)
    av = lambda a, t: (cpv[t] - (cpv[a - 1] if a else 0)) / max(1.0, cv[t] - (cv[a - 1] if a else 0))  # noqa: E731
    s50 = pd.Series(c).rolling(50).mean().to_numpy(); s5 = pd.Series(c).rolling(5).mean().to_numpy()
    val20 = pd.Series(c * v).rolling(20).mean().to_numpy()
    out = []; t = 130; busy = -1
    while t < n - 1:
        if t <= busy:
            t += 1; continue
        if not (c[t] > s50[t] and s50[t] > s50[t - 10] and val20[t] >= 2e7 and c[t] >= 100):
            t += 1; continue
        kh = t - 19 + int(np.argmax(h[t - 19:t + 1]))
        if not (3 <= t - kh <= 20 and h[kh] >= np.max(h[t - 59:t + 1])):
            t += 1; continue
        kl = kh - 60 + int(np.argmin(l[kh - 60:kh + 1]))
        trig = c[t] > s5[t] and s5[t] > s5[t - 1] and c[t - 1] <= s5[t - 1]
        if mode == "pinch":
            lo_t, hi_t, lo_p, hi_p = av(kl, t), av(kh, t), av(kl, t - 1), av(kh, t - 1)
            trig = trig and c[t] > hi_t and lo_p < c[t - 1] < hi_p and (hi_p - lo_p) / c[t - 1] <= max_gap
        if not trig:
            t += 1; continue
        j = t + 1; buy = h[t] * 1.001
        if h[j] < buy:
            t += 1; continue
        e = max(o[j], buy); stop = np.min(l[t - 2:t + 1]) * 0.999
        if mode == "pinch":
            stop = min(stop, av(kl, t) * 0.999)
        if e <= stop or (e - stop) / e > 0.10:
            t += 1; continue
        R = e - stop; tgt = e + 2 * R if tgt_mode == "2R" else max(h[kh], e + 0.5 * R)
        half_px = None; exit_px = None; exit_i = None; k = j
        while k < n:
            if l[k] <= stop:
                exit_px, exit_i = (min(o[k], stop) if k > j else stop), k; break
            if half_px is None and h[k] >= tgt:
                half_px = max(o[k], tgt) if k > j else tgt
            if k > j and c[k] < s5[k] and k + 1 < n:
                exit_px, exit_i = o[k + 1], k + 1; break
            k += 1
        if exit_px is None:
            exit_px, exit_i = c[-1], n - 1
        u = lambda px: px / e - 1  # noqa: E731
        ret = (0.5 * u(half_px) + 0.5 * u(exit_px) if half_px is not None else u(exit_px)) - COST
        risk = max(R / e, 0.005)
        out.append(dict(sym=sym, side=1, entry=dts[j], exit=dts[exit_i], e=e, risk=risk, ret=ret, r_mult=ret / risk, half=half_px is not None,
                        days=exit_i - j, adx=float(val20[t]), open=exit_i == n - 1))
        busy = exit_i; t = exit_i + 1
    return out


def main():
    tick = list(symbols("NSE").ticker)
    if PILOT:
        tick = tick[:200]
    D = download(tick)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    C = {s: x.Close.to_dict() for s, x in D.items()}
    days = sorted(set().union(*[set(x.index[x.index >= "2016-06-01"]) for x in D.values()]))
    print("R| stocks", len(D), flush=True)
    res = dict(method=__doc__, runs={})
    for nm, mode, gap, tm in (("pinch as given (gap <= 6%, half at 2R)", "pinch", 0.06, "2R"), ("pinch, half at the swing high", "pinch", 0.06, "swing"),
                              ("pinch, any gap", "pinch", 9.0, "2R"), ("CONTROL: same pullback + 5-SMA trigger, no AVWAP", "control", 0, "2R")):
        rows = []
        for s, x in D.items():
            rows += trades_for(s, x, mode, gap, tm)
        T = pd.DataFrame(rows)
        if not len(T):
            print("R|", nm, "no trades", flush=True); continue
        T = T[T.entry >= "2016-06-01"]
        st = tstats(T); eq = portfolio(T, C, days); rp = report(eq, bull)
        res["runs"][nm] = dict(trades=st, port=rp)
        end = T.entry.max()
        print(f"R| {nm} | trades {st}", flush=True)
        print(f"R| {nm} | portfolio {rp}", flush=True)
        print(f"R| {nm} | trades newest first", {f"last {y}y": tstats(T[T.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)}, flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/shannon_avwap.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
