"""Linda Raschke's "Holy Grail" pullback (21 Nov 2026, Amritpal pasted the rules). Daily version on NSE stocks, 2016 -> today.

Rules as given, daily bars (the hourly entry refinement needs 60-minute history Yahoo keeps for ~2 years only - not in this run):
  setup  : ADX(14) > 30 and rising; trend direction by DMI (+DI > -DI for longs); a new swing high in the last 10 sessions
           (a 20-day closing-high... we use: the 20-day HIGH was set within the last 10 sessions), then a bar whose LOW touches or
           slightly pierces the 20 EMA (low <= EMA20 and close >= 98% of EMA20)
  entry  : buy-stop one tick above that bar's high, valid the next session only (a new touch bar re-arms it at its own high)
  stop   : just below the pullback's swing low (lowest low from the swing-high bar to the touch bar) - 0.1%; skip if > 12% away
  exit   : half at the prior swing high (a retest); the rest trails below the lowest low of the last 3 sessions (daily stand-in
           for "below each higher hourly swing low"), raised only. Stop and target in the same bar -> stop first (conservative).
  shorts : the mirror image, F&O stocks only (cash shorts can't be held overnight in India), reported apart.
Variants: as given | ADX > 25 | no half exit (trail all) | half at 2R instead of the swing high.
Portfolio: Rs 20 L, 1% risk a trade, max 10 positions, <= 20% of equity each, 0.2% cost a round trip, best ADX first.
Survivors only (Yahoo). Reporting newest first (last 1/2/3/5 years, each year), bull vs bear days (Nifty vs 200-day), ex-Covid,
and trades split by the market traffic light. PILOT env = 150 stocks. Output data/research/holy_grail.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002
MINVAL = 2e7
STRICT = False
TRAIL = 3      # trail below the lowest low of the last TRAIL sessions


def adx(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]; ph = np.roll(h, 1); ph[0] = h[0]; pl = np.roll(l, 1); pl[0] = l[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    up, dn = h - ph, pl - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    w = lambda x: pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()  # noqa: E731
    atr = w(tr); pdi = 100 * w(pdm) / atr; ndi = 100 * w(ndm) / atr
    dx = 100 * np.abs(pdi - ndi) / np.where(pdi + ndi == 0, np.nan, pdi + ndi)
    return w(np.nan_to_num(dx)), pdi, ndi


def trades_for(sym, x, side, adx_min, half_mode):
    """x: one stock's daily frame (Date index; OPEN HIGH LOW CLOSE val). Returns a list of trade dicts (whole-trade return incl. half exit)."""
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); val = x.val.to_numpy(float); dts = x.index
    n = len(c)
    if n < 80:
        return []
    A, pdi, ndi = adx(h, l, c)
    ema = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
    if side < 0:                                   # mirror prices so one routine handles both sides
        o, h, l, c, ema = -o, -l, -h, -c, -ema
        pdi, ndi = ndi, pdi
    hh20 = pd.Series(h).rolling(20).max().to_numpy()
    out = []; i = 30; busy_until = -1
    while i < n - 1:
        if i <= busy_until:
            i += 1; continue
        ok = (A[i] > adx_min and pdi[i] > ndi[i] and val[i] >= MINVAL and (A[i] > A[i - 1] if STRICT else True))
        if ok:
            k_hi = i - 9 + int(np.argmax(h[i - 9:i + 1]))          # swing high bar within the last 10 sessions
            swing = h[k_hi]
            # "ADX above 30 and rising": ADX normally dips during the pullback itself, so 'rising' is checked into the swing
            # high (ADX at the swing bar above its value 5 sessions earlier); STRICT = rising on the touch bar too
            ok = (swing >= hh20[i] and k_hi < i and k_hi >= 5 and A[k_hi] > A[k_hi - 5] and l[i] <= ema[i]
                  and c[i] >= (ema[i] - 0.02 * abs(ema[i])))
        if not ok:
            i += 1; continue
        trig = h[i] + abs(h[i]) * 0.0005
        stop = np.min(l[k_hi:i + 1]) - abs(np.min(l[k_hi:i + 1])) * 0.001
        j = i + 1
        if h[j] < trig:                            # not triggered next session
            i += 1; continue
        e = max(trig, o[j])
        if e <= stop or (e - stop) / abs(e) > 0.12:
            i += 1; continue
        R = e - stop; tgt = swing if half_mode == "swing" else e + 2 * R
        if tgt <= e:
            tgt = e + R
        stp = stop; half_px = None; k = j; exit_px = None; exit_i = None
        while k < n:
            lo, hi_, op = l[k], h[k], o[k]
            if lo <= stp:                          # stop / trail first (conservative)
                px = min(op, stp) if k > j else stp
                exit_px, exit_i = px, k; break
            if half_mode != "none" and half_px is None and hi_ >= tgt:
                half_px = max(op, tgt) if k > j else tgt
                stp = max(stp, e)                  # rest: at least break-even
            if k >= j + TRAIL - 1:
                stp = max(stp, np.min(l[k - TRAIL + 1:k + 1]) - abs(np.min(l[k - TRAIL + 1:k + 1])) * 0.001)
            k += 1
        if exit_px is None:
            exit_px, exit_i = c[-1], n - 1
        u = lambda px: (px - e) / abs(e)           # works for mirrored (short) prices too  # noqa: E731
        gross = 0.5 * u(half_px) + 0.5 * u(exit_px) if half_px is not None else u(exit_px)
        ret = gross - COST
        out.append(dict(sym=sym, side=side, sig=dts[i], entry=dts[j], exit=dts[exit_i], e=abs(e), stop=abs(stop), risk=abs(R / e),
                        ret=ret, r_mult=ret / abs(R / e), half=half_px is not None, days=exit_i - j, adx=float(A[i]), open=exit_i == n - 1))
        busy_until = exit_i
        i = exit_i + 1
    return out


def portfolio(T, C, days, maxpos=10, risk=0.01, cap0=2_000_000):
    T = T.sort_values(["entry", "adx"], ascending=[True, False])
    byday = {d: g for d, g in T.groupby("entry")}
    cash, pos, eq = cap0, [], {}
    for d in days:
        for p in [p for p in pos if p["exit"] <= d]:
            cash += p["q"] * p["e"] * (1 + p["ret"]); pos.remove(p)
        if d in byday:
            for r in byday[d].itertuples():
                if len(pos) >= maxpos or any(p["sym"] == r.sym for p in pos):
                    continue
                E = cash + sum(p["q"] * p["last"] for p in pos)
                q = min(risk * E / (r.e * r.risk), 0.20 * E / r.e, cash / r.e)
                if q * r.e < 0.01 * E:
                    continue
                cash -= q * r.e; pos.append(dict(sym=r.sym, q=q, e=r.e, ret=r.ret, exit=r.exit, last=r.e, side=r.side))
        for p in pos:
            px = C.get(p["sym"], {}).get(d)
            if px is not None and np.isfinite(px):
                p["last"] = px if p["side"] > 0 else p["e"] * (2 - px / p["e"])
        eq[d] = cash + sum(p["q"] * p["last"] for p in pos)
    return pd.Series(eq)


def report(eq, bull):
    eq = eq.sort_index(); end = eq.index[-1]; yrs = (end - eq.index[0]).days / 365.25; out = {}
    out["CAGR"] = round((float(eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1)
    out["max DD"] = round(float((eq / eq.cummax() - 1).min()) * 100, 1)
    for y in (1, 2, 3, 5):
        e = eq[eq.index >= end - pd.DateOffset(years=y)]
        out[f"{y}y"] = round((float(e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1)
    yr = eq.resample("YE").last(); yr = pd.concat([eq.iloc[:1], yr]).pct_change().dropna()
    out["years"] = {str(k.year): round(v * 100, 1) for k, v in sorted(yr.items(), reverse=True)}
    r = eq.pct_change().dropna(); b = bull.reindex(r.index).fillna(False).astype(bool).values
    ann = lambda x: round(float((1 + x).prod() ** (252 / max(1, len(x))) - 1) * 100, 1)  # noqa: E731
    out["bull/bear a year"] = [ann(r[b]), ann(r[~b])]
    cov = np.asarray((r.index >= "2020-02-15") & (r.index <= "2020-12-31")); rx = r[~cov]; ex = (1 + rx).cumprod()
    out["ex-Covid"] = [ann(rx), round(float((ex / ex.cummax() - 1).min()) * 100, 1)]
    return out


def tstats(T):
    if not len(T):
        return dict(n=0)
    return dict(n=len(T), avg=round(T.ret.mean() * 100, 2), med=round(T.ret.median() * 100, 2), win=round((T.ret > 0).mean() * 100),
                avgR=round(T.r_mult.mean(), 2), half_hit=round(T.half.mean() * 100), hold=float(T.days.median()), risk=round(T.risk.median() * 100, 1))


def main():
    d, _ = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"])
    fno = set(pd.read_csv("data/universe/fno_stocks.csv").Symbol.astype(str))
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    try:
        import light_distribution as LD
        L = LD.light_series(d)
    except Exception as e:  # noqa: BLE001
        print("light unavailable", e); L = None
    C = {s: g.set_index("Date").CLOSE.astype(float).to_dict() for s, g in d.groupby("SYMBOL")}
    days = sorted(d.Date[d.Date >= "2016-06-01"].unique())
    print("R| panel", d.SYMBOL.nunique(), "stocks", flush=True)
    res = dict(method=__doc__, runs={})
    VAR = [("as given (ADX>30, half at swing high)", 30, "swing"), ("ADX > 25", 25, "swing"), ("no half exit, trail all", 30, "none"),
           ("half at 2R", 30, "2R")]
    global STRICT, TRAIL
    VAR = VAR + [("strict: ADX rising on the touch bar", 30, "swing"), ("looser trail: 10-day low", 30, "swing")]
    for nm, amin, hm in VAR:
        STRICT = nm.startswith("strict"); TRAIL = 10 if nm.startswith("looser") else 3
        rows = []
        for s, g in d.groupby("SYMBOL"):
            x = g.set_index("Date")
            rows += trades_for(s, x, 1, amin, hm)
            if s.replace(".NS", "") in fno:
                rows += trades_for(s, x, -1, amin, hm)
        T = pd.DataFrame(rows)
        if not len(T):
            print("R|", nm, "no trades"); continue
        T = T[T.entry >= "2016-06-01"]
        for side, lbl in ((1, "LONG"), (-1, "SHORT (F&O)")):
            X = T[T.side == side]
            if not len(X):
                continue
            st = tstats(X); eq = portfolio(X, C, days); rp = report(eq, bull)
            k = f"{lbl} | {nm}"; res["runs"][k] = dict(trades=st, port=rp)
            print(f"R| {k} | trades {st}", flush=True)
            print(f"R| {k} | portfolio {rp}", flush=True)
            if L is not None and side == 1 and nm.startswith("as given"):
                X = X.assign(light=[L.iloc[max(0, L.index.searchsorted(pd.Timestamp(t)) - 1)] if len(L) else None for t in X.entry])
                print("R|", k, "| by light", {lt: tstats(X[X.light == lt]) for lt in ("GREEN", "AMBER", "RED")}, flush=True)
                end = X.entry.max()
                print("R|", k, "| trades newest first", {f"last {y}y": tstats(X[X.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)}, flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/holy_grail.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
