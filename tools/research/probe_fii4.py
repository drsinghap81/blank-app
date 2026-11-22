"""Probe (22 Nov 2026): history for the other FII/DII lines (FII index futures / index options / stock futures / stock options net,
DII cash). NSE archives fii_stats_DD-Mon-YYYY.xls (FII derivatives turnover), and candidate DII cash history URLs."""
import io
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36", "Accept": "*/*"}
S = requests.Session(); S.headers.update(UA)
try:
    S.get("https://www.nseindia.com", timeout=20)
except Exception as e:  # noqa: BLE001
    print("R| home", e)
for u in ["https://nsearchives.nseindia.com/content/fo/fii_stats_20-Nov-2026.xls", "https://archives.nseindia.com/content/fo/fii_stats_20-Nov-2026.xls",
          "https://nsearchives.nseindia.com/content/fo/fii_stats_20-Nov-2017.xls", "https://nsearchives.nseindia.com/content/fo/fii_stats_02-Jan-2012.xls"]:
    try:
        r = S.get(u, timeout=30); print("R|", u, r.status_code, len(r.content), r.headers.get("content-type"))
        if r.status_code == 200:
            for eng in ("xlrd", None):
                try:
                    T = pd.read_excel(io.BytesIO(r.content), header=None, engine=eng); print("R| table\n" + T.head(12).to_string()); break
                except Exception as e:  # noqa: BLE001
                    print("R| read", eng, e)
    except Exception as e:  # noqa: BLE001
        print("R|", u, e)
for u in ["https://www.nseindia.com/api/fiidiiTradeReact", "https://www.nseindia.com/api/fiidiiTradeNse",
          "https://www.nseindia.com/api/historical/fii-dii?from=01-10-2026&to=20-11-2026",
          "https://www.nseindia.com/api/historicalOR/fii-dii?from=01-10-2026&to=20-11-2026",
          "https://nsearchives.nseindia.com/content/equities/fii_dii_20112026.csv"]:
    try:
        r = S.get(u, timeout=30); print("R|", u, r.status_code, r.text[:400].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print("R|", u, e)
