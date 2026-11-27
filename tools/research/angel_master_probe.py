"""probe the public Angel One scrip master: NSE -EQ and BSE equity tokens for the arbitrage pilot's 20 stocks."""
import json

import requests

S = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK", "AXISBANK", "HINDUNILVR",
     "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL", "NTPC", "POWERGRID", "M&M", "TITAN"]
M = requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json", timeout=120).json()
nse = {x["name"]: x["token"] for x in M if x.get("exch_seg") == "NSE" and str(x.get("symbol", "")).endswith("-EQ") and x.get("name") in S}
bse = {}
for x in M:
    if x.get("exch_seg") == "BSE" and not x.get("instrumenttype") and x.get("symbol") in S:
        bse.setdefault(x["symbol"], x["token"])
print("R| NSE " + json.dumps(nse)); print("R| BSE " + json.dumps(bse))
print("R| missing", [s for s in S if s not in nse], [s for s in S if s not in bse])
