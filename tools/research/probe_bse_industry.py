"""probe: BSE scrip master industry fields, and NSE quote API basicIndustry (20 Nov 2026)"""
import json
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com", "Accept": "application/json"}
try:
    r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active", headers=H, timeout=60)
    print("BSE", r.status_code, len(r.content)); j = r.json(); print("R|", len(j), json.dumps(j[:2])[:800])
    from collections import Counter
    print("R| industries", len({x.get("INDUSTRY") for x in j}), Counter(x.get("INDUSTRY") for x in j).most_common(40))
except Exception as e:
    print("R| BSE fail", e)
S = requests.Session(); S.headers.update({"User-Agent": H["User-Agent"], "Referer": "https://www.nseindia.com/", "Accept": "application/json"})
try:
    S.get("https://www.nseindia.com/", timeout=20)
    for sym in ("BALRAMCHIN", "SUPREMEIND", "TATASTEEL"):
        r = S.get(f"https://www.nseindia.com/api/quote-equity?symbol={sym}", timeout=20)
        print("R| NSE", sym, r.status_code, json.dumps((r.json() if r.ok else {}).get("industryInfo"))[:300])
except Exception as e:
    print("R| NSE fail", e)
