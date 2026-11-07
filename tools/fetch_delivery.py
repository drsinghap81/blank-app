"""NSE daily delivery position (security-wise MTO file) for one calendar year -> deliv/deliv_YEAR.csv.gz
Columns: date, symbol, series, traded_qty, deliv_qty, deliv_pct (EQ and BE series only).
Usage: python tools/fetch_delivery.py 2016"""
import gzip, io, os, sys, time
from datetime import date, timedelta
import requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})
yr = int(sys.argv[1]); d = date(yr, 1, 1); end = min(date(yr, 12, 31), date.today())
os.makedirs("deliv", exist_ok=True)
out = gzip.open(f"deliv/deliv_{yr}.csv.gz", "wt"); out.write("date,symbol,series,traded_qty,deliv_qty,deliv_pct\n")
ok = miss = 0
while d <= end:
    if d.weekday() < 5:
        txt = None
        for host in ("https://nsearchives.nseindia.com", "https://archives.nseindia.com"):
            for _ in range(3):
                try:
                    r = s.get(f"{host}/archives/equities/mto/MTO_{d:%d%m%Y}.DAT", timeout=30)
                    if r.status_code == 200 and b",EQ," in r.content[:20000] or (r.status_code == 200 and b",BE," in r.content[:20000]):
                        txt = r.text; break
                    if r.status_code == 404:
                        break
                except Exception:  # noqa: BLE001
                    time.sleep(2)
            if txt:
                break
        if txt:
            n = 0
            for line in io.StringIO(txt):
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 7 and p[0] == "20" and p[3] in ("EQ", "BE"):
                    out.write(f"{d.isoformat()},{p[2]},{p[3]},{p[4]},{p[5]},{p[6]}\n"); n += 1
            ok += 1
            if ok % 50 == 0:
                print(d, "files", ok, "rows", n, flush=True)
        else:
            miss += 1
        time.sleep(0.25)
    d += timedelta(days=1)
out.close(); print("year", yr, "files", ok, "missing weekdays", miss)
