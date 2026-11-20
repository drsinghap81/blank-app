"""probe 2: Nasdaq per-ticker daily bars speed + Yahoo v8 chart for LSE (20 Nov 2026)"""
import time
from concurrent.futures import ThreadPoolExecutor
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "application/json"}
def nq(t):
    r = requests.get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass=stocks&fromdate=2026-11-12&limit=10", headers=H, timeout=20)
    rows = (((r.json() or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    return t, r.status_code, [(x["date"], x["close"]) for x in rows[:2]]
tk = "AAPL MSFT NVDA AMZN GOOGL META TSLA JPM XOM UNH HD PG KO PEP COST WMT DIS NFLX AMD INTC CSCO ORCL CRM ADBE QCOM TXN IBM BA CAT GE".split()
t0 = time.time()
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(nq, tk))
print("R| nasdaq 30 tickers in", round(time.time() - t0, 1), "s; ok", sum(1 for r in res if r[1] == 200 and r[2]), "sample", res[:3], flush=True)
for t in ("HSBA.L", "III.L", "BP.L", "VOD.L"):
    j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10d&interval=1d", headers=H, timeout=20).json()
    r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    print("R|", t, [(time.strftime("%Y-%m-%d", time.gmtime(ts)), c) for ts, c in zip(r["timestamp"][-3:], q["close"][-3:])], flush=True)
j = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=10d&interval=1d", headers=H, timeout=20).json()
r = j["chart"]["result"][0]; print("R| AAPL v8", [(time.strftime("%Y-%m-%d", time.gmtime(ts)), c) for ts, c in zip(r["timestamp"][-3:], r["indicators"]["quote"][0]["close"][-3:])])
