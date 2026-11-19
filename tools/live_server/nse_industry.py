"""NSE's official industry classification for every NSE stock (20 Nov 2026, Amritpal: StockEdge-style industry charts from the
public NSE Indices "Industry Classification Structure": macro sector -> sector -> industry -> basic industry, ~190 basic industries).
NSE shows each stock's classification on its quote page (api/quote-equity -> industryInfo) but blocks cloud servers such as
GitHub's; this server is in Mumbai, so it fetches the map here and serves it read-only at /api/nse_industry for the nightly scan.
Runs at most once every 6 days, only outside 08:30-16:00 IST, ~3 requests a second (about 15 minutes for ~2,200 symbols).
Public, non-account data. Output: DATA/nse_industry.json"""
import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/get-quotes/equity"}


class NseIndustry:
    def __init__(self, data_dir, log=lambda *a, **k: None, session=None):
        self.path = os.path.join(data_dir, "nse_industry.json"); self.log = log
        self.st = self._load(); self.thread = None; self.lock = threading.Lock(); self.progress = None; self.err = None
        self._session = session

    def _load(self):
        try:
            return json.load(open(self.path))
        except Exception:  # noqa: BLE001
            return {}

    def status(self):
        return dict(asof=self.st.get("asof"), n=len(self.st.get("rows") or {}), progress=self.progress, error=self.err)

    def due(self, now=None):
        now = now or datetime.now(IST)
        if 8 * 60 + 30 <= now.hour * 60 + now.minute <= 16 * 60:
            return False
        a = self.st.get("asof")
        return not a or (now - datetime.fromisoformat(a)).days >= 6

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start(); return True

    def _sess(self):
        if self._session is not None:
            return self._session
        import requests
        s = requests.Session(); s.headers.update(UA)
        for u in ("https://www.nseindia.com/", "https://www.nseindia.com/market-data/live-equity-market"):
            try:
                s.get(u, timeout=20)
            except Exception:  # noqa: BLE001
                pass
        return s

    def symbols(self, s):
        r = s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=30)
        rows = list(csv.DictReader(io.StringIO(r.text)))
        key = next((k for k in (rows[0].keys() if rows else []) if k.strip() == "SERIES"), None)
        return [x["SYMBOL"].strip() for x in rows if key and x[key].strip() in ("EQ", "BE")]

    def _run(self):
        try:
            s = self._sess(); syms = self.symbols(s); out = dict(self.st.get("rows") or {}); fails = 0
            for i, sym in enumerate(syms):
                self.progress = f"{i + 1}/{len(syms)}"
                try:
                    r = s.get("https://www.nseindia.com/api/quote-equity", params={"symbol": sym}, timeout=20)
                    if r.status_code in (401, 403):
                        fails += 1
                        if fails % 20 == 0:
                            s = self._sess() if self._session is None else s      # cookies expired: warm up again
                        time.sleep(2); continue
                    ii = (r.json() or {}).get("industryInfo") or {}
                    if ii.get("basicIndustry"):
                        out[sym] = [ii.get("macro") or "", ii.get("sector") or "", ii.get("industry") or "", ii.get("basicIndustry") or ""]
                except Exception:  # noqa: BLE001
                    fails += 1
                time.sleep(0.33)
            with self.lock:
                self.st = dict(asof=datetime.now(IST).isoformat(timespec="minutes"), rows=out, fails=fails, symbols=len(syms))
                tmp = self.path + ".tmp"; json.dump(self.st, open(tmp, "w")); os.replace(tmp, self.path)
            self.err = None; self.log("nse_industry_done", n=len(out), fails=fails)
        except Exception as ex:  # noqa: BLE001
            self.err = str(ex)[:200]; self.log("nse_industry_error", error=self.err)
        finally:
            self.progress = None

    def loop(self):
        while True:
            try:
                if self.due():
                    self._run()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1800)
