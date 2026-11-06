"""Download 15-minute NSE candles from Angel SmartAPI (read-only market data, no orders) for a list of symbols,
zip them, and create a one-time download link served by app.py at /dl/<key> (valid 2 hours, one use).

Run on the server (as the service user, so it can read .env and write var/):
  sudo -u trenddesk /opt/trenddesk/venv/bin/python /opt/trenddesk/repo/tools/live_server/fetch_candles.py \
       /opt/trenddesk/repo/tools/live_server/udts_symbols.txt 2022-01-01
"""
import csv, gzip, io, json, os, re, sys, tempfile, time, zipfile
from datetime import date, datetime, timedelta

ENVF = os.environ.get("ENV_FILE", "/opt/trenddesk/.env")
for line in open(ENVF):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), re.sub(r"\s+#.*$", "", v).strip())
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from brokers import AngelEquity  # noqa: E402

DATA = os.environ.get("DATA_DIR", "/opt/trenddesk/var")
syms = [s.strip() for s in open(sys.argv[1]) if s.strip()]
start = datetime.strptime(sys.argv[2] if len(sys.argv) > 2 else "2022-01-01", "%Y-%m-%d")
end = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=15, minutes=30)
CHUNK = timedelta(days=95)          # Angel allows up to ~100 days per FIFTEEN_MINUTE request

b = AngelEquity(dict(os.environ), tempfile.mkdtemp()); api = b._session()
out = os.path.join(DATA, "candles_15m"); os.makedirs(out, exist_ok=True)
log = []
for n, sym in enumerate(syms, 1):
    ts = f"{sym}-EQ"
    if ts not in b.tokens:
        log.append(f"{sym}: not in scrip master"); continue
    tok = b.tokens[ts]["token"]; rows = []; t0 = start
    while t0 < end:
        t1 = min(t0 + CHUNK, end)
        p = dict(exchange="NSE", symboltoken=str(tok), interval="FIFTEEN_MINUTE",
                 fromdate=t0.strftime("%Y-%m-%d 09:15"), todate=t1.strftime("%Y-%m-%d 15:30"))
        for k in range(4):
            try:
                r = api.getCandleData(p) or {}
                if r.get("status") or r.get("data") is not None:
                    rows += r.get("data") or []; break
                time.sleep(1.5 * (k + 1))
            except Exception as e:  # noqa: BLE001
                time.sleep(1.5 * (k + 1))
                if k == 3:
                    log.append(f"{sym} {p['fromdate']}: {str(e)[:80]}")
        time.sleep(0.4)                 # stay under Angel's ~3 requests/second
        t0 = t1 + timedelta(days=1)
    seen = set(); rows = [r for r in rows if not (r[0] in seen or seen.add(r[0]))]
    with gzip.open(os.path.join(out, f"{sym}.csv.gz"), "wt", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "open", "high", "low", "close", "volume"]); w.writerows(rows)
    print(f"{n:3d}/{len(syms)} {sym}: {len(rows)} bars {rows[0][0][:10] if rows else '-'} .. {rows[-1][0][:10] if rows else '-'}", flush=True)

zp = os.path.join(DATA, "candles_15m.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
    for f in sorted(os.listdir(out)):
        z.write(os.path.join(out, f), f)
    z.writestr("log.txt", "\n".join(log))
key = os.urandom(16).hex()
json.dump(dict(key=key, file="candles_15m.zip", until=time.time() + 7200), open(os.path.join(DATA, "dl.json"), "w"))
print("ZIP", zp, os.path.getsize(zp), "bytes; problems:", len(log))
print("DOWNLOAD__KEY", key)
