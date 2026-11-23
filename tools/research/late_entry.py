"""Buying a Monthly ATH breakout LATE, or BELOW the trigger after it failed (23 Nov 2026, Amritpal's portfolio review: fresh-signal buys
did best; late buys and 'cheaper' buys below a failed breakout did worse -> "backtest and filter out rules").
Monthly ATH rules as live (claude/monthly-ath-system.md): trigger = high of the highest-closing COMPLETED month, that month >= 24 months
old; buy when price trades above it (trigger, or the open if it gaps above); at the last completed week close > 30-week SMA and the SMA
higher than 4 weeks earlier; >= Rs 2 cr/day, close > 20. Exit = weekly close below the 30-week SMA -> next open. 0.4% round trip.
Same events, entry variants: E0 at the breakout (the system); LATE k = buy at the close k sessions after the breakout (k = 5/10/20/40)
if the system has not exited yet, split by where the price is vs the trigger that day: > +10% above, 0..+10%, BELOW the trigger
(failed-breakout 'cheaper' buy, < 0%), and below -10%. Exit by the same rule. Per-trade return to exit; newest first by entry date,
bull/bear (Nifty vs 200-day), ex-Covid. NSE via Yahoo + bhavcopy patch, survivors. PILOT = 150 stocks. Output data/research/late_entry.json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import flag_volume as FV  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def events(sym, x):
    x = x[x.index >= "2012-01-01"]
    if len(x) < 600:
        return []
    m = x.resample("ME").agg({"OPEN": "first", "HIGH": "max", "LOW": "min", "CLOSE": "last", "VOL": "sum"}).dropna()
    w = x.CLOSE.resample("W-FRI").last().dropna(); s30 = w.rolling(30).mean()
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); D = x.index
    tv = (x.CLOSE * x.VOL).rolling(20).mean().to_numpy()
    out, busy = [], None
    for mi in range(26, len(m)):
        prev = m.iloc[:mi]; k = int(np.argmax(prev.CLOSE.to_numpy()))
        if mi - k < 24:                                  # ATH month must be >= 24 months old
            continue
        trig = float(prev.HIGH.iloc[k]); mend = m.index[mi]; mstart = (mend - pd.offsets.MonthBegin(1)).normalize()
        idx = np.where((D >= mstart) & (D <= mend))[0]
        for j in idx:
            if busy is not None and j <= busy:
                break
            if h[j] < trig:
                continue
            wk = w[w.index < D[j]]
            if len(wk) < 35 or not np.isfinite(s30.loc[wk.index[-1]]):
                break
            lw = wk.index[-1]; sm = s30.loc[lw]; sm4 = s30.loc[wk.index[-5]]
            if not (wk.iloc[-1] > sm and sm > sm4) or not (tv[j] >= 2e7) or c[j - 1] <= 20:
                break
            e0 = max(trig, o[j]); ex_j = None                # exit: weekly close below the 30-week SMA -> next open
            for wd in w.index[w.index >= D[j]]:
                if np.isfinite(s30.loc[wd]) and w.loc[wd] < s30.loc[wd]:
                    nx = np.where(D > wd)[0]
                    ex_j = nx[0] if len(nx) else None; break
            if ex_j is None:
                ex_j = len(D) - 1; openpos = True
            else:
                openpos = False
            out.append(dict(sym=sym, d=D[j], j=j, trig=trig, e0=e0, ex=ex_j, xp=o[ex_j] if not openpos else c[ex_j], open=openpos, c=c, D=D))
            busy = ex_j; break
    return out


def main():
    P = FV.load()
    n = yf.download("^NSEI", start="2012-01-01", progress=False, auto_adjust=True)["Close"]; n = (n.iloc[:, 0] if isinstance(n, pd.DataFrame) else n).dropna()
    n.index = pd.to_datetime(n.index).tz_localize(None); bull = (n > n.rolling(200).mean())
    rows = []
    for sym, x in P.items():
        try:
            for e in events(sym, x):
                c, D, j, ex = e["c"], e["D"], e["j"], e["ex"]
                base = dict(sym=sym, d=e["d"], bull=bool(bull.asof(e["d"])) if len(bull) else None)
                rows.append(dict(base, var="E0 breakout", entry_d=e["d"], ret=e["xp"] / e["e0"] - 1 - 0.004, vs=0.0, days=(D[ex] - D[j]).days))
                for k in (5, 10, 20, 40):
                    jj = j + k
                    if jj >= ex or jj >= len(c):
                        continue
                    vs = c[jj] / e["trig"] - 1
                    rows.append(dict(base, var=f"late {k}", entry_d=D[jj], ret=e["xp"] / c[jj] - 1 - 0.004, vs=vs, days=(D[ex] - D[jj]).days))
        except Exception as ex_:  # noqa: BLE001
            print("skip", sym, str(ex_)[:80])
    R = pd.DataFrame(rows); R = R[R.d >= "2016-01-01"]
    end = R.entry_d.max()
    def band(v):
        return "above +10%" if v > 0.10 else "0..+10%" if v >= 0 else "below trigger (0..-10%)" if v >= -0.10 else "below -10%"
    R["band"] = [("breakout" if a == "E0 breakout" else band(v)) for a, v in zip(R["var"], R.vs)]
    res = {"method": __doc__}

    def st(s):
        return dict(n=int(len(s)), avg=round(s.ret.mean() * 100, 1), med=round(s.ret.median() * 100, 1), win=round((s.ret > 0).mean() * 100),
                    pf=round(s.ret[s.ret > 0].sum() / -s.ret[s.ret < 0].sum(), 2) if (s.ret < 0).any() else None, days=int(s.days.median())) if len(s) else None
    groups = [("E0 breakout", R["var"] == "E0 breakout")]
    for k in (5, 10, 20, 40):
        for b in ("above +10%", "0..+10%", "below trigger (0..-10%)", "below -10%"):
            groups.append((f"late {k} | {b}", (R["var"] == f"late {k}") & (R.band == b)))
        groups.append((f"late {k} | all", R["var"] == f"late {k}"))
    for lab, mask in groups:
        S = R[mask]; o = dict(all=st(S))
        for y in (1, 2, 3, 5):
            o[f"{y}y"] = st(S[S.entry_d > end - pd.DateOffset(years=y)])
        o["bull"] = st(S[S.bull == True]); o["bear"] = st(S[S.bull == False])  # noqa: E712
        o["exCovid"] = st(S[~((S.entry_d >= "2020-02-15") & (S.entry_d < "2021-01-01"))])
        res[lab] = o
        a = o["all"]
        if a:
            print(f"R| {lab:34s} | all n{a['n']} avg {a['avg']:+.1f}% med {a['med']:+.1f}% win {a['win']}% pf {a['pf']} hold {a['days']}d | "
                  + " ".join(f"{k} {o[k]['avg']:+.1f}%({o[k]['n']})" if o[k] else f"{k} -" for k in ("1y", "2y", "3y", "5y", "bull", "bear", "exCovid")), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/late_entry" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
