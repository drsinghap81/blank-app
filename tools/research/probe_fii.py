"""Probe FII data sources (22 Nov 2026): NSDL FPI daily / fortnightly sector reports, NSE FII/DII API."""
import re
import requests

s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"})
U = ["https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx",
     "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx",
     "https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx",
     "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Nov152026.html",
     "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Oct312026.html",
     "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Mar152016.html",
     "https://www.fpi.nsdl.co.in/web/Reports/Yearwise.aspx?RptType=6",
     "https://www.nseindia.com/api/fiidiiTradeReact"]
for u in U:
    try:
        r = s.get(u, timeout=40); t = r.text
        print("R|", u, r.status_code, len(t))
        txt = re.sub(r"<[^>]+>", " ", t); txt = re.sub(r"\s+", " ", txt)
        print("R|   ", txt[:700])
        if "Selection" in u or "Archive" in u:
            print("R|   links", re.findall(r'href="([^"]+)"', t)[:40])
            print("R|   inputs", re.findall(r'name="([^"]+)"', t)[:40])
            print("R|   options", re.findall(r'<option[^>]*value="([^"]*)"', t)[:60])
    except Exception as e:  # noqa: BLE001
        print("R|", u, "err", e)
