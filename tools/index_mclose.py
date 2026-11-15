"""NSE indices month-close check (15 Nov 2026): did the last COMPLETED month close above the index's all-time HIGH (highest
intraday level of all earlier months, as on TradingView), after a base of >= 12 months since that high?
Data: NSE's daily ind_close_all_DDMMYYYY.csv (every NSE index, OHLC). Cache data/scan/index_hl.csv.gz (Date, INDEX, HIGH,
CLOSE) is built once from 2005 (resumable, time-boxed) and then topped up with the missing days.
Output data/scan/index_mclose.json: the month-close rows plus each index's distance from its all-time high."""
import io, json, os, sys, time
from datetime import datetime, timezone, timedelta
import numpy as np, pandas as pd, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cupclose import IX_DY_DEP, IX_WK_DEP, wd_closes  # noqa: E402

CACHE = "data/scan/index_hl.csv.gz"; OUT = "data/scan/index_mclose.json"; START = "2005-01-01"
MAXMIN = float(sys.argv[1]) if len(sys.argv) > 1 else 80
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"})
T0 = time.time()


def day_file(d):
    for u in ("https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
              "https://archives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"):
        try:
            r = S.get(u.format(d=d), timeout=25)
            if r.status_code == 200 and b"Index" in r.content[:200]:
                x = pd.read_csv(io.BytesIO(r.content)); x.columns = [c.strip() for c in x.columns]
                col = lambda k: next(c for c in x.columns if k.lower() in c.lower())  # noqa: E731
                return pd.DataFrame({"Date": d.date(), "INDEX": x[col("Index Name")].astype(str).str.strip().str.upper(),
                                     "HIGH": pd.to_numeric(x[col("High")], errors="coerce"), "CLOSE": pd.to_numeric(x[col("Clos")], errors="coerce")})
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def load(today):
    have = pd.read_csv(CACHE, parse_dates=["Date"]) if os.path.exists(CACHE) else pd.DataFrame(columns=["Date", "INDEX", "HIGH", "CLOSE"])
    done = set(pd.to_datetime(have.Date).dt.date) if len(have) else set()
    tried = set()
    if os.path.exists(CACHE + ".empty"):
        tried = set(pd.to_datetime(open(CACHE + ".empty").read().split()).date)
    days = [d for d in pd.bdate_range(START, today) if d.date() not in done and d.date() not in tried]
    days.sort(reverse=True)                  # newest first, so a time-boxed run always has the recent months
    new, empty = [], []
    for d in days:
        if (time.time() - T0) / 60 > MAXMIN:
            print("time budget reached; resume next run", flush=True); break
        x = day_file(d)
        (new if x is not None else empty).append(x if x is not None else d)
        time.sleep(0.15)
    H = pd.concat([have] + new) if new else have
    H["Date"] = pd.to_datetime(H.Date)
    H = H.dropna(subset=["CLOSE"]).drop_duplicates(["Date", "INDEX"]).sort_values(["INDEX", "Date"])
    H.to_csv(CACHE, index=False)
    old = [d for d in empty if (pd.Timestamp(today) - d).days > 10]   # holidays / missing files: don't retry (recent ones may appear later)
    if old:
        open(CACHE + ".empty", "a").write("".join(f"{d.date()}\n" for d in old))
    print("index rows", len(H), "new days", len(new), "left", max(0, len(days) - len(new) - len(empty)), flush=True)
    return H, max(0, len(days) - len(new) - len(empty))


def main():
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    H, left = load(today)
    # NSE renamed its indices in Nov 2015 (CNX -> Nifty): join the old history to the current name
    REN = {"S&P CNX NIFTY": "NIFTY 50", "CNX NIFTY": "NIFTY 50", "CNX BANK": "NIFTY BANK", "CNX NIFTY JUNIOR": "NIFTY NEXT 50", "S&P CNX 500": "NIFTY 500",
           "CNX MIDCAP": "NIFTY MIDCAP 100", "CNX SMALLCAP": "NIFTY SMALLCAP 100", "CNX FINANCE": "NIFTY FINANCIAL SERVICES", "CNX SERVICE SECTOR": "NIFTY SERVICES SECTOR",
           "CNX CONSUMPTION": "NIFTY INDIA CONSUMPTION", "CNX HIGH BETA": "NIFTY HIGH BETA 50", "CNX LOW VOLATILITY": "NIFTY LOW VOLATILITY 50", "CNX ALPHA INDEX": "NIFTY ALPHA 50",
           "CNX DIVIDEND OPPORTUNITIES": "NIFTY DIVIDEND OPPORTUNITIES 50", "CPSE": "NIFTY CPSE", "S&P CNX 500 SHARIAH": "NIFTY500 SHARIAH", "CNX 500 SHARIAH": "NIFTY500 SHARIAH"}
    names = set(H.INDEX)
    for o in set(H.INDEX):
        if o not in REN and o.startswith("CNX ") and "NIFTY " + o[4:] in names:
            REN[o] = "NIFTY " + o[4:]
    REN = {o: n for o, n in REN.items() if n in names}
    H = H.assign(INDEX=H.INDEX.replace(REN)).sort_values(["INDEX", "Date"]).drop_duplicates(["Date", "INDEX"], keep="last")
    lm = pd.Timestamp(today).to_period("M") - 1
    rows, dist, wrows, drows = [], [], [], []
    first = H.Date.min()
    for name, g in H.groupby("INDEX"):
        g = g.set_index("Date").sort_index()
        if len(g) < 300:
            continue
        mon = g.index.to_period("M")
        mc = g.CLOSE.groupby(mon).last(); mh = g.HIGH.fillna(g.CLOSE).groupby(mon).max()
        if mc.index[-1] < lm or lm not in mc.index:
            continue
        i = list(mc.index).index(lm); ph = mh.iloc[:i]
        if len(ph) < 13:
            continue
        a = int(np.argmax(ph.to_numpy())); old = float(ph.iloc[a]); base = i - a; c = float(mc.iloc[i]); last = float(g.CLOSE.iloc[-1])
        allh = float(mh.max())
        w = g.CLOSE[g.index <= lm.to_timestamp(how="end")].resample("W-FRI").last().dropna(); sma = w.rolling(30).mean()
        rising = bool(len(sma.dropna()) > 5 and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5])
        try:
            wk, dy = wd_closes(g.rename(columns={"HIGH": "High", "CLOSE": "Close"}), IX_WK_DEP, IX_DY_DEP)
            for z, L in ((wk, wrows), (dy, drows)):
                if z:
                    L.append(dict(index=name, close=last, since=str(g.index[0].date()), sma_rising=rising, **z))
        except Exception as e:  # noqa: BLE001
            print("wd fail", name, e)
        dist.append(dict(index=name, close=last, ath=allh, below_pct=round((1 - last / allh) * 100, 2), since=str(g.index[0].date())))
        if c > old and base >= 12:
            dep = float(mc.iloc[a + 1:i].min() / old - 1) if a + 1 < i else 0.0
            rows.append(dict(index=name, month=str(lm), close_m=c, high_m=float(mh.iloc[i]), old_ath=old, ath_month=str(ph.index[a]), base_months=int(base), depth=round(dep, 4),
                             above_pct=round((c / old - 1) * 100, 2), sma_rising=rising, long_cup=bool(base >= 36 and dep <= -0.30), close=last,
                             since=str(g.index[0].date())))
    rows.sort(key=lambda r: (-r["long_cup"], -r["base_months"]))
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), month=str(lm), history_from=str(first.date()) if len(H) else None,
                   backfill_left=left, rows=rows, week_close=wrows, day_close=drows, indices=sorted(dist, key=lambda r: r["below_pct"])), open(OUT, "w"), separators=(",", ":"))
    print("indices", len(dist), "month-close rows", len(rows), "week", [r["index"] for r in wrows], "day", [r["index"] for r in drows])


if __name__ == "__main__":
    main()
