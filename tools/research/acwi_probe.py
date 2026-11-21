"""Probe: can the Action download ACWI country weights? (21 Nov 2026)"""
import io
import subprocess
import sys

import requests
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pypdf"], check=False)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
s = requests.Session(); s.headers.update(H)
pg = "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf"
r0 = s.get(pg, timeout=60); print("R| page", r0.status_code, len(r0.text), flush=True)
for u in [pg + "/1467271812596.ajax?fileType=csv&fileName=ACWI_holdings&dataType=fund",
          pg + "/1521942788811.ajax?fileType=xls&fileName=iShares-MSCI-ACWI-ETF_fund&dataType=fund"]:
    r = s.get(u, timeout=60, headers={"Referer": pg}); t = r.text
    print("R|", r.status_code, len(t), u[-60:], "|", t[:200].replace("\n", " "), flush=True)
r = requests.get("https://www.msci.com/documents/10199/a71b65b5-d0ea-4b5c-a709-24b1213bc3c5", headers=H, timeout=60)
from pypdf import PdfReader  # noqa: E402
txt = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
i = txt.upper().find("COUNTRY WEIGHTS")
print("R| MSCI pdf chars", len(txt), "| around COUNTRY WEIGHTS:", txt[i - 50:i + 600].replace("\n", " | ") if i >= 0 else txt[:800].replace("\n", " | "), flush=True)
