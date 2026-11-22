"""Probe 2: NSDL daily archive (ASP.NET postback) + parse one fortnightly sector table."""
import re
import io
import requests
import pandas as pd

s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"})
u = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
r = s.get(u, timeout=40); t = r.text
f = {k: v for k, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', t)}
print("R| hidden", {k: len(v) for k, v in f.items()})
print("R| txtDate html", re.findall(r'<input[^>]*txtDate[^>]*>', t)[:2])
for dv in ["15-Oct-2026", "Oct-2026", "15/10/2026"]:
    data = {k: f.get(k, "") for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
    data.update(__EVENTTARGET="btnSubmit1", __EVENTARGUMENT="", txtDate=dv, hdnDate=dv)
    try:
        p = s.post(u, data=data, timeout=60)
        tx = re.sub(r"<[^>]+>", " ", p.text); tx = re.sub(r"\s+", " ", tx)
        i = tx.find("Debt")
        print("R| post", dv, p.status_code, len(p.text), tx[max(0, i - 600):i + 900])
        try:
            T = pd.read_html(io.StringIO(p.text))
            print("R| tables", [x.shape for x in T][:8])
            big = max(T, key=lambda x: x.shape[0]); print("R|", big.head(12).to_string()[:2500])
        except Exception as e:  # noqa: BLE001
            print("R| no tables", e)
    except Exception as e:  # noqa: BLE001
        print("R| post err", dv, e)
# fortnightly table
h = s.get("https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Nov152026.html", timeout=40).text
T = pd.read_html(io.StringIO(h)); big = max(T, key=lambda x: x.shape[0] * x.shape[1])
print("R| fortnight shape", big.shape); print("R|", big.iloc[:8, :14].to_string()[:3000]); print("R|", big.iloc[:, :3].to_string()[:3000])
