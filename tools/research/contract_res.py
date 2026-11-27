"""Contracting pullbacks under a flat resistance (28 Nov 2026, Amritpal's chart: "at first resistance rejection is more, at next
less and then further less, tight range" -> breakout).
NSE stocks (Yahoo 2015-26, survivors), >= Rs 2 cr/day, price >= 100, 0.4% cost.
RESISTANCE R = highest high of the last 150 sessions (before the breakout day t). TOUCHES = swing highs (higher than 2 bars each
  side) within 2% under R, at least 5 sessions apart; >= 3 touches, the first >= 40 sessions before t.
PULLBACKS: depth after each touch = 1 - lowest low until the next touch (the last one: until t-1) / R.
  CONTRACTING: each pullback shallower than the one before; first >= 10%, first >= 2x the last.
TIGHT RANGE: the last pullback <= 6% and the 5 sessions before t have a range <= 6% with every close <= R.
BREAKOUT: close above R (previous close at/under R). Variant: on >= 1.5x the 20-day volume. Variant: price above the 200-day.
ENTRY (Amritpal's rule): buy-stop at the breakout candle's high + 0.15% for 3 sessions (gap > 3% above skipped).
STOP: under the tight range's low; risk 1-12%.
EXITS: 2R (10 sessions) | 3R (15) | 9/21 close exit | 30 EMA (2 closes under it). R net of cost.
CONTROL: first close above the same 150-session high, no contraction / tight-range rules, stop = 10-day low.
Portfolio: 1% risk a trade, max 10% a stock, 10 open. Newest windows first. PILOT env = 150 stocks."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

COST, BUF = 0.004, 0.0015


def walk(o, h, l, c, e9, e21, e30, j, e, stop, rule):
    n = len(c); R = e - stop
    tgt = {"2R": 2, "3R": 3}.get(rule); lim = {"2R": 10, "3R": 15}.get(rule, 400); below = 0
    for k in range(j, min(n, j + lim + 1)):
        if l[k] <= stop:
            return (min(o[k], stop) if k > j else stop), k
        if tgt and h[k] >= e + tgt * R:
            return (max(o[k], e + tgt * R) if k > j else e + tgt * R), k
        if rule == "921" and k > j and e9[k] < e21[k] and k + 1 < n:
            return o[k + 1], k + 1
        if rule == "ema30" and k > j:
            below = below + 1 if c[k] < e30[k] else 0
            if below >= 2 and k + 1 < n:
                return o[k + 1], k + 1
    k = min(n - 1, j + lim); return c[k], k


def events(sym, x):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); n = len(c); C = x.CLOSE
    e9, e21, e30 = (C.ewm(span=s, adjust=False).mean().to_numpy() for s in (9, 21, 30))
    s200 = C.rolling(200).mean().to_numpy(); v20 = x.VOL.rolling(20).mean().shift(1).to_numpy()
    val = (C * x.VOL).rolling(20).mean().to_numpy() / 1e7
    hh = pd.Series(h).rolling(150).max().shift(1).to_numpy()
    sh = np.zeros(n, bool); sh[2:-2] = (h[2:-2] > h[1:-3]) & (h[2:-2] > h[:-4]) & (h[2:-2] >= h[3:-1]) & (h[2:-2] >= h[4:])
    out = []; last_ctl = -99
    for t in range(200, n - 1):
        if not (val[t] >= 2 and c[t] >= 100 and np.isfinite(hh[t])):
            continue
        R = hh[t]
        if not (c[t] > R and c[t - 1] <= R):
            continue
        kinds = []; info = {}
        if t - last_ctl >= 10:
            kinds.append(("control", l[t - 10:t].min())); last_ctl = t
        tch = []
        for k in range(t - 150, t - 2):
            if sh[k] and h[k] >= R * 0.98 and (not tch or k - tch[-1] >= 5):
                tch.append(k)
        if len(tch) >= 3 and t - tch[0] >= 40:
            ends = tch[1:] + [t]
            d = [1 - l[a:b].min() / R for a, b in zip(tch, ends)]
            tight = l[t - 5:t].min()
            if (all(d[i + 1] < d[i] for i in range(len(d) - 1)) and d[0] >= 0.10 and d[0] >= 2 * d[-1] and d[-1] <= 0.06
                    and h[t - 5:t].max() / tight - 1 <= 0.06 and (c[t - 5:t] <= R).all()):
                stop = l[tch[-1]:t].min()
                info = dict(R=float(R), touches=[str(x.index[k].date()) for k in tch], depths=[round(z * 100, 1) for z in d])
                kinds.append(("contracting", stop))
                if v20[t] and v[t] >= 1.5 * v20[t]:
                    kinds.append(("contracting + vol", stop))
                if c[t] > s200[t]:
                    kinds.append(("contracting + above 200d", stop))
        # v2 (28 Nov 2026, Amritpal: "a VCP is like an ascending triangle"): flat top = >= 3 touches within 1% of R, >= 10 sessions
        # apart; lows rising GRADUALLY - each pullback 30-80% of the one before; last <= 6%; base >= 30 sessions
        tc = []
        for k in range(t - 150, t - 2):
            if sh[k] and h[k] >= R * 0.99 and (not tc or k - tc[-1] >= 10):
                tc.append(k)
        if len(tc) >= 3 and t - tc[0] >= 30:
            ends = tc[1:] + [t]
            d2 = [1 - l[a:b].min() / R for a, b in zip(tc, ends)]
            if all(0.3 <= d2[i + 1] / d2[i] <= 0.8 for i in range(len(d2) - 1) if d2[i] > 0) and d2[-1] <= 0.06 and d2[0] >= 0.06:
                st2_ = l[tc[-1]:t].min()
                info = dict(R=float(R), touches=[str(x.index[k].date()) for k in tc], depths=[round(z * 100, 1) for z in d2])
                kinds.append(("triangle", st2_))
        for kind, stop in kinds:
            trig = h[t] * (1 + BUF); j = None
            for k in range(t + 1, min(n, t + 4)):
                if h[k] >= trig:
                    if o[k] > trig * 1.03:
                        break
                    j = k; break
                if l[k] < stop:
                    break
            if j is None:
                continue
            e = max(o[j], trig)
            if stop >= e or not 0.01 <= (e - stop) / e <= 0.12:
                continue
            row = dict(sym=sym, kind=kind, d=x.index[t], entry=x.index[j], e=e, risk=(e - stop) / e, stop=stop, **(info if kind != "control" else {}))
            for rule in ("2R", "3R", "921", "ema30"):
                px, k = walk(o, h, l, c, e9, e21, e30, j, e, stop, rule)
                row[rule + "R"] = (px / e - 1 - COST) / ((e - stop) / e); row[rule + "ret"] = px / e - 1 - COST; row[rule + "x"] = x.index[k]
            out.append(row)
    return out


def portfolio(T, C, days, rule, cap0=1_000_000):
    T = T.sort_values("entry"); byday = {d: g for d, g in T.groupby("entry")}; cash, pos, eq = cap0, [], {}
    for d in days:
        for p in [p for p in pos if p["exit"] <= d]:
            cash += p["q"] * p["e"] * (1 + p["ret"]); pos.remove(p)
        if d in byday:
            for r in byday[d].to_dict("records"):
                if len(pos) >= 10 or any(p["sym"] == r["sym"] for p in pos):
                    continue
                E = cash + sum(p["q"] * p["last"] for p in pos); amt = min(0.01 * E / r["risk"], 0.10 * E, cash)
                if amt < 0.01 * E:
                    continue
                cash -= amt; pos.append(dict(sym=r["sym"], q=amt / r["e"], e=r["e"], ret=r[rule + "ret"], exit=r[rule + "x"], last=r["e"]))
        for p in pos:
            px = C.get(p["sym"], {}).get(d)
            if px is not None and np.isfinite(px):
                p["last"] = px
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos)
    eq = pd.Series(eq); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.3)) * 100 - 100, (eq / eq.cummax() - 1).min() * 100


def main():
    P = FV.load()
    D = pd.DataFrame([e for s, x in P.items() for e in events(s, x)])
    C = {s: x.CLOSE.to_dict() for s, x in P.items()}
    days = sorted(set().union(*[set(x.index) for x in P.values()])); end = days[-1]
    print(f"R| stocks {len(P)} entries {len(D)}", flush=True)
    wins = (("last 1y", end - pd.DateOffset(years=1)), ("last 3y", end - pd.DateOffset(years=3)),
            ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2016+", pd.Timestamp("2016-01-01")))
    for kind in ("control", "contracting", "triangle"):
        Z = D[D.kind == kind]
        print(f"R| ===== {kind}: {len(Z)} trades ({len(Z) / 10:.0f}/yr), median risk {Z.risk.median() * 100:.1f}%", flush=True)
        for lab, st in wins:
            z = Z[Z.d >= st]
            if len(z) < 10:
                print(f"R|   {lab:15s} n {len(z)} (too few)", flush=True); continue
            parts = [f"{r} {z[r + 'R'].mean():+.2f}R ({(z[r + 'R'] > 0).mean() * 100:.0f}%)" for r in ("2R", "3R", "921", "ema30")]
            dd = [d for d in days if d >= st]
            pc = [portfolio(z, C, dd, r) for r in ("2R", "ema30")]
            print(f"R|   {lab:15s} n {len(z):5d} | " + " | ".join(parts) +
                  f" || portfolio 2R {pc[0][0]:+.1f}%/yr ({pc[0][1]:.0f}%), 30 EMA {pc[1][0]:+.1f}%/yr ({pc[1][1]:.0f}%)", flush=True)


def show():
    """print the last 6 'contracting' trades with daily bars (charts for Amritpal)."""
    import json
    P = FV.load(); D = pd.DataFrame([e for s, x in P.items() for e in events(s, x)])
    Z = D[D.kind == os.environ.get("KIND", "triangle")].sort_values("d").tail(6)
    for r in Z.to_dict("records"):
        x = P[r["sym"]]; i0 = max(0, x.index.get_loc(pd.Timestamp(r["touches"][0])) - 30); i1 = min(len(x), x.index.get_loc(r["entry"]) + 40)
        y = x.iloc[i0:i1]
        print("R|T " + json.dumps(dict(s=r["sym"], R=r["R"], touches=r["touches"], depths=r["depths"], bo=str(r["d"].date()), entry=str(r["entry"].date()),
              e=round(r["e"], 2), stop=round(r["stop"], 2), res={k: [round(r[k + "R"], 2), str(r[k + "x"].date())] for k in ("2R", "ema30")},
              bars=[[str(d.date()), *[round(float(v), 2) for v in row]] for d, row in zip(y.index, y[["OPEN", "HIGH", "LOW", "CLOSE", "VOL"]].to_numpy())])), flush=True)


if __name__ == "__main__":
    show() if os.environ.get("SHOW") else main()
