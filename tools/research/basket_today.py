"""What would today's Pulse basket look like? (20 Nov 2026, Amritpal) NSE official industries, liquid members.
Open = 09:15 (the pre-open auction price); first 15 minutes = 09:15-09:30. At 09:30: breadth = share of the industry's stocks above
yesterday's close. BUY up to 2 strong-Pulse industries (top 25%, previous-session rank) with breadth >= 60%; SELL up to 2 weak-Pulse
(bottom 25%) with breadth <= 40%. Entry 09:30 close, stop = first-15-minute low (buy) / high (sell), each stock equal risk, whole
basket risks 1% of Rs 20 lakh = Rs 20,000. Status at the latest 5-minute bar. Also the plain 'strongest / weakest move' basket."""
import json
import numpy as np
import pandas as pd
import yfinance as yf
G = json.load(open("data/scan/group_pulse.json")); PH = json.load(open("data/research/nse_pulse_daily.json"))
IND = {r["basic"]: [m["symbol"] for m in r["members"] if m.get("liquid")] for r in G["nse"]["rows"]}
IND = {k: v for k, v in IND.items() if len(v) >= 3}
syms = sorted({s for v in IND.values() for s in v})
d = yf.download([s + ".NS" for s in syms], period="5d", interval="5m", progress=False, group_by="column", auto_adjust=False, threads=True)
O, H, L, C = (d[k].rename(columns=lambda c: c[:-3]) for k in ("Open", "High", "Low", "Close"))
idx = C.index.tz_convert("Asia/Kolkata"); O.index = H.index = L.index = C.index = idx
today = idx[-1].date(); prev = sorted({t.date() for t in idx if t.date() < today})[-1]
pc = C[[t.date() == prev for t in idx]].ffill().iloc[-1]
T = [t for t in idx if t.date() == today]; f15 = [t for t in T if t.strftime("%H:%M") < "09:30"]; last = T[-1]
pk = sorted(x for x in PH if x < str(today))[-1]; P = PH[pk]
print("R| today", today, "latest bar", last.strftime("%H:%M"), "| Pulse as of", pk, "| first-15 bars", len(f15), flush=True)
rows = []
for k, ss in IND.items():
    ss = [s for s in ss if s in C.columns and pd.notna(pc.get(s))]
    if len(ss) < 3:
        continue
    o = (O.loc[T[0], ss] / pc[ss] - 1).mean() * 100; c15 = C.loc[f15[-1], ss]
    br = float((c15 > pc[ss]).mean()); mv = float((c15 / pc[ss] - 1).mean() * 100)
    pr = np.nanmean([P.get(s, np.nan) for s in ss])
    rows.append(dict(ind=k, ss=ss, open=o, br=br, mv=mv, pulse=pr))
R = pd.DataFrame(rows)


def run(name, buys, sells):
    out = []; tot = []
    for side, L_ in ((1, buys), (-1, sells)):
        for k in L_:
            ss = R.set_index("ind").at[k, "ss"]
            rr = []
            for s in ss:
                e = C.loc[f15[-1], s]; st = (L.loc[f15, s].min() if side > 0 else H.loc[f15, s].max())
                risk = (e - st) * side
                if not (risk > 0.002 * e):
                    continue
                after = [t for t in T if t > f15[-1]]
                hit = [t for t in after if (side > 0 and L.at[t, s] <= st) or (side < 0 and H.at[t, s] >= st)]
                px = st if hit else C.at[last, s]
                r_ = ((px - e) * side - 0.001 * e) / risk; rr.append(r_); tot.append(r_)
            out.append(f"{'BUY ' if side > 0 else 'SELL'} {k} ({len(rr)} stocks, Pulse {R.set_index('ind').at[k, 'pulse']:.2f}, 09:30 breadth "
                       f"{R.set_index('ind').at[k, 'br'] * 100:.0f}%): avg {np.mean(rr) if rr else 0:+.2f} R, stopped {sum(1 for x in rr if x <= -0.99)}")
    print(f"R| {name}: basket avg {np.mean(tot) if tot else 0:+.2f} R = Rs {np.mean(tot) * 20000 if tot else 0:+,.0f} at 1% risk (status {last.strftime('%H:%M')})")
    for x in out:
        print("R|    ", x)


st = R[(R.pulse >= 0.75) & (R.br >= 0.6)].sort_values(["br", "mv"], ascending=False).ind.tolist()[:2]
wk = R[(R.pulse <= 0.25) & (R.br <= 0.4)].sort_values(["br", "mv"]).ind.tolist()[:2]
run("PULSE basket (strong + green buy, weak + red sell)", st, wk)
run("MOVE basket (2 strongest / 2 weakest first-15 move, no Pulse)", R.sort_values("mv", ascending=False).ind.tolist()[:2], R.sort_values("mv").ind.tolist()[:2])
bo = R[(R.pulse >= 0.75) & (R.open < 0) & (R.br >= 0.6)].sort_values("br", ascending=False).ind.tolist()[:2]
fa = R[(R.pulse <= 0.25) & (R.open > 0) & (R.br <= 0.4)].sort_values("br").ind.tolist()[:2]
run("BOUNCE basket (strong opened red now green / weak opened green now red)", bo, fa)
top = R.sort_values("mv", ascending=False)
print("R| first-15 leaders:", [(r.ind, round(r.mv, 2), f"{r.br * 100:.0f}%", round(r.pulse, 2)) for r in top.head(5).itertuples()])
print("R| first-15 laggards:", [(r.ind, round(r.mv, 2), f"{r.br * 100:.0f}%", round(r.pulse, 2)) for r in top.tail(5).itertuples()])
