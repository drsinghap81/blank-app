"""Where is money going TODAY (intraday snapshot, 23 Nov 2026, Amritpal: "what's happening, are hands churning, which sectors /
industries are seeing buying"). Yahoo 15-minute bars for today + 30 daily bars, liquid NSE stocks grouped by NSE sector and basic
industry (group_pulse.json). Per group (3+ liquid members): today's move (equal weight, last bar vs Friday close), breadth (% up),
relative volume = today's volume so far / (20-day average daily volume x share of the session elapsed), and last week's move
(to see rotation: last week's leaders vs today's). Read-only snapshot."""
import json

import numpy as np
import pandas as pd

from cluster_open15 import dl


def main():
    G = json.load(open("data/scan/group_pulse.json")); SEC, IND = {}, {}
    for r in G["nse"]["rows"]:
        liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
        SEC.setdefault(r.get("sector") or r.get("macro"), []).extend(liq)
        if len(liq) >= 3:
            IND[r["basic"]] = liq
    syms = sorted({s for v in SEC.values() for s in v})
    I = dl([s + ".NS" for s in syms], period="2d", interval="15m"); D = dl([s + ".NS" for s in syms], period="45d", interval="1d")
    for x in I.values():
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None) if x.index.tz is not None else x.index
    day = max(x.index[-1].date() for x in I.values()); st = {}
    for s in syms:
        x, d = I.get(s), D.get(s)
        if x is None or d is None:
            continue
        t = x[x.index.date == day]; d = d.copy(); d.index = pd.to_datetime(d.index).tz_localize(None)
        prev = d[d.index.date < day]
        if len(t) < 2 or len(prev) < 25:
            continue
        el = min(1.0, len(t) / 25.0); av = prev.Volume.iloc[-20:].mean()
        st[s] = dict(mv=t.Close.iloc[-1] / prev.Close.iloc[-1] - 1, rv=t.Volume.sum() / (av * el) if av else np.nan,
                     wk=prev.Close.iloc[-1] / prev.Close.iloc[-6] - 1, tv=t.Volume.sum() * t.Close.iloc[-1], last=str(t.index[-1])[11:16])
    last = max(v["last"] for v in st.values())
    mk = np.mean([v["mv"] for v in st.values()]) * 100; up = np.mean([v["mv"] > 0 for v in st.values()]) * 100
    print(f"R| snapshot {day} {last} IST | {len(st)} stocks | market avg {mk:+.2f}% | {up:.0f}% of stocks up", flush=True)
    for lab, GR, mn in (("SECTOR", SEC, 5), ("INDUSTRY", IND, 3)):
        rows = []
        for g, mem in GR.items():
            v = [st[s] for s in mem if s in st]
            if len(v) < mn:
                continue
            top = sorted([s for s in mem if s in st], key=lambda s: -st[s]["mv"] * (st[s]["rv"] if np.isfinite(st[s]["rv"]) else 1))[:3]
            rows.append(dict(g=g, n=len(v), mv=np.mean([a["mv"] for a in v]) * 100, br=np.mean([a["mv"] > 0 for a in v]) * 100,
                             rv=np.nanmedian([a["rv"] for a in v]), wk=np.mean([a["wk"] for a in v]) * 100,
                             top=[f"{s} {st[s]['mv'] * 100:+.1f}% x{st[s]['rv']:.1f}" for s in top]))
        R = pd.DataFrame(rows).sort_values("mv", ascending=False)
        R["wk_rank"] = R.wk.rank(ascending=False).astype(int); R["today_rank"] = range(1, len(R) + 1)
        for _, r in pd.concat([R.head(12 if lab == "INDUSTRY" else 8), R.tail(6 if lab == "INDUSTRY" else 5)]).iterrows():
            print(f"R| {lab} | {r.g} | n{r.n} | today {r.mv:+.2f}% | up {r.br:.0f}% | relvol x{r.rv:.2f} | last wk {r.wk:+.1f}% (rank {r.wk_rank}/{len(R)}) | {', '.join(r.top)}", flush=True)
        hv = R[(R.rv >= 1.3) & (R.mv > 0)].sort_values("rv", ascending=False).head(8)
        for _, r in hv.iterrows():
            print(f"R| {lab} HEAVY BUYING | {r.g} | today {r.mv:+.2f}% relvol x{r.rv:.2f} up {r.br:.0f}% | last wk rank {r.wk_rank}", flush=True)
        hs = R[(R.rv >= 1.3) & (R.mv < 0)].sort_values("rv", ascending=False).head(6)
        for _, r in hs.iterrows():
            print(f"R| {lab} HEAVY SELLING | {r.g} | today {r.mv:+.2f}% relvol x{r.rv:.2f} up {r.br:.0f}% | last wk rank {r.wk_rank}", flush=True)
        print(f"R| {lab} rotation: corr(last week rank, today rank) = {R.wk_rank.corr(R.today_rank, method='spearman'):+.2f}", flush=True)


if __name__ == "__main__":
    main()
