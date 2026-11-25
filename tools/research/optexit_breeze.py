"""Option trader exits on ICICI Breeze 1-minute history of EXPIRED Nifty / Bank Nifty weekly options (26 Nov 2026, Amritpal: "if you
have Bank Nifty or Nifty, test on those" - Angel only serves live contracts, so the server test sees ~3 weeks).
Data: Breeze download from his PC (tools/breeze/fetch_intraday.py): out/<SYM>/<expiry>/INDEX.csv and CE<strike>.csv / PE<strike>.csv
(1-minute, last 5 trading days before each weekly expiry, ATM +-10 strikes). Resampled to 5-minute bars from 09:15.
Contract each day: the strike nearest the index's previous close (as the live trader), CE and PE of that expiry.
Entry = the paper trader (tools/live_server/opt_bt.py): 5-minute close with RSI(14) of the option crossing above 60, option above its
session VWAP, the other option below its VWAP, close above the upper Bollinger band (20, 2), no entries 11:00-14:30 or after 15:00;
CE only while the index is above yesterday's close, PE only while below (ONE index here - the live rule also needs Bank Nifty).
No PCR condition (stock PCR quintiles don't exist for indices). Buy-stop above the signal candle's high for 3 candles; stop = signal
low (min 3%); intraday. Exits = the server test's ten (opt_bt.exit_sim / entry_sim), 1% of premium cost, R and % of premium.
Usage: python optexit_breeze.py <path to out/NIFTY> [<path to out/BANKNIFTY>]"""
import os
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "live_server"))
import opt_bt as O  # noqa: E402

COST = O.COST
LOOSE = bool(os.environ.get("LOOSE"))     # smoke tests only: drop the VWAP / BB / index conditions
MODES = [("ema5", "5 EMA close (live)"), ("x_be1", "5 EMA + breakeven at 1R"), ("x_half15", "half at 1.5R + 5 EMA"),
         ("x_prevlow", "previous candle low trail"), ("x_be1_prevlow", "breakeven 1R then prev-low trail"), ("x_ema3", "3 EMA close"),
         ("x_atr2", "2 ATR trail"), ("x_t15_be", "target 1.5R, breakeven at 1R"), ("1.5", "target 1.5R"), ("2.0", "target 2R"),
         ("3.0", "target 3R (basket rule)")]


def bars5(f):
    x = pd.read_csv(f)
    if x.empty or "datetime" not in x:
        return []
    x["datetime"] = pd.to_datetime(x["datetime"]).dt.tz_localize(None)
    x = x.set_index("datetime").sort_index()
    x = x[(x.index.time >= pd.Timestamp("09:15").time()) & (x.index.time < pd.Timestamp("15:30").time())]
    v = x["volume"] if "volume" in x else pd.Series(0, index=x.index)
    r = pd.DataFrame({"o": x.open.resample("5min", origin="start_day", offset="15min").first(), "h": x.high.resample("5min", origin="start_day", offset="15min").max(),
                      "l": x.low.resample("5min", origin="start_day", offset="15min").min(), "c": x.close.resample("5min", origin="start_day", offset="15min").last(),
                      "v": v.resample("5min", origin="start_day", offset="15min").sum()}).dropna(subset=["c"])
    return [(t.strftime("%Y-%m-%d %H:%M"), float(a.o), float(a.h), float(a.l), float(a.c), float(a.v)) for t, a in r.iterrows()]


def run(root):
    sym = os.path.basename(os.path.normpath(root)); trades = []
    exps = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for ex in exps:
        D = os.path.join(root, ex); fi = os.path.join(D, "INDEX.csv")
        if not os.path.exists(fi):
            continue
        I = pd.read_csv(fi)
        if I.empty:
            continue
        I["datetime"] = pd.to_datetime(I["datetime"]).dt.tz_localize(None); I = I.set_index("datetime").sort_index()
        closes = I.close.groupby(I.index.date).last(); days = sorted(closes.index)
        strikes = sorted({int(f[2:-4]) for f in os.listdir(D) if f[:2] in ("CE", "PE") and f[2:-4].isdigit()})
        if not strikes:
            continue
        for di in range(1, len(days)):
            d = days[di]; pc = float(closes.iloc[di - 1]); k = min(strikes, key=lambda s: abs(s - pc))
            fc, fp = os.path.join(D, f"CE{k}.csv"), os.path.join(D, f"PE{k}.csv")
            if not (os.path.exists(fc) and os.path.exists(fp)):
                continue
            C, P = bars5(fc), bars5(fp)
            if len(C) < 30 or len(P) < 30:
                continue
            ix = I[I.index.date == d].close
            for side, A, B in (("CE", C, P), ("PE", P, C)):
                c = [x[4] for x in A]; rs = O.rsi_series(c); bbu = O.bb_upper(c); em5 = O.ema(c, 5); em3 = O.ema(c, 3)
                trA = [max(x[2] - x[3], abs(x[2] - A[q - 1][4]), abs(x[3] - A[q - 1][4])) if q else x[2] - x[3] for q, x in enumerate(A)]
                atr = [sum(trA[max(0, q - 13):q + 1]) / len(trA[max(0, q - 13):q + 1]) for q in range(len(trA))]
                ia = [i for i, x in enumerate(A) if x[0][:10] == str(d)]
                if len(ia) < 3:
                    continue
                bmap = {}; pv = vv = 0.0
                for x in B:
                    if x[0][:10] == str(d):
                        pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]; bmap[x[0]] = (x[4], pv / vv if vv else x[4])
                pv = vv = 0.0; busy = -1
                for i in ia:
                    x = A[i]; pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]; vw = pv / vv if vv else x[4]
                    t = x[0][11:16]
                    if i <= busy or t >= "15:00" or "11:00" <= t < "14:30" or i < 1 or rs[i] is None or rs[i - 1] is None or not (rs[i] > 60 >= rs[i - 1]):
                        continue
                    ob = bmap.get(x[0])
                    if not LOOSE and (not ob or not (x[4] > vw and ob[0] < ob[1]) or bbu[i] is None or not x[4] > bbu[i]):
                        continue
                    ts = pd.Timestamp(x[0]) + pd.Timedelta(minutes=5)          # the signal candle's close
                    iv = ix[ix.index <= ts]
                    if iv.empty:
                        continue
                    up = float(iv.iloc[-1]) > pc
                    if (side == "CE") != up and not LOOSE:
                        continue
                    O_, H_, L_, C_ = [b[1] for b in A], [b[2] for b in A], [b[3] for b in A], [b[4] for b in A]
                    res = {}
                    for m, _ in MODES:
                        if m.startswith("x_"):
                            r = O.exit_sim(O_, H_, L_, C_, i, ia[-1], m, em3=em3, em5=em5, atr=atr)
                            if r:
                                e, risk, how, xp = r; res[m] = ((xp - e) / risk - COST * e / risk, (xp / e - 1 - COST) * 100, how)
                        else:
                            tr = O.entry_sim(O_, H_, L_, C_, i, ia[-1], tgt_r=3.0 if m == "ema5" else float(m), trail=em5 if m == "ema5" else None)
                            if tr:
                                e, risk, how, xp, j, f_ = tr
                                Rr = -1.0 if how == "SL" else (3.0 if m == "ema5" else float(m)) if how == "target" else (xp - e) / risk
                                res[m] = (Rr - COST * e / risk, (xp / e - 1 - COST) * 100, how)
                                busy = j
                    if res:
                        trades.append(dict(sym=sym, ex=ex, d=str(d), t=t, side=side, k=k, **{m: v for m, v in res.items()}))
    return trades


def report(T, lab):
    print(f"R| ===== {lab}: {len(T)} trades on {len({t['d'] for t in T})} days =====", flush=True)
    for m, nm in MODES:
        X = [t for t in T if m in t]
        if not X:
            continue
        R = [t[m][0] for t in X]; P = [t[m][1] for t in X]
        byd = defaultdict(float)
        for t in X:
            byd[t["d"]] += t[m][0]
        eq = pk = dd = 0.0
        for d in sorted(byd):
            eq += byd[d]; pk = max(pk, eq); dd = min(dd, eq - pk)
        yr = defaultdict(list)
        for t in X:
            yr[t["d"][:4]].append(t[m][0])
        print(f"R| {nm:34s} n {len(X):4d} | win {sum(r > 0 for r in R) / len(R) * 100:3.0f}% | avg {sum(R) / len(R):+.3f}R | total {sum(R):+7.1f}R | "
              f"avg {sum(P) / len(P):+6.2f}% of premium | up days {sum(v > 0 for v in byd.values())}/{len(byd)} | worst run {dd:.1f}R | "
              + " ".join(f"{y}: {sum(v):+.1f}R" for y, v in sorted(yr.items(), reverse=True)), flush=True)


if __name__ == "__main__":
    allT = []
    for root in sys.argv[1:]:
        T = run(root); allT += T
        for side in ("CE", "PE"):
            pass
        report(T, os.path.basename(os.path.normpath(root)))
        report([t for t in T if t["side"] == "CE"], os.path.basename(os.path.normpath(root)) + " CE only")
        report([t for t in T if t["side"] == "PE"], os.path.basename(os.path.normpath(root)) + " PE only")
