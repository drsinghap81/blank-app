"""probe: BSE Sensex 1991-2000 daily tables from bse-1991-2000.blogspot.com (year pages)"""
import re
import requests
import pandas as pd
from io import StringIO
U = {"User-Agent": "Mozilla/5.0"}
base = "https://bse-1991-2000.blogspot.com/"
r = requests.get(base + "p/bse-sensex-historical-prices-in-year_1204.html", headers=U, timeout=30, allow_redirects=True)
print("R| status", r.status_code, len(r.text), flush=True)
links = sorted(set(re.findall(r'https?://bse-1991-2000\.blogspot\.com/p/[^"\'#]+\.html', r.text)))
print("R| links", links, flush=True)
for u in links:
    try:
        t = requests.get(u.replace("http://", "https://"), headers=U, timeout=30).text
        yr = re.findall(r"year (\d{4})", t[:5000]) or re.findall(r"19\d\d", u)
        tabs = pd.read_html(StringIO(t))
        big = max(tabs, key=len)
        print(f"R| PAGE {u} years {yr[:3]} rows {len(big)} cols {list(big.columns)[:8]}", flush=True)
        for _, z in big.iterrows():
            print("R| ROW " + " | ".join(str(v) for v in z.values[:6]), flush=True)
    except Exception as e:  # noqa: BLE001
        print("R| fail", u, str(e)[:150], flush=True)
