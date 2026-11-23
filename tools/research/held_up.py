"""Stocks / industries that HOLD UP on a falling day - do they lead the bounce? (23 Nov 2026, Amritpal: "a map of such a falling day,
what outperformed; if the market bounces these can come up fast").
NSE stocks (Yahoo + bhavcopy patch, survivors, liquid), 2016 -> today. Down day = Nifty 50 close-to-close <= -1% (also <= -1.5%).
On each down day rank stocks by their move minus Nifty's: TOP 10% (held up best), BOTTOM 10% (fell most), all. Moves > +-15% dropped
(news / circuits). Forward from that close: next 5 / 10 / 20 sessions, stock minus the average stock (relative), and the same only when
the market BOUNCED (Nifty up over those sessions). Industries (NSE basic, 3+ liquid stocks, equal weight): top 3 vs bottom 3 that day.
Newest first (last 1/2/3/5 years by down-day date), bull/bear (Nifty above/below its 200-day average), ex-Covid (Feb-Dec 2020 out).
PILOT env = 150 stocks. Output data/research/held_up(_pilot).json"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import flag_volume as FV  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def main():
    P = FV.load()
    C = pd.DataFrame({k: v.CLOSE for k, v in P.items()}).sort_index(); C = C[C.index >= "2016-01-01"]
    n = yf.download("^NSEI", start="2015-01-01", progress=False, auto_adjust=True)["Close"]; n = (n.iloc[:, 0] if isinstance(n, pd.DataFrame) else n).dropna()
    n.index = pd.to_datetime(n.index).tz_localize(None); n200 = n.rolling(200).mean(); n = n.reindex(C.index).ffill(); n200 = n200.reindex(C.index).ffill()
    R = C.pct_change(); nr = n.pct_change(); ex = R.sub(nr, axis=0); ex[R.abs() > 0.15] = np.nan
    avg = R.where(R.abs() <= 0.15).mean(axis=1)
    G = json.load(open("data/scan/group_pulse.json")); IND = {}
    for r in G["nse"]["rows"]:
        m = [x["symbol"] for x in r["members"] if x["symbol"] in C.columns]
        if len(m) >= 3:
            IND[r["basic"]] = m
    end = C.index[-1]; out = {"method": __doc__}
    for thr in (-0.01, -0.015):
        days = [d for d in C.index[1:-1] if nr.get(d, 0) <= thr]
        rows = []
        for d in days:
            i = C.index.get_loc(d); e = ex.loc[d].dropna()
            if len(e) < 30:
                continue
            top, bot = e[e >= e.quantile(0.9)].index, e[e <= e.quantile(0.1)].index
            ie = {k: e.reindex(v).mean() for k, v in IND.items() if e.reindex(v).notna().sum() >= 3}
            it = sorted(ie, key=ie.get); itop = [s for k in it[-3:] for s in IND[k]]; ibot = [s for k in it[:3] for s in IND[k]]
            rec = dict(d=d, bull=bool(n.at[d] > n200.at[d]) if np.isfinite(n200.at[d]) else None)
            for h in (5, 10, 20):
                if i + h >= len(C):
                    continue
                f = C.iloc[i + h] / C.iloc[i] - 1; m = np.prod(1 + avg.iloc[i + 1:i + h + 1]) - 1; nb = n.iloc[i + h] / n.iloc[i] - 1
                rec[f"top{h}"] = f.reindex(top).mean() - m; rec[f"bot{h}"] = f.reindex(bot).mean() - m
                rec[f"itop{h}"] = f.reindex(itop).mean() - m; rec[f"ibot{h}"] = f.reindex(ibot).mean() - m
                rec[f"topabs{h}"] = f.reindex(top).mean(); rec[f"allabs{h}"] = m; rec[f"bounce{h}"] = bool(nb > 0)
            rows.append(rec)
        D = pd.DataFrame(rows); lab = f"Nifty <= {thr * 100:.1f}%"
        print(f"R| {lab} | down days {len(D)}", flush=True)

        def show(name, S):
            o = {}
            for h in (5, 10, 20):
                s = S.dropna(subset=[f"top{h}"])
                if not len(s):
                    continue
                b = s[s[f"bounce{h}"]]
                o[h] = dict(n=len(s), top=round(s[f"top{h}"].mean() * 100, 2), top_win=round((s[f"top{h}"] > 0).mean() * 100), bottom=round(s[f"bot{h}"].mean() * 100, 2),
                            ind_top=round(s[f"itop{h}"].mean() * 100, 2), ind_bottom=round(s[f"ibot{h}"].mean() * 100, 2),
                            bounce_n=len(b), bounce_top=round(b[f"top{h}"].mean() * 100, 2) if len(b) else None, bounce_bottom=round(b[f"bot{h}"].mean() * 100, 2) if len(b) else None,
                            bounce_top_abs=round(b[f"topabs{h}"].mean() * 100, 2) if len(b) else None, bounce_all_abs=round(b[f"allabs{h}"].mean() * 100, 2) if len(b) else None)
                print(f"R| {lab} | {name} | next {h}d | {o[h]}", flush=True)
            out[f"{lab} | {name}"] = o
        for y in (1, 2, 3, 5):
            show(f"last {y}y", D[D.d > end - pd.DateOffset(years=y)])
        show("all 2016-26", D); show("bull (Nifty > 200d)", D[D.bull == True]); show("bear", D[D.bull == False])  # noqa: E712
        show("ex-Covid", D[~((D.d >= "2020-02-15") & (D.d < "2021-01-01"))])
        for yy in sorted(D.d.dt.year.unique(), reverse=True):
            s = D[D.d.dt.year == yy].dropna(subset=["top10"])
            if len(s):
                print(f"R| {lab} | year {yy} | n {len(s)} | next 10d top {s.top10.mean() * 100:+.2f} bottom {s.bot10.mean() * 100:+.2f} ind top {s.itop10.mean() * 100:+.2f}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/held_up" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
