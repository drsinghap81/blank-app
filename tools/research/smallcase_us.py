"""Research (12 Nov 2026): smallcase-style US stock baskets for Trading 212 pies (rules-based, equal weight, rebalanced on a
schedule), vs S&P 500 (SPY), Nasdaq 100 (QQQ) and equal-weight S&P (RSP). Universe = TODAY's S&P 500 + Nasdaq 100 members
(survivorship bias: flatters every basket; measured by comparing our equal-weight universe with the real RSP ETF).
Monthly data 2008 -> last month, auto-adjusted (dividends in), 0.15% per unit traded (Trading 212 AU FX).
Writes data/research/smallcase_us.json."""
import io, json, os
import numpy as np, pandas as pd, requests, yfinance as yf

H = {"User-Agent": "Mozilla/5.0"}
sp = pd.read_html(io.StringIO(requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=H, timeout=30).text))[0]
ndq = set()
try:
    for t in pd.read_html(io.StringIO(requests.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers=H, timeout=30).text)):
        cols = [c for c in t.columns if str(c).strip().lower() in ("ticker", "symbol")]
        if cols and len(t) >= 90:
            ndq = set(t[cols[0]].astype(str).str.replace(".", "-", regex=False)); break
except Exception as ex:  # noqa: BLE001
    print("nasdaq list failed", ex)
print("S&P", len(sp), "Nasdaq", len(ndq))
U = sorted(set(sp["Symbol"].str.replace(".", "-", regex=False)) | ndq)
SECT = dict(zip(sp["Symbol"].str.replace(".", "-", regex=False), sp["GICS Sector"]))
BEN = ["SPY", "QQQ", "RSP", "BIL", "MTUM"]
px = yf.download(U + BEN, start="2006-01-01", auto_adjust=True, progress=False, threads=True)["Close"]
D = px.dropna(how="all")
M = D.resample("ME").last(); M = M.loc["2007-01-31":]
R = M.pct_change()
COST = 0.0015
stocks = [c for c in U if c in M.columns]
vol = D[stocks].pct_change().rolling(252).std().resample("ME").last() * np.sqrt(252)
hi52 = D[stocks].rolling(252).max().resample("ME").last()
sma10 = M.rolling(10).mean()
m12_1 = M[stocks].shift(1) / M[stocks].shift(12) - 1
m6 = M[stocks] / M[stocks].shift(6) - 1
m3 = M[stocks] / M[stocks].shift(3) - 1


def basket(score_fn, n=20, every=1, filt=None, maxsec=None):
    idx = M.loc["2008-01-31":].index; w = {}; prev = {}; out = []; hold_n = []
    for i in range(len(idx) - 1):
        d, nx = idx[i], idx[i + 1]
        if i % every == 0:
            s = score_fn(d)
            s = s[[M.loc[d, k] == M.loc[d, k] and k in stocks for k in s.index]].dropna().sort_values(ascending=False)
            pick = []
            cnt = {}
            for k in s.index:
                sec = SECT.get(k, "Other")
                if maxsec and cnt.get(sec, 0) >= maxsec:
                    continue
                pick.append(k); cnt[sec] = cnt.get(sec, 0) + 1
                if len(pick) >= n:
                    break
            w = {k: 1 / len(pick) for k in pick} if pick else {"BIL": 1.0}
            if filt and not filt(d):
                w = {"BIL": 1.0}
        turn = sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev))
        r = sum(v * (R.loc[nx, k] if pd.notna(R.loc[nx, k]) else 0) for k, v in w.items()) - turn * COST
        out.append((nx, r)); hold_n.append(len(w))
        g = {k: v * (1 + (R.loc[nx, k] if pd.notna(R.loc[nx, k]) else 0)) for k, v in w.items()}; s_ = sum(g.values()) or 1
        prev = {k: v / s_ for k, v in g.items()}
    return pd.Series(dict(out)), w


def stats(s):
    eq = (1 + s).cumprod(); dd = (eq / eq.cummax() - 1).min()
    cg = lambda x: ((1 + x).prod() ** (12 / len(x)) - 1) * 100 if len(x) else None  # noqa: E731
    yr = (1 + s).groupby(s.index.year).prod() - 1
    return dict(cagr=round(cg(s), 1), maxdd=round(dd * 100, 1), p1=round(cg(s.loc[:"2016-12-31"]), 1), p2=round(cg(s.loc["2017-01-01":]), 1),
                last3=round(cg(s.iloc[-36:]), 1), worst_year=round(yr.min() * 100, 1),
                years={int(y): round(v * 100, 1) for y, v in yr.items()})


mkt_up = lambda d: M.loc[d, "SPY"] > sma10.loc[d, "SPY"]  # noqa: E731
near_hi = lambda d: (M.loc[d, stocks] / hi52.loc[d, stocks] >= 0.95)  # noqa: E731
tests = {
    "Momentum 20 (12-1 m), monthly": dict(f=lambda d: m12_1.loc[d], n=20),
    "Momentum 20 (12-1 m), quarterly": dict(f=lambda d: m12_1.loc[d], n=20, every=3),
    "Momentum 20, monthly, max 5 per sector": dict(f=lambda d: m12_1.loc[d], n=20, maxsec=5),
    "Momentum 20, monthly, cash when S&P < 10-m avg": dict(f=lambda d: m12_1.loc[d], n=20, filt=mkt_up),
    "Momentum 10 (12-1 m), monthly": dict(f=lambda d: m12_1.loc[d], n=10),
    "Momentum 30 (12-1 m), quarterly": dict(f=lambda d: m12_1.loc[d], n=30, every=3),
    "6-m momentum 20, monthly": dict(f=lambda d: m6.loc[d], n=20),
    "Near 52-w high + 12-1 m momentum 20, monthly": dict(f=lambda d: m12_1.loc[d].where(near_hi(d)), n=20),
    "Momentum / volatility 20 (risk-adjusted), monthly": dict(f=lambda d: (m12_1.loc[d] / vol.loc[d]), n=20),
    "Low volatility 30, quarterly": dict(f=lambda d: -vol.loc[d], n=30, every=3),
    "Equal weight whole universe (bias check vs RSP)": dict(f=lambda d: M.loc[d, stocks] * 0 + 1, n=len(stocks), every=12),
}
res = []; now = {}
for k, t in tests.items():
    s, w = basket(t["f"], t["n"], t.get("every", 1), t.get("filt"), t.get("maxsec"))
    res.append(dict(name=k, **stats(s))); now[k] = sorted(w, key=lambda x: -w[x])[:30]
bench = []
for b in ["SPY", "QQQ", "RSP", "MTUM"]:
    s = R[b].loc["2008-02-29":].dropna()
    if len(s):
        bench.append(dict(name=b, **stats(s)))
os.makedirs("data/research", exist_ok=True)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"), universe=len(stocks), last=str(M.index[-1].date()),
               note="Survivorship: universe = today's members; compare 'Equal weight whole universe' with RSP for the size of the bias.",
               results=res, bench=bench, holdings_now=now), open("data/research/smallcase_us.json", "w"), indent=1)
for r in bench + res: print(r["name"], r["cagr"], r["maxdd"], r["p1"], r["p2"], r["last3"])
