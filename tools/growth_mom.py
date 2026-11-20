"""Growth + momentum list for NSE (15 Nov 2026), from the fundamental-scan test (project doc fundamental-scan-test.md).
At each month-end: liquid NSE stocks (60-day average turnover > Rs 5 cr) whose trailing-4-quarter net profit is up >= 20%
on the 4 quarters before, with profit up year-on-year in at least 3 of the last 4 quarters; ranked by the 12-month price
return that skips the latest month; top 25, equal weight. Only results announced before the month-end count.
Results: data/fundq/shard_*.json (tools/fetch_nse_results.py, FUNDQ_UPDATE mode adds new quarters).
Prices: Yahoo. Output: data/scan/growth_mom.json."""
import csv, glob, json, os
from datetime import date, timedelta
import numpy as np, pandas as pd, yfinance as yf
import nse_bhav; nse_bhav.install()  # noqa: E402,E702  20 Nov 2026 (Amritpal: always use bhavcopy): recent NSE sessions from NSE's bhavcopy

OUT = "data/scan/growth_mom.json"; N, RES = 25, 15
BT = dict(period="Jan 2017 - Oct 2026", cagr=24.7, dd=-35.9, filt_cagr=23.4, filt_dd=-29.2, mom_cagr=22.1, mom_dd=-43.5,
          nifty_cagr=11.5, nifty_dd=-28.8, eq_cagr=11.8, n_stocks=1752)

R = {}
for f in sorted(glob.glob("data/fundq/shard_*.json")):
    R.update(json.load(open(f)))
today = date.today(); D = pd.Timestamp(today.replace(day=1) - timedelta(days=1))   # latest completed month-end


def feats(q):
    df = pd.DataFrame([x for x in q if x.get("end") and x.get("known") and x.get("np") is not None])
    if len(df) < 8:
        return None
    df = df.sort_values("end").drop_duplicates("end", keep="first").reset_index(drop=True)
    k = df[pd.to_datetime(df.known) < D]
    if len(k) < 8:
        return None
    a, b = k.iloc[-4:], k.iloc[-8:-4]; ea, eb = pd.to_datetime(a.end), pd.to_datetime(b.end)
    if (ea.iloc[-1] - ea.iloc[0]).days > 300 or (D - ea.iloc[-1]).days > 200 or (ea.iloc[-1] - eb.iloc[0]).days > 700 \
            or pd.concat([a, b]).cons.nunique() > 1:
        return None
    ttm, prev = a.np.sum(), b.np.sum()
    if prev <= 0:
        return None
    up = int(sum(1 for x, y in zip(a.np.values, b.np.values) if y > 0 and x > y))
    ss, sp = a.sales.sum(), b.sales.sum()
    sh = [r.np / r.eps for r in a.iloc[-2:].itertuples() if r.eps and r.eps > 0 and r.np > 0]   # implied shares (lakh)
    return dict(g=ttm / prev - 1, up4=up, sg=(ss / sp - 1) if sp and sp > 0 else None, ttm=ttm, sh=float(np.mean(sh)) if sh else None,
                last_q=a.end.iloc[-1], q0=(a.np.iloc[-1] / b.np.iloc[-1] - 1) if b.np.iloc[-1] > 0 else None, n_q=int(len(k)))


F = {s: f for s, v in R.items() if v.get("q") for f in [feats(v["q"])] if f}
cand = {s: f for s, f in F.items() if f["g"] >= 0.20 and f["up4"] >= 3}
print(f"results for {len(R)} symbols, usable at {D:%Y-%m-%d}: {len(F)}, growth filter: {len(cand)}")

tick = [f"{s}.NS" for s in cand] + ["NIFTYBEES.NS"]
px = yf.download(tick, start=(D - timedelta(days=420)).strftime("%Y-%m-%d"), auto_adjust=False, progress=False, threads=True,
                 group_by="column")
AC, CL, VO = px["Adj Close"], px["Close"], px["Volume"]
AC.columns = [c[:-3] for c in AC.columns]; CL.columns = [c[:-3] for c in CL.columns]; VO.columns = [c[:-3] for c in VO.columns]
upto = AC.index[AC.index <= D]; di = upto[-1]
CM = AC.loc[:D].ffill(limit=25).resample("ME").last()
m12 = (CM.shift(1) / CM.shift(12) - 1).iloc[-1]
val60 = (CL * VO).loc[:di].iloc[-60:].mean()
nb = AC["NIFTYBEES"].dropna(); nb_d = nb.loc[:di]
mkt = dict(above=bool(nb_d.iloc[-1] > nb_d.iloc[-200:].mean()), close=round(float(nb_d.iloc[-1]), 2),
           dma200=round(float(nb_d.iloc[-200:].mean()), 2), now_above=bool(nb.iloc[-1] > nb.iloc[-200:].mean()))

names = {}
for fn in glob.glob("data/universe/nifty*.csv"):
    for r in csv.DictReader(open(fn, encoding="utf-8-sig")):
        if r.get("Symbol"):
            names.setdefault(r["Symbol"], (r.get("Company Name", "").replace(" Ltd.", "").replace(" Limited", ""), r.get("Industry", "")))
try:      # NSE's list of all listed equities, for names missing from the index files
    import io, requests
    r = requests.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"})
    for x in csv.DictReader(io.StringIO(r.text)):
        x = {k.strip(): v for k, v in x.items()}
        if x.get("SYMBOL") and x["SYMBOL"] not in names:
            names[x["SYMBOL"]] = (x.get("NAME OF COMPANY", "").title().replace(" Limited", "").replace(" Ltd", ""), "")
except Exception:  # noqa: BLE001
    pass
ind = {}
try:
    for r in csv.DictReader(open("data/universe/nse_industry.csv")):
        ind[r["symbol"]] = r.get("industry") or r.get("sector") or ""
except Exception:  # noqa: BLE001
    pass

rows = []
for s, f in cand.items():
    if s not in AC or pd.isna(m12.get(s)) or not (val60.get(s, 0) > 5e7):
        continue
    c_me = float(AC.loc[:di, s].dropna().iloc[-1]); c_now = AC[s].dropna(); c_raw = float(CL[s].dropna().iloc[-1])
    pe = (float(CL.loc[:di, s].dropna().iloc[-1]) * f["sh"] / f["ttm"]) if f["sh"] else None
    rows.append(dict(symbol=s, name=names.get(s, ("", ""))[0], industry=ind.get(s) or names.get(s, ("", ""))[1],
                     m12=round(float(m12[s]) * 100, 1), g=round(f["g"] * 100, 1), sg=None if f["sg"] is None else round(f["sg"] * 100, 1),
                     q0=None if f["q0"] is None else round(f["q0"] * 100, 1), up4=f["up4"], last_q=f["last_q"],
                     pe=None if pe is None or pe <= 0 or pe > 1000 else round(pe, 1), val_cr=round(float(val60[s]) / 1e7, 1),
                     close=round(c_raw, 2), since=round((float(c_now.iloc[-1]) / c_me - 1) * 100, 1)))
rows.sort(key=lambda r: -r["m12"])
picks, reserve = rows[:N], rows[N:N + RES]

old = {}
if os.path.exists(OUT):
    try:
        old = json.load(open(OUT))
    except Exception:  # noqa: BLE001
        old = {}
if old.get("asof") == f"{D:%Y-%m-%d}":
    prev, prev_asof = old.get("prev", []), old.get("prev_asof")
else:
    prev, prev_asof = [r["symbol"] for r in old.get("picks", [])], old.get("asof")
cur = [r["symbol"] for r in picks]
out = dict(asof=f"{D:%Y-%m-%d}", price_day=f"{di:%Y-%m-%d}", updated=f"{today}", n_results=len(F), n_growth=len(cand),
           n_qualified=len(rows), market=mkt, picks=picks, reserve=reserve, prev=prev, prev_asof=prev_asof,
           added=[s for s in cur if prev and s not in prev], dropped=[s for s in prev if s not in cur], backtest=BT)
json.dump(out, open(OUT, "w"), separators=(",", ":"))
print(f"{len(rows)} qualified; top: {', '.join(cur[:10])}; market above 200-DMA: {mkt['above']}")
