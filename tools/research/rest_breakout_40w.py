"""'Three phases, eight rules' (40-week MA rest + trendline breakout) - backtested 19 Nov 2026 at Amritpal's request (video slide).

Weekly bars (Friday close) from Yahoo daily data, NSE stocks 2015 -> today (survivors), liquid (20-day traded value >= Rs 1 cr).
  1 trend up      : the last two confirmed weekly swing highs AND swing lows are higher (pivot = 2 weeks each side)
  2 above MA      : close > 40-week SMA, and the SMA is above its value 4 weeks earlier
  3 retest        : in the rest window a weekly low came within 2% of the 40-week SMA
  4 rest          : the last R weeks (R = 4 or 6) all closed between 0.97x and 1.08x the SMA; variant: their average volume
                    below 0.8x the 20 weeks before (volume contracting)
  5 trendline     : from the highest high of the last 26 weeks (>= 4 weeks back): the falling line through the highs after
                    it that no high cuts (upper envelope)
  6 entry         : a weekly CLOSE above that line (and below the swing high) -> buy next week's open
  7 stop          : the lowest low of the rest window (last swing low)
  8 target        : the previous swing high (the line's anchor)
Exit variants: A stop + target (as on the slide); B stop + target only if the target is >= 1.5x the risk; C stop, no target,
exit on a weekly close below the 40-week SMA; D = C with the 1.5x filter. Same week stop and target -> stop first.
Portfolio: 10 positions, 1% risk (capped at 1/10 of equity), ranked by 3-month strength; costs 0.25% + 0.15% slippage a side.
Reference: the live 9/21 system on the same data (tools/research/concentrated_921.py).
Output: data/research/rest_breakout_40w.json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import symbols  # noqa: E402
from trend_bt_global import features, stats  # noqa: E402
import concentrated_921 as C  # noqa: E402

COST, SLIP = 0.0025, 0.0015


def weekly(x):
    w = pd.DataFrame({"O": x.Open.resample("W-FRI").first(), "H": x.High.resample("W-FRI").max(), "L": x.Low.resample("W-FRI").min(),
                      "C": x.Close.resample("W-FRI").last(), "V": x.Volume.resample("W-FRI").sum(),
                      "val": (x.Close * x.Volume).rolling(20).mean().resample("W-FRI").last()}).dropna(subset=["C"])
    return w


def setups(sym, w, R=4, vol=False):
    """weekly signals: (signal week index, stop, target, anchor) per the 8 rules"""
    if len(w) < 80:
        return []
    H, L, Cl, V = w.H.values, w.L.values, w.C.values, w.V.values
    ma = pd.Series(Cl).rolling(40).mean().values
    n = len(w); k = 2
    ph = [i for i in range(k, n - k) if H[i] == max(H[i - k:i + k + 1])]
    pl = [i for i in range(k, n - k) if L[i] == min(L[i - k:i + k + 1])]
    out = []
    for t in range(60, n):
        if not np.isfinite(ma[t]) or not np.isfinite(ma[t - 4]) or ma[t] <= ma[t - 4] or Cl[t] <= ma[t]:
            continue
        if not (w.val.values[t] >= 1e7):
            continue
        hs = [i for i in ph if i + k <= t - 1]; ls = [i for i in pl if i + k <= t - 1]          # pivots confirmed before t
        if len(hs) < 2 or len(ls) < 2 or not (H[hs[-1]] > H[hs[-2]] and L[ls[-1]] > L[ls[-2]]):
            continue
        r0 = t - R                                                     # rest window: weeks r0 .. t-1
        cl = Cl[r0:t]; m = ma[r0:t]
        if not np.all((cl >= 0.97 * m) & (cl <= 1.08 * m)) or not np.any(L[r0:t] <= 1.02 * m):
            continue
        if vol and not (V[r0:t].mean() < 0.8 * V[max(0, r0 - 20):r0].mean()):
            continue
        a0 = max(0, t - 26); h = a0 + int(np.argmax(H[a0:t]))
        if t - h < 4:
            continue
        s = max((H[j] - H[h]) / (j - h) for j in range(h + 1, t))     # upper envelope from the anchor (no high cuts it)
        if s >= 0:
            continue
        line = H[h] + s * (t - h)
        if not (Cl[t] > line and Cl[t] < H[h]) or Cl[t - 1] > H[h] + s * (t - 1 - h):
            continue                                                   # fresh break this week, still under the swing high
        out.append((t, float(min(L[r0:t])), float(H[h])))
    return out


def run(W, S, mode, rr_min=0.0, maxpos=10, risk=0.01, cap0=2_000_000, start="2016-06-01"):
    """weekly portfolio: S[date] = list of (sym, stop, target, r63); entry next week's open"""
    dates = sorted(set(d for w in W.values() for d in w.index)); dates = [d for d in dates if d >= pd.Timestamp(start)]
    cash, pos, eq, trades, pend = cap0, {}, {}, [], []
    for d in dates:
        # entries at this week's open
        for sym, stop, tgt in pend:
            w = W[sym]
            if d not in w.index or sym in pos or len(pos) >= maxpos:
                continue
            o = float(w.at[d, "O"])
            if o <= stop or (tgt and o >= tgt):
                continue
            if rr_min and (tgt - o) < rr_min * (o - stop):
                continue
            e = cash + sum(p["q"] * p["last"] for p in pos.values()); fill = o * (1 + SLIP) * (1 + COST / 2)
            q = min(risk * e / (o - stop), e / maxpos / o, cash / fill)
            if q * o < 0.005 * cap0:
                continue
            cash -= q * fill; pos[sym] = dict(q=q, cin=fill, stop=stop, tgt=tgt if mode in ("A", "B") else None, d=d, last=o)
        pend = []
        for sym in list(pos):
            p = pos[sym]; w = W[sym]
            if d not in w.index:
                continue
            r = w.loc[d]; px = None
            if r.L <= p["stop"]:
                px = min(r.O, p["stop"]); why = "stop"
            elif p["tgt"] and r.H >= p["tgt"]:
                px = max(r.O, p["tgt"]); why = "target"
            elif mode in ("C", "D") and r.C < r.ma:
                px = r.C; why = "below 40w"
            if px is not None:
                f = px * (1 - SLIP) * (1 - COST / 2); cash += p["q"] * f
                trades.append(dict(sym=sym, entry=p["d"], exit=d, ret=f / p["cin"] - 1, why=why)); del pos[sym]
            else:
                p["last"] = float(r.C)
        if d in S and len(pos) < maxpos:
            c = sorted(S[d], key=lambda z: -z[3])
            pend = [(s, st, tg) for s, st, tg, _ in c if s not in pos][:maxpos - len(pos)]
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos.values())
    return pd.Series(eq), pd.DataFrame(trades)


def main():
    u = symbols("NSE"); tick = list(u.ticker); W, F = {}, []
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]; D = None
        for _ in range(3):
            try:
                D = yf.download(ch, start="2014-06-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if D is None or D.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({k: D[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x = x[(x.Close > 0) & (x.Open > 0)]
                if len(x) < 400:
                    continue
                w = weekly(x); w["ma"] = w.C.rolling(40).mean(); w["r63"] = w.C / w.C.shift(13) - 1
                W[t] = w
                f = features(t, x.Open, x.High, x.Low, x.Close, x.Volume, 1e7)
                if f is not None:
                    F.append(f)
            except Exception:  # noqa: BLE001
                continue
        print("downloaded", i + 200, len(W), flush=True); time.sleep(2)
    res = dict(method=__doc__, stocks=len(W))
    for R in (4, 6):
        for vol in (False, True):
            S = {}; nsig = 0
            for sym, w in W.items():
                for t, stop, tgt in setups(sym, w, R, vol):
                    if t + 1 < len(w):
                        S.setdefault(w.index[t], []).append((sym, stop, tgt, float(w.r63.iloc[t]) if np.isfinite(w.r63.iloc[t]) else -9)); nsig += 1
            for mode, rr in (("A", 0), ("B", 1.5), ("C", 0), ("D", 1.5)):
                eq, T = run(W, S, mode, rr)
                if not len(eq):
                    continue
                a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
                hold = (pd.to_datetime(T.exit) - pd.to_datetime(T.entry)).dt.days if len(T) else pd.Series(dtype=float)
                k = f"rest {R} weeks{' + volume drying' if vol else ''} | {dict(A='stop + target (slide)', B='stop + target, target >= 1.5R', C='stop, exit below 40-week, no target', D='C with target >= 1.5R')[mode]}"
                res[k] = dict(signals=nsig, cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                              win=round(float((T.ret > 0).mean() * 100)) if len(T) else None, avg=round(float(T.ret.mean() * 100), 2) if len(T) else None,
                              hold_median_days=float(hold.median()) if len(hold) else None,
                              exits=T.why.value_counts().to_dict() if len(T) else {})
                print("R|", k, {x: res[k][x] for x in ("signals", "cagr", "maxdd", "cagr_22_26", "trades", "win", "avg", "hold_median_days")}, flush=True)
    d = pd.concat(F, ignore_index=True).sort_values(["SYMBOL", "Date"]); g = d.groupby("SYMBOL").CLOSE
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max()); d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    eq, T = C.run(d, 10, 0.01, "r63", 0); a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
    res["9/21 reference, 10 positions, 3-month strength"] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], trades=len(T))
    print("R| 9/21 reference", res["9/21 reference, 10 positions, 3-month strength"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rest_breakout_40w.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
