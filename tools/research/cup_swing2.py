"""Short-term cup baskets, round 2 (26 Nov 2026, Amritpal: "my idea of short term is more trades and booked in 1-2 weeks type").
Same entry as cup_swing_test.py (first close above a cup rim -> buy next session above the breakout candle's high + 0.15%, stop
under the breakout candle's low, longer cups first, Rs 5 L, 1% risk, 20% max a stock, 10 open), but
  more signals - shorter / shallower cups:
    D1y  daily 250-session rim >= 20 sessions old, cup >= 15% deep (the app's daily cup)
    D6m  daily 125-session rim >= 15 old, >= 10% deep
    D3m  daily  63-session rim >= 10 old, >=  8% deep
    W1y  weekly 52-week rim >= 8 weeks old, >= 12% deep (buy any day of the next week)
    W2y  weekly 104-week rim >= 26 weeks old, >= 20% deep (the app's weekly cup)
  quick exits (all keep the wick stop):
    t10    out at the 10th session's close
    2R     target 2 x risk (1:2), else out at the 10th session's close
    2R15   1:2 target, at most 15 sessions; 3R15  1:3 target, at most 15 sessions (Amritpal: "1:2 or 1:3 trades")
    e9     a daily close below EMA 9 -> next open, at most 15 sessions
    pl     after +1R the stop trails the previous day's low, at most 15 sessions
    921    reference: EMA 9 < EMA 21 (no time limit)
Lane filter on / off as before. PILOT env = 150 stocks."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cup_swing_test as CS  # noqa: E402

SETS = {"D1y": ("D", 250, 20, -0.15, -0.08), "D6m": ("D", 125, 15, -0.10, -0.06), "D3m": ("D", 63, 10, -0.08, -0.05),
        "W1y": ("W", 52, 8, -0.12, -0.08), "W2y": ("W", 104, 26, -0.20, -0.10)}
EXITS = ("t10", "2R", "2R15", "3R15", "e9", "pl", "921")


def walk(o, h, l, c, e9, e21, j0, e, stop, xr):
    n = len(c); R = e - stop; st = stop; lim = {"t10": 9, "2R": 9, "2R15": 14, "3R15": 14, "e9": 14, "pl": 14}.get(xr)
    k = {"2R": 2, "2R15": 2, "3R15": 3}.get(xr)
    for j in range(j0, n):
        if j > j0 and o[j] <= st:
            return j, o[j], "stop"
        if l[j] <= st:
            return j, st, "stop"
        if k:
            t = e + k * R
            if j > j0 and o[j] >= t:
                return j, o[j], "target"
            if h[j] >= t:
                return j, t, "target"
        if lim is not None and j - j0 >= lim:
            return j, c[j], "time"
        if xr == "e9" and c[j] < e9[j] and j + 1 < n:
            return j + 1, o[j + 1], "ema9"
        if xr == "921" and e9[j] < e21[j] and j + 1 < n:
            return j + 1, o[j + 1], "9/21"
        if xr == "pl" and c[j] >= e + R:
            st = max(st, l[j])                                           # tomorrow's stop = today's low once +1R is reached
    return n - 1, c[n - 1], "open"


def trades_for(sym, x, etf, lane_of):
    o, h, l, c = (x[k].to_numpy(float) for k in ("O", "H", "L", "C")); D = x.index; n = len(c)
    val = (x.C * x.V).rolling(20).mean().to_numpy(float)
    e9 = x.C.ewm(span=9, adjust=False).mean().to_numpy(float); e21 = x.C.ewm(span=21, adjust=False).mean().to_numpy(float)
    W = x.resample("W-FRI").agg({"O": "first", "H": "max", "L": "min", "C": "last", "V": "sum"}).dropna()
    posW = np.searchsorted(D.values, W.index.values, side="right")
    out = []
    for name, (tf, K, B, Dp, Dpe) in SETS.items():
        dep_min = Dpe if etf else Dp
        if tf == "D":
            H_, L_, C_, sigD = h, l, c, D
            sig = [(i, i + 1, i + 1) for i in range(30, n - 1)]
        else:
            if len(W) < 40:
                continue
            H_, L_, C_ = (W[k].to_numpy(float) for k in ("H", "L", "C")); sigD = W.index
            sig = [(i, int(posW[i]), int(posW[i + 1]) - 1 if i + 1 < len(posW) else n - 1) for i in range(20, len(W) - 1)]
        rm = pd.Series(H_).rolling(K, min_periods=B + 3).max().shift(1).to_numpy()
        for i, j1, j2 in sig:
            if j1 >= n or not (C_[i] > rm[i]):
                continue
            cu = CS.cup_at(H_, C_, i, K, B, dep_min)
            if not cu:
                continue
            a, rim, age, dep = cu
            di = j1 - 1
            if not etf and (not np.isfinite(val[di]) or val[di] < 1e7 or c[di] < 50):
                continue
            ln = "etf" if etf else lane_of(sym, D[di])
            trig = H_[i] * 1.0015; stop = L_[i]; fill = None
            for j in range(j1, min(j2, n - 1) + 1):
                if l[j] <= stop:
                    break
                if h[j] >= trig:
                    fill = (j, max(o[j], trig)); break
            if not fill:
                continue
            j0, e = fill
            if e > trig * 1.03 or (e - stop) / e > 0.12 or e <= stop:
                continue
            age_d = age if tf == "D" else age * 5
            for xr in EXITS:
                jx, px, why = walk(o, h, l, c, e9, e21, j0, e, stop, xr)
                out.append(dict(sym=sym, set=name, xr=xr, etf=etf, lane=ln, age=int(age_d), dep=round(dep, 3), d=D[j0], dx=D[jx], e=float(e),
                                stop=float(stop), x=float(px), why=why, ret=px / e - 1 - CS.COST, R=(px - e) / (e - stop), open=why == "open"))
    return out


def main():
    nifty = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None)
    P = CS.AC.load(); E = CS.load_etfs()
    print("R| stocks", len(P), "etfs", len(E), flush=True)
    C = pd.DataFrame({s: x.C for s, x in {**P, **E}.items()}).sort_index()
    V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, V = C[ok], V[ok]
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    LN = CS.CC.lanes(C[[c for c in C.columns if c in P]], V, nifty.reindex(C.index).ffill(), IND)

    def lane_of(sym, d):
        g = ind_of.get(sym)
        return LN.at[d, g] if g and g in LN.columns and d in LN.index else "none"
    T = []
    for s, x in {**P, **E}.items():
        try:
            T += trades_for(s, x, s in E, lane_of)
        except Exception as ex:  # noqa: BLE001
            print("err", s, ex)
    T = pd.DataFrame(T); T = T[T.d >= "2016-06-01"]
    print("R| trades", len(T), flush=True)
    SK = ("weak", "fade", "bounce"); res = {}
    combos = [(s_,) for s_ in SETS] + [("D1y", "D6m", "D3m"), ("D6m", "W1y"), ("D1y", "D6m", "D3m", "W1y", "W2y")]
    for sets in combos:
        for xr in EXITS:
            for lane in ("lane", "nolane"):
                S = T[T.set.isin(sets) & (T.xr == xr)]
                if lane == "lane":
                    S = S[~S.lane.isin(SK)]
                S = S.sort_values(["d", "age"], ascending=[True, False]).drop_duplicates(["sym", "d"])   # same stock same day: once (longest cup)
                key = f"{'+'.join(sets)} · exit {xr} · {lane}"
                row = dict(trades=CS.tstats(S), recent=CS.tstats(S[S.d >= "2024-01-01"]),
                           yearly_trades=round(len(S[S.d >= "2017-01-01"]) / 9.9, 0))
                row["basket"] = {w: CS.basket(S, C, st) for w, st in CS.WINDOWS}
                res[key] = row
                b = row["basket"]
                print("R|", key, "| trades", json.dumps(row["trades"]), "| 2024+", json.dumps(row["recent"]), "| per yr", row["yearly_trades"], flush=True)
                print("R|    basket", " · ".join(f"{w}: {b[w]['cagr']}% / {b[w]['dd']}% ({b[w]['trades']})" for w in b), flush=True)
                print("R|    years", json.dumps(b["since 2017"]["years"]), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(dict(generated=pd.Timestamp.now().isoformat(), pilot=bool(os.environ.get("PILOT")), results=res), open("data/research/cup_swing2.json", "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
