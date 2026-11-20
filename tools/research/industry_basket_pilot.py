"""Pilot (20 Nov 2026): can we get hourly + 5-minute NSE stock bars from Yahoo, and the NSE industry map from our server?"""
import requests
import yfinance as yf
m = requests.get("https://13-126-118-48.sslip.io/api/nse_industry", timeout=60).json()
print("R| map rows", len(m.get("rows") or {}), "asof", m.get("asof"), "SBIN", (m.get("rows") or {}).get("SBIN"))
for iv, per in (("1h", "730d"), ("5m", "60d")):
    d = yf.download(["SBIN.NS", "TCS.NS", "BALRAMCHIN.NS", "ASTRAL.NS", "RELIANCE.NS"], period=per, interval=iv, progress=False, group_by="column", auto_adjust=False)
    c = d["Close"]
    print("R|", iv, "rows", len(c), "first", c.index[0], "last", c.index[-1], "tz", c.index.tz, "nan%", round(float(c.isna().mean().mean()) * 100, 1))
    day = c.index[-1].date(); print("R|", iv, "bars on", day, [str(t.time()) for t in c.index if t.date() == day][:10])
