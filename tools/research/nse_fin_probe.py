"""Probe 2 (14 Nov 2026): where NSE serves quarterly results filed since 2025 (SEBI 'Integrated Filing - Financials')."""
import json, os, time
import requests
OUT = "data/research/nse_fin_probe"; os.makedirs(OUT, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
for u in ("https://www.nseindia.com/", "https://www.nseindia.com/companies-listing/corporate-integrated-filing"):
    try: S.get(u, timeout=20)
    except Exception as e: print("warm", e)
rep = {}
C = [("ifr", "https://www.nseindia.com/api/integrated-filing-results", dict(index="equities", symbol="TCS")),
     ("ifr2", "https://www.nseindia.com/api/integrated-filing-results", dict(index="equities", symbol="TCS", type="Integrated Filing- Financials")),
     ("ifr3", "https://www.nseindia.com/api/integrated-filing-results", dict(index="equities", symbol="TCS", period_ended="all", type="Integrated Filing- Financials")),
     ("cif", "https://www.nseindia.com/api/corporates-integrated-filing", dict(index="equities", symbol="TCS")),
     ("cfr_all", "https://www.nseindia.com/api/corporates-financial-results", dict(index="equities", symbol="TCS", period="Quarterly", from_date="01-01-2025", to_date="14-11-2026")),
     ("cmp", "https://www.nseindia.com/api/results-comparision", dict(symbol="TCS")),
     ("annc", "https://www.nseindia.com/api/corporate-announcements", dict(index="equities", symbol="TCS", subject="Financial Results")),
     ("xbrl_if", "https://www.nseindia.com/api/integrated-filing-results-xbrl", dict(index="equities", symbol="TCS"))]
for name, url, p in C:
    try:
        r = S.get(url, params=p, timeout=30); txt = r.text
        rep[name] = dict(status=r.status_code, n=len(r.content), head=txt[:700])
        open(f"{OUT}/p2_{name}.json", "w").write(txt[:300000])
    except Exception as e:
        rep[name] = dict(error=str(e)[:200])
    time.sleep(1.5)
json.dump(rep, open(f"{OUT}/report2.json", "w"), indent=1); print(json.dumps(rep, indent=1)[:8000])
