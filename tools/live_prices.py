"""Live (~15 min delayed) prices for EVERY NSE stock in last night's scan (data/scan/nse_close.json), for the app's
portfolio view. Publishing the whole market keeps anyone's holdings private: the app looks up its own symbols on the
phone, and nothing about the holdings is stored in the repo. Writes data/live/nse_prices.json (pushed to 'live')."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

OUT = "data/live"


def main():
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if os.environ.get("FORCE") != "1" and (now.weekday() > 4 or not (9 * 60 + 15 <= now.hour * 60 + now.minute <= 15 * 60 + 40)):
        print("outside NSE hours"); return
    syms = sorted(json.load(open("data/scan/nse_close.json"))["prices"])
    prices = {}
    for i in range(0, len(syms), 250):
        chunk = [s + ".NS" for s in syms[i:i + 250]]
        try:
            d = yf.download(chunk, period="5d", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("chunk fail", i, e); continue
        c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else d[["Close"]].set_axis(chunk, axis=1)
        for t in chunk:
            if t not in c:
                continue
            x = c[t].dropna()
            if len(x) >= 2:
                last_day = x.index[-1].date()
                prev = float(x.iloc[-2]) if last_day == now.date() else float(x.iloc[-1])
                prices[t[:-3]] = [round(float(x.iloc[-1]), 2), round(prev, 2)]
        time.sleep(1)
    os.makedirs(OUT, exist_ok=True)
    json.dump(dict(time=now.strftime("%Y-%m-%d %H:%M IST"), delayed_min=15, prices=prices),
              open(f"{OUT}/nse_prices.json", "w"), separators=(",", ":"))
    print(len(prices), "prices")


if __name__ == "__main__":
    main()
