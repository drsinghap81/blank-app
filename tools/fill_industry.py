"""Fill gaps in data/universe/nse_industry.csv (12 Nov 2026): every stock in the NSE index lists we use (Total Market, Nifty 500,
Microcap 250, theme indices) must have an industry. Tries NSE's quote API (official macro/sector/industry/basicIndustry), then
Yahoo, slowly; anything still missing gets NSE's official index 'Industry' (sector level) as its group, marked src=nse-index.
Prints what it could not fill."""
import csv, glob, os, sys, time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_industry import nse, warm, yahoo  # noqa: E402

P = "data/universe/nse_industry.csv"
d = pd.read_csv(P)
have = set(d.symbol)
lists = ["data/universe/niftytotalmarket.csv", "data/universe/nifty500.csv", "data/universe/niftymicrocap250.csv",
         "data/universe/niftysmallcap250.csv", "data/universe/niftymidcap150.csv"] + glob.glob("data/universe/themes/*.csv")
want, idx_ind = {}, {}
for f in lists:
    try:
        t = pd.read_csv(f); t.columns = [c.strip() for c in t.columns]
    except Exception:  # noqa: BLE001
        continue
    if "Symbol" not in t or "sme" in f.lower():
        continue
    for _, r in t.iterrows():
        s = str(r["Symbol"]).strip()
        if s.startswith("DUMMY") or s == "nan":
            continue
        want[s] = 1
        if "Industry" in t and pd.notna(r.get("Industry")):
            idx_ind.setdefault(s, str(r["Industry"]).strip())
miss = sorted(s for s in want if s not in have)
print("index stocks", len(want), "missing industry", len(miss), flush=True)
warm(); new = []
for k, s in enumerate(miss):
    row, src = nse(s), "nse"
    if not row:
        time.sleep(1.5); row, src = yahoo(s), "yahoo"
    if not row and s in idx_ind:
        row, src = ["", idx_ind[s], idx_ind[s], idx_ind[s]], "nse-index"
    if row:
        new.append([s] + row + [src])
    else:
        print("could not classify", s, flush=True)
    time.sleep(1.0)
if new:
    with open(P, "a", newline="") as f:
        csv.writer(f).writerows(new)
print("filled", len(new), "of", len(miss), {k: sum(1 for r in new if r[-1] == k) for k in ("nse", "yahoo", "nse-index")})
