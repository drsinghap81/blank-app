"""System combinations on Rs 20 L, compared over several windows (26 Nov 2026, Amritpal: "Try first [today's rules] and also try different
systems like bottom breakout, flags etc, various combinations, and let's compare").

Each window starts fresh with Rs 20 L and only takes trades that START inside it; open positions are marked at the daily close
(so the short 9 Nov window is a real mark-to-market). Windows, newest first: since 9 Nov 2026 (the paper book), 2026 so far,
since 2025, since 2024, since mid-2021, since 2017.
Systems (live rules, NSE, Yahoo daily checked against the bhavcopy, today's names -> survivors):
  mom_old / cup_old   Momentum / Cup 9/21, OLD entry: intraday cross of the level (tools/research/ath_confirm_test.py variant A)
  mom / cup           close confirmation (variants C / B: a daily close above the ATH-month high / the highest wick, buy next
                      session above that day's high + 0.15%); exits as live (30-week SMA weekly close / EMA9 < EMA21)
  +lane               skip industries in a Weak / Fading / Turning Pulse lane at the signal (lanes from the industry Pulse,
                      basic industries, same rule as the app)
  flag                flags / pennants / rectangles, the live rule (tools/research/flag_volume.py variant 8: tight <= 8%, volume
                      dries up, 1.5x breakout volume, room >= 0.8 x pole; buy the breakout close; stop flag low; exit a close
                      below the 21-day EMA)
  bottom              bottom patterns (W / tilted W / triple / inverse H&S, tools/pattern_scan.py rules): buy next open after the
                      first close above the neckline; out at the target (neckline + height), a close 4% (IHS 6%) under the
                      neckline, or after 120 sessions
  pulse               Pulse rotation (weekly, tools/paper20.pulse_picks; the RED-light skip not replayed)
  +TB                 the six Top Bottom bots, 1 lot each on pledge margin (tools/paper20.top_bottom), added on top
Book: equal slots of 10% of the book (a 50/50 book: 10 slots of 5% in each half), max 10 positions per sleeve, first come by
entry date; costs inside each system's returns (0.4% / 0.2% / 0.4% a round trip). PILOT env = 150 stocks."""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "angel"))
import ath_confirm_test as AC  # noqa: E402
AC.KEEP_OPEN = True
import flag_stops as FS  # noqa: E402
import flag_volume as FV  # noqa: E402
import pattern_scan as PS  # noqa: E402
import paper20 as P20  # noqa: E402

WINDOWS = [("since 9 Nov 2026", "2026-11-09"), ("2026 so far", "2026-01-01"), ("since 2025", "2025-01-01"), ("since 2024", "2024-01-01"),
           ("since Jul 2021", "2021-07-01"), ("since 2017", "2017-01-01")]
CAP = 2_000_000.0


def flags(sym, x):
    """live flag rule (flag_volume.py variant 8) -> trades"""
    y = x.rename(columns={"O": "OPEN", "H": "HIGH", "L": "LOW", "C": "CLOSE", "V": "VOL"})
    o, h, l, c, v = (y[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL")); D = y.index; n = len(c)
    e21 = pd.Series(c).ewm(span=21, adjust=False).mean().to_numpy(); v50 = pd.Series(v).rolling(50).mean().shift(1).to_numpy()
    Z = FS.zz(h, l); zh = [(z[1], z[2], z[3]) for z in Z if z[0] == 1]; out = []
    for s in FS.signals(y):
        t = s["t"]
        if D[t] < pd.Timestamp("2016-06-01") or t + 1 >= n:
            continue
        a, b, pk, lo_i = s["a"], s["b"], s["pk"], s["lo_i"]; stop = s["fl"]
        fv = v[a:b].mean(); pv = v[lo_i:pk + 1].mean(); base50 = v50[lo_i] if np.isfinite(v50[lo_i]) else v50[t]
        dry = bool(fv < 0.75 * pv and fv < base50); bvol = bool(v[t] >= 1.5 * v50[t] and v[t] >= v[a:b].max())
        tight = bool((h[a:b].max() - l[a:b].min()) / h[pk] <= 0.08)
        ent = c[t]; pole_h = h[pk] - l[lo_i]
        res = [p_ for i_, p_, cf in zh if cf < lo_i and i_ >= t - 750 and p_ > ent]
        room = (min(res) - ent) / pole_h if res and pole_h > 0 else 9.0
        if not (dry and bvol and tight and room >= 0.8) or not stop < ent:
            continue
        j, r, _ = FV.trail(o, h, l, c, e21, t, ent, stop, same_day=False)
        out.append(dict(sym=sym, sys="flag", d=D[t], dx=D[j], e=float(ent), x=float(ent * (1 + r)), ret=r - 0.002, open=j == n - 1))
    return out


def bottoms(sym, x):
    """bottom-pattern breakouts (tools/research/bottom_filters.py rules) -> trades with exit dates"""
    c = x.C.to_numpy(float); h = x.H.to_numpy(float); o = x.O.to_numpy(float); n = len(c); D = x.index
    if n < 300:
        return []
    piv = PS.zigzag(c, PS.THR)
    rmax = pd.Series(c).rolling(250, min_periods=120).max().shift(1).to_numpy(); rmin = pd.Series(c).rolling(250, min_periods=120).min().to_numpy()
    out, seen = [], set()
    for k in range(len(piv)):
        if piv[k][0] != "L":
            continue
        for typ, lows, peaks, neck in PS.patterns_at(piv, k):
            first = lows[0]; i1 = first[1]
            if np.isnan(rmax[i1]) or rmax[i1] < first[2] * (1 + PS.FALL) or first[2] > rmin[i1] * 1.05:
                continue
            last = lows[-1]; sig = None
            for j in range(last[3], min(n, last[1] + 60)):
                if c[j] < last[2]:
                    break
                if c[j] > neck:
                    sig = j; break
            if sig is None or sig + 1 >= n or sig in seen or c[sig] < 100:
                continue
            seen.add(sig)
            low0 = min(l_[2] for l_ in lows); tgt = neck + (neck - low0); sl = neck * (0.94 if typ == "IHS" else 0.96)
            e0 = o[sig + 1]; xi, xp = None, None
            for j in range(sig + 1, min(n, sig + 121)):
                if c[j] < sl:
                    xi, xp = j, c[j]; break
                if h[j] >= tgt:
                    xi, xp = j, max(tgt, o[j]); break
            if xi is None:
                xi = min(n - 1, sig + 120); xp = c[xi]
            out.append(dict(sym=sym, sys="bottom", d=D[sig + 1], dx=D[xi], e=float(e0), x=float(xp), ret=xp / e0 - 1 - 0.004, open=xi == n - 1 and sig + 120 > n - 1))
    return out


def lanes(C, V, nifty, IND):
    """daily Pulse lane per basic industry (the app's rule on 1-week / 1-month / 1-quarter shares of trending members)"""
    liq = ((C * V).rolling(60, min_periods=40).median() >= P20.MINVAL) & (C >= P20.MINPX)
    rpi = lambda k: 100 * (C / C.shift(k)).div(nifty / nifty.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = ((w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52) & liq).astype(float)
    S = {n_: tr.rolling(n_).mean() for n_ in (5, 21, 63)}; out = {}
    G = {n_: pd.DataFrame({k: S[n_][[s for s in v if s in C.columns]].where(liq[[s for s in v if s in C.columns]]).mean(axis=1) * 100
                           for k, v in IND.items() if len([s for s in v if s in C.columns]) >= 3}) for n_ in S}
    q, m, wk = G[63], G[21], G[5]
    hi, lo = q.quantile(0.6, axis=1), q.quantile(0.4, axis=1)
    up = (wk > m) & (m > q) & (wk - q >= 10); dn = (wk < m) & (m < q) & (q - wk >= 10)
    strong = q.ge(hi, axis=0); weak = q.le(lo, axis=0)
    L = pd.DataFrame("mid", index=q.index, columns=q.columns)
    L[strong & up] = "build"; L[strong & dn] = "fade"; L[strong & ~up & ~dn] = "hold"; L[weak & up] = "bounce"; L[weak & ~up] = "weak"
    L[q.isna()] = "none"
    return L


def book(sleeves, days, C):
    """sleeves: list of (weight, trades DataFrame). Daily MTM; equal slots weight/10 of the book at each entry."""
    cash = {i: w * CAP for i, (w, _) in enumerate(sleeves)}; pos = {}; eq = []
    ev = {}
    for i, (w, T) in enumerate(sleeves):
        for r in T.itertuples():
            ev.setdefault(pd.Timestamp(r.d).normalize(), []).append((i, r))
    for d in days:
        val = sum(cash.values()) + sum(p["q"] * p["last"] for p in pos.values())
        for key in [k for k, p in pos.items() if p["dx"] <= d]:
            p = pos.pop(key); cash[p["i"]] += p["q"] * p["x"]
        for i, r in sorted(ev.get(d, []), key=lambda z: (z[0], z[1].sym)):
            w = sleeves[i][0]
            if len([1 for p in pos.values() if p["i"] == i]) >= 10 or (i, r.sym) in pos:
                continue
            amt = min(w * val / 10, cash[i])
            if amt < 0.5 * w * val / 10:
                continue
            q = amt / r.e; cash[i] -= amt
            pos[(i, r.sym)] = dict(i=i, q=q, x=r.e * (1 + r.ret), dx=pd.Timestamp(r.dx).normalize(), last=r.e, sym=r.sym)
        for p in pos.values():
            v = C.at[d, p["sym"]] if p["sym"] in C.columns and d in C.index else np.nan
            if np.isfinite(v):
                p["last"] = float(v)
        eq.append(sum(cash.values()) + sum(p["q"] * p["last"] for p in pos.values()))
    return pd.Series(eq, index=days)


def stats(e, tb=None):
    if tb is not None:
        e = e + tb.reindex(e.index).ffill().fillna(0)
    yrs = max((e.index[-1] - e.index[0]).days / 365.25, 1 / 365)
    tot = e.iloc[-1] / CAP - 1; dd = (e / e.cummax() - 1).min()
    return dict(ret=round(tot * 100, 2), cagr=round(((1 + tot) ** (1 / yrs) - 1) * 100, 1) if yrs >= 0.9 else None, dd=round(dd * 100, 1))


def main():
    nifty = yf.download("^NSEI", start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None)
    reg = (nifty > nifty.rolling(200).mean()).to_dict()
    P = AC.load()
    C = pd.DataFrame({s: x.C for s, x in P.items()}).sort_index(); V = pd.DataFrame({s: x.V for s, x in P.items()}).reindex(C.index)
    ok = C.notna().mean(axis=1) > 0.3; C, V = C[ok], V[ok]
    nif = nifty.reindex(C.index).ffill()
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in (G.get("nse") or {}).get("rows") or []:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    ind_of = {s: k for k, v in IND.items() for s in v}
    T = []
    for s, x in P.items():
        try:
            T += AC.trades_for(s, x, reg); T += flags(s, x); T += bottoms(s, x)
        except Exception as ex:  # noqa: BLE001
            print("err", s, ex)
    T = pd.DataFrame(T); T = T[T.d >= "2016-06-01"].copy()
    T["k"] = np.where(T.sys == "tf", np.where(T.v == "B", "cup", np.where(T.v == "A", "cup_old", "x")),
                      np.where(T.sys == "mom", np.where(T.v == "C", "mom", np.where(T.v == "A", "mom_old", "x")), T.sys))
    T = T[T.k != "x"]
    LN = lanes(C, V, nif, IND)

    def lane_at(r):
        g = ind_of.get(r.sym)
        if not g or g not in LN.columns:
            return "none"
        i = LN.index.searchsorted(pd.Timestamp(r.d)) - 1
        return LN[g].iloc[i] if i >= 0 else "none"
    T["lane"] = [lane_at(r) for r in T.itertuples()]
    good = ~T.lane.isin(["weak", "fade", "bounce"])
    print("R| trades:", T.k.value_counts().to_dict(), "| lane known", round((T.lane != "none").mean() * 100), "%", flush=True)
    # Pulse rotation as trades: a holding from the Monday open after its Friday pick to the Monday open after it drops out
    PP = P20.pulse_picks(C, V, nif, IND, since=pd.Timestamp("2016-12-01"))
    fr = sorted(PP); O = pd.DataFrame({s: x.O for s, x in P.items()}).reindex(C.index); PT = []; cur = {}
    for f in fr:
        nxt = C.index[C.index > f]
        if not len(nxt):
            break
        dd = nxt[0]; want = set(PP[f]["picks"])
        for s in list(cur):
            if s not in want:
                e, d0 = cur.pop(s); xp = O.at[dd, s] if np.isfinite(O.at[dd, s]) else C.at[dd, s]
                PT.append(dict(sym=s, sys="pulse", d=d0, dx=dd, e=e, x=float(xp), ret=xp / e - 1 - 0.004))
        for s in want:
            if s not in cur and s in O.columns and np.isfinite(O.at[dd, s]):
                cur[s] = (float(O.at[dd, s]), dd)
    for s, (e, d0) in cur.items():
        xp = float(C[s].dropna().iloc[-1]); PT.append(dict(sym=s, sys="pulse", d=d0, dx=C.index[-1], e=e, x=xp, ret=xp / e - 1 - 0.004))
    PT = pd.DataFrame(PT)
    print("R| pulse holdings", len(PT), flush=True)
    # Top Bottom overlay: six bots from 2017, P&L in Rs per day
    TBl = []
    for sym, over, _ in P20.TB_SET:
        try:
            dly, *_ = P20.top_bottom(sym, over, start=pd.Timestamp("2017-01-02"))
            TBl.append(pd.Series({k: v["pnl"] for k, v in dly.items()}))
        except Exception as ex:  # noqa: BLE001
            print("tb", sym, ex)
    TBs = None
    if TBl:
        ix = sorted(set().union(*[set(x.index) for x in TBl]))
        TBs = sum(x.reindex(ix).ffill().fillna(0) for x in TBl)
    sel = lambda *ks, lane=False: T[T.k.isin(ks) & (good if lane else True)]  # noqa: E731
    COMBOS = [("Momentum + Cup, OLD intraday entry", [(1.0, sel("mom_old", "cup_old"))], False),
              ("Momentum + Cup, close confirm", [(1.0, sel("mom", "cup"))], False),
              ("Momentum + Cup, close confirm + lane", [(1.0, sel("mom", "cup", lane=True))], False),
              ("Flags (live rule)", [(1.0, sel("flag"))], False),
              ("Bottom breakouts", [(1.0, sel("bottom"))], False),
              ("Mom+Cup(lane) + Flags", [(1.0, pd.concat([sel("mom", "cup", lane=True), sel("flag")]))], False),
              ("Mom+Cup(lane) + Bottoms", [(1.0, pd.concat([sel("mom", "cup", lane=True), sel("bottom")]))], False),
              ("Mom+Cup(lane) + Flags + Bottoms", [(1.0, pd.concat([sel("mom", "cup", lane=True), sel("flag"), sel("bottom")]))], False),
              ("Pulse rotation", [(1.0, PT)], False),
              ("Pulse 50 / Mom+Cup(lane) 50", [(0.5, PT), (0.5, sel("mom", "cup", lane=True))], False),
              ("Pulse 50 / Mom+Cup(lane)+Flags 50", [(0.5, PT), (0.5, pd.concat([sel("mom", "cup", lane=True), sel("flag")]))], False),
              ("Pulse 50 / Mom+Cup OLD 50 (paper book now)", [(0.5, PT), (0.5, sel("mom_old", "cup_old"))], False),
              ("Pulse 50 / Mom+Cup(lane) 50 + Top Bottom", [(0.5, PT), (0.5, sel("mom", "cup", lane=True))], True),
              ("Pulse 50 / Mom+Cup(lane)+Flags 50 + Top Bottom", [(0.5, PT), (0.5, pd.concat([sel("mom", "cup", lane=True), sel("flag")]))], True),
              ("Mom+Cup(lane) + Top Bottom", [(1.0, sel("mom", "cup", lane=True))], True)]
    res = {}
    for wn, ws in WINDOWS:
        days = [d for d in C.index if d >= pd.Timestamp(ws)]
        if not days:
            continue
        nf = nif.reindex(days); nret = round((nf.iloc[-1] / nf.iloc[0] - 1) * 100, 2)
        print(f"R| ===== {wn} ({days[0].date()} -> {days[-1].date()}, {len(days)} sessions) | Nifty {nret:+.2f}% =====", flush=True)
        for nm, sl, tb in COMBOS:
            sl2 = [(w, X[pd.to_datetime(X.d) >= pd.Timestamp(ws)]) for w, X in sl]
            e = book(sl2, days, C)
            tbw = None
            if tb and TBs is not None:
                t_ = TBs.reindex(sorted(set(TBs.index) | set(days))).ffill().reindex(days).fillna(0); tbw = t_ - t_.iloc[0]
            st = stats(e, tbw); res.setdefault(wn, {})[nm] = st
            print(f"R| {nm:50s} return {st['ret']:+7.2f}% | {'CAGR ' + format(st['cagr'], '+.1f') + '%' if st['cagr'] is not None else '':12s} | worst fall {st['dd']:.1f}% | trades {sum(len(X) for _, X in sl2)}", flush=True)
    json.dump(res, open("data/research/combo_compare.json", "w"), indent=1)


if __name__ == "__main__":
    main()
