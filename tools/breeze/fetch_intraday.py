"""Download 1-minute history for expired NIFTY / BANKNIFTY options from ICICI Direct Breeze.

Runs on YOUR computer. Keys stay in keys.txt (or .env) next to this script (never commit it, never paste it in chat).

  python fetch_intraday.py --probe                    # 1 test call: shows how far back data goes
  python fetch_intraday.py --symbol NIFTY --from 2024-01-01
  python fetch_intraday.py --symbol BANKNIFTY --from 2023-01-01 --to 2024-11-30

For every expiry in expiries.csv it downloads the last 5 trading days before expiry:
  - the index itself (1-minute)
  - CE and PE for strikes ATM +- N steps (default 10), ATM taken from the futures price before the window
Files: out/<SYMBOL>/<expiry>/<CE|PE><strike>.csv and out/<SYMBOL>/<expiry>/INDEX.csv
Safe to stop and re-run: finished files are skipped. Stops by itself near Breeze's daily call limit.
"""
import argparse, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CODE = {"NIFTY": "NIFTY", "BANKNIFTY": "CNXBAN"}      # Breeze stock codes
DAILY_CAP = 4800                                       # Breeze allows ~5000 calls/day
PER_MIN = 90                                           # and ~100 calls/minute


def load_env():
    for p in (HERE / "keys.txt", HERE / ".env"):
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


LOG = HERE / "breeze_log.txt"


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def capture_session(url, timeout=300):
    """Open the ICICI login page and catch the apisession token on http://127.0.0.1 (the app's redirect URL)."""
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
    got = {}

    class H(BaseHTTPRequestHandler):
        def _grab(self, body=""):
            q = parse_qs(urlparse(self.path).query)
            q.update(parse_qs(body))
            if q.get("apisession"):
                got["tok"] = q["apisession"][0]
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(b"<h2>Logged in. You can close this tab and go back to the black window.</h2>")

        def do_GET(self):
            self._grab()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self._grab(self.rfile.read(n).decode("utf-8", "ignore"))

        def log_message(self, *a):
            pass

    try:
        srv = HTTPServer(("127.0.0.1", 80), H)
    except OSError as e:
        log("Could not listen on http://127.0.0.1 (", e, ") - falling back to copy/paste.")
        return None
    srv.timeout = 5
    log("Opening the ICICI login page in your browser. Log in there; this window continues by itself.")
    webbrowser.open(url)
    t0 = time.time()
    while "tok" not in got and time.time() - t0 < timeout:
        srv.handle_request()
    srv.server_close()
    return got.get("tok")


def connect():
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        log("Installing breeze-connect (one time)...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "breeze-connect", "pandas"])
        from breeze_connect import BreezeConnect
    load_env()
    key, secret = os.environ.get("BREEZE_API_KEY"), os.environ.get("BREEZE_API_SECRET")
    log("Python", sys.version.split()[0], "| API key found:", bool(key), "| secret found:", bool(secret))
    if not key or not secret:
        log("STOP: open keys.txt in this folder and paste your API key and secret after the = signs, then save.")
        raise SystemExit(1)
    from urllib.parse import quote_plus
    url = f"https://api.icicidirect.com/apiuser/login?api_key={quote_plus(key)}"
    tok = os.environ.get("BREEZE_SESSION") or capture_session(url)
    if not tok:
        print("Open this link, log in, and copy the number after 'apisession=' in the address bar:")
        print("  " + url)
        tok = input("apisession: ").strip()
    b = BreezeConnect(api_key=key)
    try:
        b.generate_session(api_secret=secret, session_token=tok)
    except Exception as e:
        log("LOGIN FAILED:", repr(e)[:300])
        raise SystemExit(1)
    log("Logged in to Breeze OK.")
    return b


class Limiter:
    def __init__(self):
        self.calls, self.window = 0, []

    def wait(self):
        if self.calls >= DAILY_CAP:
            raise SystemExit(f"Reached {DAILY_CAP} calls today - run again tomorrow, it resumes where it stopped.")
        now = time.time()
        self.window = [t for t in self.window if now - t < 60]
        if len(self.window) >= PER_MIN:
            time.sleep(60 - (now - self.window[0]) + 0.5)
        self.window.append(time.time())
        self.calls += 1


def iso(d, hh=9, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch(b, lim, sym, start, end, product, expiry=None, right="", strike=""):
    """1-minute candles start..end (dates), in chunks of 2 trading days (1000-candle limit)."""
    out, d = [], start
    while d <= end:
        e = min(d + timedelta(days=1), end)
        while e.weekday() >= 5 and e > d:
            e -= timedelta(days=1)
        lim.wait()
        kw = dict(interval="1minute", from_date=iso(d, 9, 0), to_date=iso(e, 15, 30), stock_code=CODE[sym])
        if product == "cash":
            kw.update(exchange_code="NSE", product_type="cash")
        else:
            kw.update(exchange_code="NFO", product_type="options", expiry_date=iso(expiry, 7, 0),
                      right=right, strike_price=str(int(strike)))
        for attempt in range(3):
            try:
                r = b.get_historical_data_v2(**kw)
                break
            except Exception as ex:          # network hiccup
                r = {"Error": str(ex)}
                time.sleep(3)
        if r and r.get("Error") and not r.get("Success") and lim.calls <= 3:
            log("Breeze reply:", str(r.get("Error"))[:200])
        if r and r.get("Success"):
            out += r["Success"]
        d = e + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    if not out:
        return None
    df = pd.DataFrame(out)
    keep = [c for c in ("datetime", "open", "high", "low", "close", "volume", "open_interest") if c in df]
    return df[keep].drop_duplicates("datetime")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="NIFTY", choices=list(CODE))
    ap.add_argument("--from", dest="frm", default="2024-01-01")
    ap.add_argument("--to", default="2099-01-01")
    ap.add_argument("--strikes", type=int, default=10, help="strikes each side of ATM")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--index-history", action="store_true", help="continuous 1-minute index candles, one file per month")
    a = ap.parse_args()

    b, lim = connect(), Limiter()
    if a.index_history:
        months = pd.period_range(a.frm, min(pd.Timestamp(a.to), pd.Timestamp.today()), freq="M")[::-1]
        folder = Path(a.out) / "INDEX_1min" / a.symbol
        folder.mkdir(parents=True, exist_ok=True)
        for m in months:
            f = folder / f"{m}.csv"
            if f.exists() and m < pd.Period(pd.Timestamp.today(), "M"):
                continue
            df = fetch(b, lim, a.symbol, m.start_time.date(), m.end_time.date(), "cash")
            (df if df is not None else pd.DataFrame()).to_csv(f, index=False)
            log(f"{a.symbol} index {m}: {0 if df is None else len(df)} candles   (calls today {lim.calls})")
        print("Done.")
        return
    ex = pd.read_csv(HERE / "expiries.csv", parse_dates=["expiry", "window_start"])

    if a.probe:      # how far back does Breeze go? try one ATM call for a few old expiries
        for _, r in ex[ex.symbol == a.symbol].iloc[::40].iterrows():
            k = round(r.ref_price / r.strike_step) * r.strike_step
            df = fetch(b, lim, a.symbol, r.expiry.date(), r.expiry.date(), "options", r.expiry.date(), "call", k)
            log(f"{a.symbol} {r.expiry.date()} CE{int(k)}:", "no data" if df is None else f"{len(df)} candles OK")
        return

    sel = ex[(ex.symbol == a.symbol) & (ex.expiry >= a.frm) & (ex.expiry <= a.to)].sort_values("expiry", ascending=False)
    print(f"{len(sel)} expiries to do for {a.symbol}  (newest first)")
    for _, r in sel.iterrows():
        e, ws = r.expiry.date(), r.window_start.date()
        folder = Path(a.out) / a.symbol / str(e)
        folder.mkdir(parents=True, exist_ok=True)
        atm = round(r.ref_price / r.strike_step) * r.strike_step
        jobs = [("INDEX", None, None)] + [(f"{rt}{int(atm + i * r.strike_step)}", "call" if rt == "CE" else "put",
                                          atm + i * r.strike_step)
                                         for i in range(-a.strikes, a.strikes + 1) for rt in ("CE", "PE")]
        got = 0
        for name, right, k in jobs:
            f = folder / f"{name}.csv"
            if f.exists():
                continue
            df = fetch(b, lim, a.symbol, ws, e, "cash" if name == "INDEX" else "options", e, right or "", k or "")
            if df is None:
                f.write_text("")            # empty marker: no data for this contract
            else:
                df.to_csv(f, index=False); got += 1
        log(f"{a.symbol} {e}: {got} new files   (calls today {lim.calls})")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        log("ERROR:", traceback.format_exc()[-1500:])
