"""Append new trading days to data/futures/<SYM>.csv from the NSE UDiFF F&O bhavcopy.
Run daily (after the close). Corporate actions (one-day ratio < 0.65 or > 1.5) are
back-adjusted the same way as tools/build_futures.py."""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_bot import fetch_bhavcopy, IST  # noqa: E402
from datetime import datetime

FUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "futures")


def main():
    files = {f[:-4].replace("M_M", "M&M"): os.path.join(FUT, f) for f in os.listdir(FUT) if f.endswith(".csv")}
    data = {s: pd.read_csv(p, index_col=0, parse_dates=True) for s, p in files.items()}
    last = min(d.index.max() for d in data.values() if len(d) and d.index.max() > pd.Timestamp("2026-01-01"))
    today = pd.Timestamp(datetime.now(IST).date())
    added = 0
    for day in pd.bdate_range(last + pd.Timedelta(days=1), today):
        b = fetch_bhavcopy(day)
        if b is None:
            continue
        b = b[b["FinInstrmTp"].isin(["IDF", "STF"])].copy()
        b["Exp"] = pd.to_datetime(b["XpryDt"])
        for s, d in data.items():
            if day in d.index or d.index.max() < pd.Timestamp("2026-01-01"):
                continue  # already have it, or symbol no longer trades
            g = b[(b["TckrSymb"] == s) & (b["Exp"] >= day)].sort_values("Exp")
            if g.empty:
                continue
            n = g.iloc[0]
            row = pd.DataFrame([dict(Open=n.OpnPric, High=n.HghPric, Low=n.LwPric, Close=n.ClsPric,
                                     Expiry=n.Exp.strftime("%Y-%m-%d"), Lot=n.get("NewBrdLotQty"))], index=[day])
            r = row["Close"].iloc[0] / d["Close"].iloc[-1]
            if r < 0.65 or r > 1.5:
                d[["Open", "High", "Low", "Close"]] *= r
                print(f"{s}: corporate-action adjust {day.date()} x{r:.4f}")
            data[s] = pd.concat([d, row])
            added += 1
    for s, d in data.items():
        d.index.name = "Date"
        d.to_csv(files[s])
    print("appended", added, "bars")


if __name__ == "__main__":
    main()
