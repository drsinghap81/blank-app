"""Short-term cup baskets, daily and weekly (26 Nov 2026, Amritpal: "a trading cup basket for daily cup with all other industry
parameters intact, SL below the breakout candle wick, run it as 9/21 or cup depth, longer cups priority, same for weekly; buy only
when the high is crossed; all assets; 5 lakh capital").

Cups = tools/cupclose.py rules (the app's daily / weekly cup-close lists):
  daily : rim = highest high of the last 250 sessions (signal bar excluded), >= 20 sessions old, lowest close since <= -15%
  weekly: rim = highest high of the last 104 weeks, >= 26 weeks old, lowest close since <= -20%
  ETFs use the shallower index depths (-8% daily, -10% weekly); room to the next older peak >= the cup depth (or none = ATH)
Signal = the FIRST close above the rim (daily close / weekly close). Industry parameters as live: skip a stock whose industry is in
a Weak / Fading / Turning Pulse lane at the signal (ETFs have no industry -> allowed). Liquid: 20-day traded value >= Rs 1 cr, price >= 50.
Entry = buy-stop at the breakout candle's high + 0.15% (daily: next session only, or 5 sessions; weekly: any day of the next week);
gap above it fills at the open, more than 3% above it = skipped (the app's chase rule). Stop = the breakout candle's low (wick);
risk > 12% skipped. Exits tested:
  921     daily close with EMA 9 < EMA 21 -> next open (weekly basket: also the weekly EMA 9/21 version)
  depth   target = rim + cup depth (rim - cup low); 120-session limit
  first   target or 9/21, whichever comes first
Basket: Rs 5 L, 1% risk a trade (Rs 5,000), max 20% a position, max 10 open, cash only; when several trigger the same day the
LONGER cup goes first. 0.3% costs a round trip. PILOT env = 150 stocks. Survivor list: absolute numbers flattered."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "angel"))
import ath_confirm_test as AC  # noqa: E402
import combo_compare as CC  # noqa: E402

CAP, RISK, MAXPOS, NPOS, COST = 500_000.0, 0.01, 0.20, 10, 0.003
ETFS = ["NIFTYBEES", "BANKBEES", "JUNIORBEES", "MID150BEES", "GOLDBEES", "SILVERBEES", "MON100", "MAFANG", "ITBEES", "PSUBNKBEES",
        "CPSEETF", "PHARMABEES", "AUTOBEES", "HNGSNGBEES", "INFRABEES", "CONSUMBEES", "MOM100", "ALPHA", "MODEFENCE", "HEALTHIETF"]
WINDOWS = [("since 2025", "2025-01-01"), ("since 2024", "2024-01-01"), ("since Jul 2021 (after Covid)", "2021-07-01"), ("since 2017", "2017-01-01")]


def load_etfs():
    out = {}
    d = yf.download([s + ".NS" for s in ETFS], start="2005-01-01", auto_adjust=True, progress=False, group_by="column", threads=True)
    for s in ETFS:
        t = s + ".NS"
        try:
            x = pd.DataFrame({"O": d["Open"][t], "H": d["High"][t], "L": d["Low"][t], "C": d["Close"][t], "V": d["Volume"][t]}).dropna()
        except Exception:  # noqa: BLE001
            continue
        x = x[(x.C > 0) & (x.O > 0)]
        if len(x) > 400:
            x.index = pd.to_datetime(x.index).tz_localize(None); out[s] = x
    return out


def cup_at(hh, cc, i, K, B, D):
    """cup-close at bar i (cupclose.py rules) -> (rim index, rim, age, depth) or None"""
    lo = max(0, i - K); win = hh[lo:i]
    if len(win) < B + 3 or not np.isfinite(win).any():
        return None
    a = lo + int(np.nanargmax(win)); rim = float(hh[a]); age = i - a
    if not (cc[i] > rim and cc[i - 1] <= rim and age >= B):
        return None
    seg = cc[a + 1:i]; dep = float(np.nanmin(seg) / rim - 1) if len(seg) else 0.0
    if dep > D:
        return None
    above = np.flatnonzero(hh[:a] > cc[i])
    if len(above):
        j = int(above[-1]); res = float(np.nanmax(hh[max(0, j - B):min(a, j + B + 1)]))
        if res / cc[i] - 1 < -dep:
            return None
    return a, rim, age, dep


def walk(o, h, l, c, e9, e21, j0, stop, tgt, exit_rule, wk_exit=None):
    """from entry bar j0 (bought that day) -> (exit index, exit price, why). Stop / target intraday, 9/21 on the close -> next open."""
    n = len(c)
    for j in range(j0, n):
        if j > j0 and o[j] <= stop:
            return j, o[j], "stop"
        if l[j] <= stop:
            return j, stop, "stop"
        if tgt and exit_rule in ("depth", "first"):
            if j > j0 and o[j] >= tgt:
                return j, o[j], "target"
            if h[j] >= tgt:
                return j, tgt, "target"
        if exit_rule in ("921", "first") and j + 1 < n:
            bad = (wk_exit[j] if wk_exit is not None else e9[j] < e21[j])
            if bad:
                return j + 1, o[j + 1], "9/21"
        if exit_rule == "depth" and j - j0 >= 120 and j + 1 < n:
            return j + 1, o[j + 1], "time"
    j = n - 1
    return j, c[j], "open"


def trades_for(sym, x, etf, lane_of, tf):
    o, h, l, c, v = (x[k].to_numpy(float) for k in ("O", "H", "L", "C", "V")); D = x.index; n = len(c)
    val = (x.C * x.V).rolling(20).mean().to_numpy(float)
    e9 = x.C.ewm(span=9, adjust=False).mean().to_numpy(float); e21 = x.C.ewm(span=21, adjust=False).mean().to_numpy(float)
    out = []
    if tf == "D":
        K, B, Dp = 250, 20, (-0.08 if etf else -0.15)
        sig = [(i, i + 1, i + 1) for i in range(30, n - 1)]                      # (signal bar, first entry day, last entry day)
        H_, L_, C_ = h, l, c; sigD = D
        wkx = None
    else:
        W = x.resample("W-FRI").agg({"O": "first", "H": "max", "L": "min", "C": "last", "V": "sum"}).dropna()
        W = W[W.index <= D[-1] + pd.Timedelta(days=6)]
        if len(W) < 140:
            return []
        H_, L_, C_ = (W[k].to_numpy(float) for k in ("H", "L", "C")); sigD = W.index
        K, B, Dp = 104, 26, (-0.10 if etf else -0.20)
        pos = np.searchsorted(D.values, W.index.values, side="right")            # first daily bar after each week's end
        sig = [(i, int(pos[i]), int(pos[i + 1]) - 1 if i + 1 < len(pos) else n - 1) for i in range(30, len(W) - 1)]
        we9 = W.C.ewm(span=9, adjust=False).mean(); we21 = W.C.ewm(span=21, adjust=False).mean()
        bw = (we9 < we21); bw.index = bw.index.normalize()
        wend = pd.Series(D).dt.to_period("W-FRI").dt.end_time.dt.normalize()
        bad_w = wend.map(bw).fillna(False).astype(bool).to_numpy()
        lastday = pd.Series(D).groupby(wend).transform("max").to_numpy()
        wkx = bad_w & (D.values == lastday)                                          # only on the week's last session
    rm = pd.Series(H_).rolling(K, min_periods=B + 3).max().shift(1).to_numpy()
    for i, j1, j2 in sig:
        if j1 >= n or not (C_[i] > rm[i]):                                       # quick pre-filter: a close above the prior K-bar high
            continue
        cu = cup_at(H_, C_, i, K, B, Dp)
        if not cu:
            continue
        a, rim, age, dep = cu
        di = min(j1 - 1, n - 1) if tf == "W" else i
        if not etf and (not np.isfinite(val[di]) or val[di] < 1e7 or c[di] < 50):
            continue
        ln = "etf" if etf else lane_of(sym, D[di])
        trig = H_[i] * 1.0015; stop = L_[i]
        for ent in ("1", "5"):
            last = j2 if tf == "W" else (j1 if ent == "1" else min(n - 1, j1 + 4))
            if tf == "W" and ent == "5":
                continue
            fill = None
            for j in range(j1, last + 1):
                if l[j] <= stop:
                    break
                if h[j] >= trig:
                    fill = (j, max(o[j], trig)); break
            if not fill:
                continue
            j0, e = fill
            if e > trig * 1.03 or (e - stop) / e > 0.12 or e <= stop:
                continue
            tgt = rim * (1 - dep) if rim * (1 - dep) > e else None
            for xr in ("921", "depth", "first") + (("921w",) if tf == "W" else ()):
                jx, px, why = walk(o, h, l, c, e9, e21, j0, stop, tgt, "921" if xr == "921w" else xr, wkx if xr == "921w" else None)
                out.append(dict(sym=sym, tf=tf, ent=ent, xr=xr, etf=etf, lane=ln, age=int(age), dep=round(dep, 3), sd=sigD[i], d=D[j0], dx=D[jx],
                                e=float(e), stop=float(stop), x=float(px), why=why, ret=px / e - 1 - COST, R=(px - e) / (e - stop), open=why == "open"))
    return out


def basket(T, C, start):
    """Rs 5 L, 1% risk, max 20% a stock, 10 open, cash only; longer cups first on the same day. Daily MTM."""
    T = T[T.d >= start].sort_values(["d", "age"], ascending=[True, False])
    days = C.index[C.index >= pd.Timestamp(start)]
    cash = CAP; pos = {}; eq = []; ev = {}
    for r in T.itertuples():
        ev.setdefault(pd.Timestamp(r.d).normalize(), []).append(r)
    taken = 0
    for d in days:
        for k in [k for k, p in pos.items() if p["dx"] <= d]:
            p = pos.pop(k); cash += p["q"] * p["x"] * (1 - COST / 2)
        val = cash + sum(p["q"] * p["last"] for p in pos.values())
        for r in ev.get(d, []):
            if len(pos) >= NPOS or r.sym in pos:
                continue
            q = min(RISK * val / (r.e - r.stop), MAXPOS * val / r.e, cash / (r.e * (1 + COST / 2)))
            if q * r.e < 0.25 * min(RISK * val / (r.e - r.stop), MAXPOS * val / r.e) * r.e or q <= 0:
                continue
            cash -= q * r.e * (1 + COST / 2); taken += 1
            pos[r.sym] = dict(q=q, x=r.x, dx=pd.Timestamp(r.dx).normalize(), last=r.e)
        for s, p in pos.items():
            vv = C.at[d, s] if s in C.columns else np.nan
            if np.isfinite(vv):
                p["last"] = float(vv)
        eq.append(cash + sum(p["q"] * p["last"] for p in pos.values()))
    e = pd.Series(eq, index=days)
    yrs = max((e.index[-1] - e.index[0]).days / 365.25, 0.1); tot = e.iloc[-1] / CAP - 1
    yr = e.resample("YE").last(); yr = (yr / yr.shift(1).fillna(CAP) - 1) * 100
    return dict(cagr=round(((1 + tot) ** (1 / yrs) - 1) * 100, 1), total=round(tot * 100, 1), dd=round(((e / e.cummax()) - 1).min() * 100, 1),
                trades=taken, years={str(k.year): round(v, 1) for k, v in yr.items()})


def tstats(T):
    if not len(T):
        return dict(n=0)
    w = T[T.ret > 0].ret.sum(); ls = -T[T.ret <= 0].ret.sum()
    return dict(n=int(len(T)), avg=round(T.ret.mean() * 100, 2), win=round((T.ret > 0).mean() * 100), pf=round(w / ls, 2) if ls else None,
                avgR=round(T.R.mean(), 2), days=round(((T.dx - T.d).dt.days).mean()))


def main():
    nifty = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None)
    P = AC.load(); E = load_etfs()
    print("R| stocks", len(P), "etfs", len(E), flush=True)
    C = pd.DataFrame({s: x.C for s, x in {**P, **E}.items()}).sort_index()
    V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, V = C[ok], V[ok]
    nif = nifty.reindex(C.index).ffill()
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    LN = CC.lanes(C[[c for c in C.columns if c in P]], V, nif, IND)

    def lane_of(sym, d):
        g = ind_of.get(sym)
        if not g or g not in LN.columns or d not in LN.index:
            return "none"
        return LN.at[d, g]
    T = []
    for s, x in {**P, **E}.items():
        for tf in ("D", "W"):
            try:
                T += trades_for(s, x, s in E, lane_of, tf)
            except Exception as ex:  # noqa: BLE001
                print("err", s, tf, ex)
    T = pd.DataFrame(T); T = T[T.d >= "2016-06-01"]
    print("R| trades", len(T), flush=True)
    SK = ("weak", "fade", "bounce")
    res = {}
    for tf in ("D", "W"):
        for ent in (("1", "5") if tf == "D" else ("1",)):
            for xr in ("921", "depth", "first") + (("921w",) if tf == "W" else ()):
                for lane in ("lane", "nolane"):
                    S = T[(T.tf == tf) & (T.ent == ent) & (T.xr == xr)]
                    if lane == "lane":
                        S = S[~S.lane.isin(SK)]
                    key = f"{'Daily' if tf == 'D' else 'Weekly'} cup · entry {'next session' if ent == '1' else '5 sessions'}{'' if tf == 'D' else ' (next week)'} · exit {xr} · {lane}"
                    row = dict(trades=tstats(S), recent=tstats(S[S.d >= "2024-01-01"]),
                               etf=tstats(S[S.etf]), long=tstats(S[S.age >= S.age.median()]) if len(S) else {}, short=tstats(S[S.age < S.age.median()]) if len(S) else {})
                    row["basket"] = {w: basket(S, C, st) for w, st in WINDOWS}
                    res[key] = row
                    print("R|", key, json.dumps(row["trades"]), "| 2024+", json.dumps(row["recent"]), "| longer half", json.dumps(row["long"]),
                          "| shorter half", json.dumps(row["short"]), flush=True)
                    for w, b in row["basket"].items():
                        print("R|    ", w, json.dumps({k: b[k] for k in ("cagr", "dd", "trades", "total")}), flush=True)
                    print("R|     years", json.dumps(row["basket"]["since 2017"]["years"]), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(dict(generated=pd.Timestamp.now().isoformat(), pilot=bool(os.environ.get("PILOT")), results=res), open("data/research/cup_swing_test.json", "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
