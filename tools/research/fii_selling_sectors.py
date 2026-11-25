"""Which sectors / sizes did best while FIIs were selling, last 2 years (25 Nov 2026, Amritpal: "check when FII were selling of late
from last 2 years, which sector outperformed - mid, small or large").
FII: NSDL daily FPI equity net (data/research/fii_daily.csv). Indices: NSE official closes (data/scan/index_ohlcv.csv.gz).
Selling phase = 20-day FII net in the bottom 20% of the past 250 sessions (same 'heavy selling' as fii_test), runs merged when < 10
sessions apart, phases of 10+ sessions. Per phase: each index's return from the phase start close to its end close, and vs Nifty 50.
Then the next 20 sessions after each phase ends (does the leader of the selling phase also lead the recovery?)."""
import pandas as pd

F = pd.read_csv("data/research/fii_daily.csv", index_col=0, parse_dates=True).iloc[:, 0]
d = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
C = d.pivot_table(index="Date", columns="INDEX", values="Close").sort_index().ffill()
KEEP = ["NIFTY 50", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY BANK", "NIFTY PRIVATE BANK", "NIFTY PSU BANK", "NIFTY FINANCIAL SERVICES",
        "NIFTY CAPITAL MARKETS", "NIFTY IT", "NIFTY PHARMA", "NIFTY HEALTHCARE INDEX", "NIFTY FMCG", "NIFTY AUTO", "NIFTY METAL", "NIFTY ENERGY",
        "NIFTY OIL & GAS", "NIFTY REALTY", "NIFTY MEDIA", "NIFTY INFRASTRUCTURE", "NIFTY CONSUMER DURABLES", "NIFTY INDIA DEFENCE", "NIFTY CPSE", "NIFTY MNC"]
C = C[[k for k in KEEP if k in C.columns]]
f = F.reindex(C.index.union(F.index)).fillna(0).groupby(level=0).sum().reindex(C.index).fillna(0)
s20 = f.rolling(20).sum(); heavy = s20 <= s20.rolling(250, min_periods=120).quantile(0.2)
h = heavy[heavy.index >= "2024-11-01"]
ph = []; start = None; last = None
for dt, v in h.items():
    if v:
        if start is None:
            start = dt
        elif (C.index.get_loc(dt) - C.index.get_loc(last)) > 10:
            ph.append((start, last)); start = dt
        last = dt
if start is not None:
    ph.append((start, last))
ph = [(a, b) for a, b in ph if C.index.get_loc(b) - C.index.get_loc(a) >= 9]
nm = lambda k: k.replace("NIFTY ", "").title().replace("Psu", "PSU").replace("Cpse", "CPSE").replace("Mnc", "MNC").replace("It", "IT") if k != "NIFTY 50" else "Nifty 50"  # noqa: E731
allv, allnext = {}, {}
for a, b in ph:
    i0 = C.index.get_loc(a) - 1; i1 = C.index.get_loc(b)
    r = (C.iloc[i1] / C.iloc[i0] - 1) * 100; vs = r - r["NIFTY 50"]
    fl = f.iloc[i0 + 1:i1 + 1].sum()
    i2 = min(i1 + 20, len(C) - 1); rn = (C.iloc[i2] / C.iloc[i1] - 1) * 100; vsn = rn - rn["NIFTY 50"]
    for k in C.columns:
        allv.setdefault(k, []).append(vs[k]); allnext.setdefault(k, []).append(vsn[k])
    o = vs.drop("NIFTY 50").sort_values(ascending=False)
    print(f"R| PHASE {a.date()} -> {b.date()} ({i1 - i0} sessions) FII net Rs {fl / 1000:,.0f}k cr | Nifty {r['NIFTY 50']:+.1f}% | "
          f"Midcap 150 {vs['NIFTY MIDCAP 150']:+.1f} / Smallcap 250 {vs['NIFTY SMALLCAP 250']:+.1f} pts vs Nifty", flush=True)
    print("R|   best vs Nifty: " + ", ".join(f"{nm(k)} {v:+.1f}" for k, v in o.head(5).items()) + " | worst: " + ", ".join(f"{nm(k)} {v:+.1f}" for k, v in o.tail(4).items()), flush=True)
    print(f"R|   next 20 sessions (to {C.index[i2].date()}): Nifty {rn['NIFTY 50']:+.1f}% | Midcap {vsn['NIFTY MIDCAP 150']:+.1f} Smallcap {vsn['NIFTY SMALLCAP 250']:+.1f} pts | "
          "best " + ", ".join(f"{nm(k)} {v:+.1f}" for k, v in vsn.drop('NIFTY 50').sort_values(ascending=False).head(4).items()), flush=True)
print("R| ===== average over all selling phases (pts vs Nifty), and how often it beat Nifty =====", flush=True)
A = pd.DataFrame({k: dict(during=sum(v) / len(v), beat=sum(x > 0 for x in v), after=sum(allnext[k]) / len(v), beat_after=sum(x > 0 for x in allnext[k]))
                  for k, v in allv.items() if k != "NIFTY 50"}).T.sort_values("during", ascending=False)
for k, r in A.iterrows():
    print(f"R| {nm(k):22s} during {r.during:+6.1f} pts (beat {int(r.beat)}/{len(ph)}) | next 20 sessions {r.after:+6.1f} pts (beat {int(r.beat_after)}/{len(ph)})", flush=True)
