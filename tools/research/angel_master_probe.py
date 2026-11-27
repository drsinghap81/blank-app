"""probe the public Angel One scrip master: BSE equity rows and NIFTY Dec-29 option rows (arb_bt token matching)."""
import collections
import json

import requests

M = requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json", timeout=120).json()
print("R| rows", len(M), "segments", collections.Counter(x.get("exch_seg") for x in M).most_common(12))
for nm in ("RELIANCE", "HDFCBANK", "M&M"):
    rows = [x for x in M if x.get("exch_seg") == "BSE" and (nm in str(x.get("name", "")) or str(x.get("symbol", "")).startswith(nm))][:4]
    for x in rows:
        print("R| BSE", nm, json.dumps(x))
rows = [x for x in M if x.get("exch_seg") == "NFO" and x.get("name") == "NIFTY" and "29DEC26" in str(x.get("symbol", "")) and str(x.get("strike", "")).startswith(("2560000", "2575000"))]
for x in rows:
    print("R| NFO", json.dumps(x))
rows = [x for x in M if x.get("exch_seg") == "NFO" and x.get("name") == "NIFTY" and str(x.get("instrumenttype")) == "FUTIDX"]
for x in rows:
    print("R| FUT", json.dumps(x))
