"""Probe: ACWI country weights inside the iShares product page (21 Nov 2026)"""
import re

import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
t = requests.get("https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf", headers=H, timeout=60).text
for m in list(re.finditer(r"India", t))[:6]:
    print("R| India ctx:", t[max(0, m.start() - 300):m.start() + 200].replace("\n", " "), flush=True)
for k in ("tabsExposureBreakdownsGeography", "subTabsCountries", "exposureBreakdowns", "Geography", "Location of Holdings"):
    i = t.find(k); print("R| key", k, i, t[i:i + 400].replace("\n", " ") if i >= 0 else "", flush=True)
