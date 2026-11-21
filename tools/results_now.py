"""Results-season ranking of NSE industries for the app (21 Nov 2026, Amritpal: "1" = show it in the app).

Tested 2016-26 (tools/research/results_season.py, project doc results-season-industry-test.md): once 70% of an industry has reported a
quarter, the share of its stocks with net profit up > 20% y/y and a cheap median P/E predicted the next 3 months vs Nifty (top fifth
minus bottom fifth +2.8% and +3.2%); the profile "half+ growing > 20%, growth accelerating in half+, cheapest 40% P/E" beat Nifty by
+4.4% over 3 months (+2.4% in 1 month), weak seasons (< 20% growing) -1.0%. Slow, context / ranking only - not an entry timer.

Inputs: data/fundq shards (quarterly results with announcement dates), data/scan/group_pulse.json 'nse' rows (members, latest close).
Per industry (3+ members with results): the latest quarter with >= 70% reported ('complete'), plus the quarter now being reported
('in progress', share reported so far). Output: data/scan/results_season.json."""
import glob
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

PROFILE_TXT = "Tested 2016-26: industries with half+ of stocks growing profit > 20%, growth speeding up in half+, and P/E in the cheapest 40% beat Nifty by +4.4% over the next 3 months on average (all industries +1.6%; weak seasons -1.0%). Context, not an entry signal."


def main():
    Q = {}
    for f in glob.glob("data/fundq/*.json"):
        Q.update(json.load(open(f)))
    G = json.load(open("data/scan/group_pulse.json"))
    rows = (G.get("nse") or {}).get("rows") or []
    today = pd.Timestamp(date.today())
    recs = []
    for s, v in Q.items():
        for x in v.get("q", []):
            if x.get("known") and x.get("end"):
                recs.append(dict(sym=s, end=pd.Timestamp(x["end"]), known=pd.Timestamp(x["known"]), eps=x.get("eps"), np_=x.get("np")))
    R = pd.DataFrame(recs).drop_duplicates(["sym", "end"]).sort_values(["sym", "end"])
    R = R[R.known <= today]
    R["key"] = R.end.dt.year * 10 + R.end.dt.quarter
    ly = R.assign(key=R.key + 10)[["sym", "key", "np_"]].rename(columns={"np_": "np_ly"})
    R = R.merge(ly, on=["sym", "key"], how="left")
    R["yoy"] = np.where((R.np_ly > 0) & R.np_.notna(), (R.np_ / R.np_ly - 1) * 100, np.nan)
    R["yoy_prev"] = R.groupby("sym").yoy.shift(1)
    R["ttm"] = R.groupby("sym").eps.transform(lambda s: s.rolling(4, min_periods=4).sum())
    close = {m["symbol"]: m.get("close") for r in rows for m in r["members"]}
    out = []
    for r in rows:
        mem = [m["symbol"] for m in r["members"]]
        x = R[R.sym.isin(mem)]
        have = x.sym.nunique()
        if have < 3:
            continue
        per_q = x.groupby("end").sym.nunique().sort_index()
        done = per_q[per_q >= np.ceil(0.7 * have)]
        if not len(done):
            continue
        qe = done.index[-1]; g = x[x.end == qe]
        y = g.yoy.dropna(); a = g.dropna(subset=["yoy", "yoy_prev"])
        last = x.sort_values("end").groupby("sym").tail(1)
        pe = [close[s] / e for s, e in zip(last.sym, last.ttm) if close.get(s) and pd.notna(e) and e > 0]
        nxt = per_q[per_q.index > qe]
        o = dict(basic=r["basic"], sector=r.get("sector"), slug=r.get("slug"), quarter=str(qe.date()), reported=int(len(g)), of=int(have),
                 done_on=str(g.known.sort_values().iloc[int(np.ceil(0.7 * have)) - 1].date()) if len(g) >= np.ceil(0.7 * have) else None,
                 strong=round(float((y > 20).mean()), 2) if len(y) else None, accel=round(float((a.yoy > a.yoy_prev).mean()), 2) if len(a) else None,
                 med=round(float(y.median()), 1) if len(y) else None, pe=round(float(np.median(pe)), 1) if len(pe) >= 2 else None,
                 next_q=str(nxt.index[-1].date()) if len(nxt) else None, next_reported=int(nxt.iloc[-1]) if len(nxt) else 0,
                 top=[dict(symbol=t.sym, yoy=round(float(t.yoy), 0)) for t in g.dropna(subset=["yoy"]).sort_values("yoy", ascending=False).head(5).itertuples()])
        out.append(o)
    # P/E rank among industries on the same quarter -> profile flag
    D = pd.DataFrame(out)
    if len(D):
        D["pe_rank"] = D.groupby("quarter").pe.rank(pct=True)
        for o, (_, r) in zip(out, D.iterrows()):
            o["pe_rank"] = None if pd.isna(r.pe_rank) else round(float(r.pe_rank), 2)
            o["profile"] = bool((o["strong"] or 0) >= 0.5 and (o["accel"] or 0) >= 0.5 and o["pe_rank"] is not None and o["pe_rank"] <= 0.4)
            o["weak"] = bool(o["strong"] is not None and o["strong"] < 0.2)
    out.sort(key=lambda o: (-(o.get("profile") or 0), -(o["strong"] or -1), o["pe"] or 999))
    # 22 Nov 2026 (Amritpal: "Yes" to an alert): PSU banks met the profile on 26 Oct, 10 days before their 5 Nov breakout, but
    # nothing pinged. Track when each industry entered the profile; alert (scheduled runs) on new entries only.
    try:
        prev = {r["basic"]: r for r in json.load(open("data/scan/results_season.json")).get("rows", [])}
    except Exception:  # noqa: BLE001
        prev = None
    today_s = str(date.today()); new = []
    for o in out:
        p_ = (prev or {}).get(o["basic"]) or {}
        if o.get("profile"):
            if p_.get("profile"):
                o["profile_since"] = p_.get("profile_since") or p_.get("done_on") or today_s
            else:
                o["profile_since"] = today_s
                if prev is not None:
                    new.append(o)
    js = dict(generated=today_s, note=PROFILE_TXT, rows=out,
              new_profile=[dict(basic=o["basic"], quarter=o["quarter"], since=o["profile_since"], strong=o["strong"], accel=o["accel"], pe=o["pe"]) for o in new])
    json.dump(js, open("data/scan/results_season.json", "w"), separators=(",", ":"))
    if new and os.environ.get("SEND_TELEGRAM") == "1":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify import send
        lines = [f"Results season: {len(new)} industr{'y' if len(new) == 1 else 'ies'} now strong + improving + cheap"]
        for o in new[:10]:
            lines.append(f"- {o['basic']}: {round((o['strong'] or 0) * 100)}% of stocks profit > 20% y/y, {round((o['accel'] or 0) * 100)}% speeding up, P/E {o['pe']}")
        lines.append("Tested 2016-26: such industries beat Nifty by +4.4% over 3 months on average (PSU banks met it 26 Oct 2026, 10 days before their breakout). Context, not an entry signal: wait for your system's buy.")
        send("\n".join(lines))
    print("results season:", len(out), "industries;", sum(o.get("profile", False) for o in out), "fit the profile;",
          [o["basic"] for o in out if o.get("profile")][:10], "| new:", [o["basic"] for o in new])


if __name__ == "__main__":
    main()
