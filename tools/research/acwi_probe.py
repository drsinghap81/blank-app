"""Probe: can the Action download ACWI country weights? (21 Nov 2026)"""
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "text/csv,*/*"}
for u in ["https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/1467271812596.ajax?fileType=csv&fileName=ACWI_holdings&dataType=fund",
          "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/1467271812596.ajax?tab=all&fileType=json",
          "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spdw.xlsx",
          "https://www.msci.com/documents/10199/a71b65b5-d0ea-4b5c-a709-24b1213bc3c5"]:
    try:
        r = requests.get(u, headers=H, timeout=60)
        t = r.text
        print("R|", r.status_code, len(t), u[:90], "|", t[:300].replace("\n", " ")[:300], flush=True)
        if "Location" in t[:5000]:
            print("R| has Location column", flush=True)
    except Exception as e:  # noqa: BLE001
        print("R| fail", u[:90], e, flush=True)
