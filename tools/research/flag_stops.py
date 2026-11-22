"""Flags / pennants / rectangles: where to put the stop, and how to exit (22 Nov 2026, Amritpal: "Where a flag or pennant stop
is typically placed, research it" -> "Go").

Detection = the live scanner's rules (tools/pattern_scan.py flag()), replayed day by day with no look-ahead:
  uptrend (pole top above the previous 6% swing high, flag low above the previous swing low; swings confirmed before the pole
  started), 21-day average rising over 5 sessions, 200-day over 20, close above the 200-day; pole >= 15% in <= 15 sessions
  (swing low -> highest high), flag 3-25 sessions, pullback <= 12% and <= half the pole, highs drifting down or flat;
  lane 'early' (pole started within 4% of the 200-day) or 'established' (50 > 200, both rising).
  Breakout = a close above the flag's top line (box top for a rectangle) on an up day. One trade per pole top.
Entry = the breakout day's close (what the app shows). 0.2% cost a round trip.
Stops tested (from the research: Bulkowski, IG, Qullamaggie, ChartMill):
  A flag low      = lowest low of the flag or the breakout day (the app now)
  B support line  = the flag's / pennant's lower line on the breakout day (rectangle: its low)
  C breakout low  = the breakout day's low
  D 2 x ATR       = entry - 2 x ATR(14)
  E flag low, skip trades whose stop is more than 8% away
  F flag low, but never more than 8% away (capped)
Exits: target = entry + pole (60-session limit) | trail = first close below the 21-day EMA, sold next open | half at target,
trail the rest. A stop and a target in the same bar -> stop first; gaps fill at the open.
Portfolio: Rs 20 L, 1% risk a trade (so a tighter stop buys more shares), max 10 positions, <= 20% each, biggest pole first.
NSE via Yahoo with the last sessions checked against NSE's bhavcopy; survivors only. Newest first, ex-Covid shown.
PILOT env = 150 stocks. Output data/research/flag_stops.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
from trend_bt_global import load  # noqa: E402
from holy_grail import portfolio, report  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002
POLE, POLE_D, MIN_D, MAX_D, DEPTH = 0.15, 15, 3, 25, 0.12
STOPS = ["A flag low (now)", "B support line", "C breakout-day low", "D 2 x ATR", "E flag low, skip > 8%", "F flag low, capped 8%"]
EXITS = ["target", "trail EMA21", "half target + trail"]


def zz(h, l, thr=0.06):
    out = []; mode = 1; ex, ei = h[0], 0
    for i in range(1, len(h)):
        if mode == 1:
            if h[i] > ex: ex, ei = h[i], i
            elif l[i] <= ex * (1 - thr): out.append((1, ei, ex, i)); mode = -1; ex, ei = l[i], i
        else:
            if l[i] < ex: ex, ei = l[i], i
            elif h[i] >= ex * (1 + thr): out.append((-1, ei, ex, i)); mode = 1; ex, ei = h[i], i
    return out


def signals(x):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c)
    if n < 260:
        return []
    S = pd.Series(c); s21 = S.rolling(21).mean().to_numpy(); s50 = S.rolling(50).mean().to_numpy(); s200 = S.rolling(200).mean().to_numpy()
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    Z = zz(h, l); zc = np.array([z[3] for z in Z]) if Z else np.array([])
    out = []; used = set()
    for t in range(230, n - 1):
        if not (c[t] > c[t - 1] and c[t] > s200[t] and s21[t] > s21[t - 5] and s200[t] >= s200[t - 20]):
            continue
        if h[t - MAX_D:t - MIN_D + 1].max() < 1.15 * l[t - MAX_D - POLE_D:t].min():
            continue
        end = t; w0 = max(POLE_D + 30, end - MAX_D)
        for pk in sorted(range(w0, end - MIN_D + 1), key=lambda i: -h[i]):
            top = h[pk]
            if h[pk + 1:end].max(initial=0) > top:
                continue
            lo_i = pk - POLE_D + int(np.argmin(l[pk - POLE_D:pk + 1])); base = l[lo_i]
            if top / base - 1 < POLE:
                continue
            a, b = pk + 1, end
            if b - a < MIN_D:
                continue
            plo = l[a:b].min(); depth = 1 - plo / top
            if depth > DEPTH or (top - plo) > 0.5 * (top - base):
                continue
            idx = np.arange(a, b); k_, b_ = np.polyfit(idx, h[a:b], 1); kl_, bl_ = np.polyfit(idx, l[a:b], 1)
            flat = 0.0015 * top
            if k_ > flat:
                continue
            shape = "Pennant" if k_ < -flat and kl_ > flat else "Rectangle" if abs(k_) <= flat and abs(kl_) <= flat else "Flag"
            if shape == "Rectangle":
                k_, b_, kl_, bl_ = 0.0, float(h[a:b].max()), 0.0, float(plo)
            k = int((zc <= lo_i).sum()) if len(zc) else 0; ZZ = Z[:k]
            ph = [z[2] for z in ZZ if z[0] == 1]; pl = [z[2] for z in ZZ if z[0] == -1]
            if not ph or not pl or not (top > ph[-1] and plo > pl[-1]):
                continue
            near = bool(np.nanmin(l[max(0, lo_i - 30):lo_i + 1] / s200[max(0, lo_i - 30):lo_i + 1]) <= 1.04)
            est = bool(s50[end] > s200[end] and s50[end] > s50[end - 20] and s200[end] > s200[end - 20])
            lane = "early" if near else "established" if est else None
            if not lane:
                continue
            # BO=high (22 Nov 2026, Amritpal: "DATAPATTNS is still not broken out"): breakout = a close above the flag's highest high,
            # not just above its falling top line
            lvl = h[a:b].max() if os.environ.get("BO") == "high" else k_ * t + b_
            if not c[t] > lvl or pk in used:
                break
            used.add(pk); e = c[t]
            out.append(dict(t=t, e=e, shape=shape, lane=lane, pole=top / base - 1, tgt=e + (top - base), fl=min(plo, l[t]), pk=pk, lo_i=lo_i, a=a, b=b, depth=depth,
                            sl=min(kl_ * t + bl_, l[t]) if shape != "Rectangle" else min(plo, l[t]), bl=l[t], atr=e - 2 * atr[t]))
            break
    return out


def run_exit(o, h, l, c, e21, t, e, stop, tgt, mode):
    """-> (exit index, gross return)"""
    n = len(c); half = None; j = t + 1; lim = t + (60 if mode == "target" else 250)
    while j < n:
        if o[j] <= stop: px = o[j]; break
        if l[j] <= stop: px = stop; break
        if mode != "trail EMA21" and half is None and h[j] >= tgt:
            if mode == "target": px = max(o[j], tgt); break
            half = max(o[j], tgt)
        if mode != "target" and c[j] < e21[j] and j + 1 < n:
            j += 1; px = o[j]; break
        if j >= lim: px = c[j]; break
        j += 1
    else:
        j = n - 1; px = c[j]
    r = px / e - 1
    if half is not None:
        r = 0.5 * (half / e - 1) + 0.5 * r
    return j, r


def tst(T):
    if not len(T):
        return dict(n=0)
    gw = T.ret[T.ret > 0].sum(); gl = -T.ret[T.ret < 0].sum()
    return dict(n=len(T), win=round((T.ret > 0).mean() * 100), avg=round(T.ret.mean() * 100, 2), avgR=round(T.r_mult.mean(), 2),
                stop_hit=round(T.stopped.mean() * 100), tgt_hit=round(T.hit.mean() * 100), pf=round(gw / gl, 2) if gl else None,
                risk=round(T.risk.median() * 100, 1), hold=float(T.days.median()))


def main():
    d, _ = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"])
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    C = {s: g.set_index("Date").CLOSE.astype(float).to_dict() for s, g in d.groupby("SYMBOL")}
    days = sorted(d.Date[d.Date >= "2016-06-01"].unique())
    rows = {(s, x): [] for s in STOPS for x in EXITS}; nsig = 0; nst = 0
    for sym, g in d.groupby("SYMBOL"):
        x = g.set_index("Date"); nst += 1
        o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index
        e21 = pd.Series(c).ewm(span=21, adjust=False).mean().to_numpy()
        for s in signals(x):
            if D[s["t"]] < pd.Timestamp("2016-06-01"):
                continue
            nsig += 1; e = s["e"]
            st = {STOPS[0]: s["fl"], STOPS[1]: s["sl"], STOPS[2]: s["bl"], STOPS[3]: s["atr"], STOPS[4]: s["fl"], STOPS[5]: max(s["fl"], e * 0.92)}
            for sn, sp in st.items():
                if not (0 < sp < e * 0.999) or (sn.startswith("E") and sp < e * 0.92):
                    continue
                risk = 1 - sp / e
                for xm in EXITS:
                    j, r = run_exit(o, h, l, c, e21, s["t"], e, sp, s["tgt"], xm)
                    ret = r - COST
                    rows[(sn, xm)].append(dict(sym=sym, side=1, entry=D[s["t"]], exit=D[j], e=e, risk=risk, ret=ret, r_mult=ret / risk, half=False,
                                               days=j - s["t"], adx=s["pole"], stopped=bool(l[j] <= sp or o[j] <= sp), hit=bool(h[s["t"] + 1:j + 1].max(initial=0) >= s["tgt"]),
                                               shape=s["shape"], lane=s["lane"], year=D[s["t"]].year))
        if nst % 200 == 0:
            print("R| stocks", nst, "signals", nsig, flush=True)
    print("R| panel", nst, "stocks,", nsig, "breakouts since Jun 2016", flush=True)
    nr = report(pd.Series({dd: float(nif.asof(dd)) for dd in days}), bull)
    res = dict(method=__doc__, stocks=nst, signals=nsig, nifty=nr, runs={})
    print("R| Nifty 50 buy & hold", nr, flush=True)
    for (sn, xm), L in rows.items():
        T = pd.DataFrame(L)
        if not len(T):
            continue
        end = T.entry.max()
        tr = dict(all=tst(T), **{f"last {y}y": tst(T[T.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)},
                  ex_covid=tst(T[~((T.entry >= "2020-02-15") & (T.entry <= "2020-12-31"))]))
        rp = report(portfolio(T, C, days), bull)
        k = f"{sn} | {xm}"; res["runs"][k] = dict(trades=tr, port=rp)
        if sn.startswith("A") or sn.startswith("C"):
            res["runs"][k]["by_shape"] = {sh: tst(T[T["shape"] == sh]) for sh in ("Flag", "Pennant", "Rectangle")}
            res["runs"][k]["by_lane"] = {ln: tst(T[T.lane == ln]) for ln in ("early", "established")}
            res["runs"][k]["by_year"] = {str(y): tst(T[T.year == y]) for y in sorted(T.year.unique(), reverse=True)}
        print(f"R| {k} | trades {tr['all']} | last 1y {tr['last 1y']}", flush=True)
        print(f"R| {k} | portfolio {rp}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/flag_stops" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
