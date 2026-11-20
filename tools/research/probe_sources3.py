"""probe 3: UK daily closes from the FT and the LSE's own API (20 Nov 2026)"""
import re
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "*/*"}
for nm, u in (("FT hist", "https://markets.ft.com/data/equities/tearsheet/historical?s=HSBA:LSE"),
              ("LSE api", "https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/HSBA"),
              ("LSE chart api", "https://api.londonstockexchange.com/api/v1/pages?path=stock/HSBA/hsbc-holdings-plc/company-page"),
              ("investing", "https://www.investing.com/equities/hsbc-holdings-plc-historical-data"),
              ("marketwatch", "https://www.marketwatch.com/investing/stock/hsba/download-data?countrycode=uk"),
              ("wsj csv", "https://www.wsj.com/market-data/quotes/UK/XLON/HSBA/historical-prices/download?num_rows=10&range_days=10&startDate=11/10/2026&endDate=11/20/2026")):
    try:
        r = requests.get(u, headers=H, timeout=30); t = r.text
        m = re.findall(r"(Nov 1[89], 2026|19/11/2026|2026-11-19|11/19/2026|Thursday, November 19, 2026)[^<]{0,120}", t)[:2]
        print(f"R| {nm}: {r.status_code} {len(r.content)}b 19Nov-mentions {m} :: {t[:160]!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"R| {nm}: ERROR {e}", flush=True)
