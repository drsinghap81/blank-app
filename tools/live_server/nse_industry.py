"""NSE's official industry classification for every NSE stock (20 Nov 2026, Amritpal: StockEdge-style industry charts from the
public NSE Indices "Industry Classification Structure": macro sector -> sector -> industry -> basic industry, ~190 basic industries).
NSE shows each stock's classification on its quote page (api/quote-equity -> industryInfo) but blocks cloud servers such as
GitHub's; this server is in Mumbai, so it fetches the map here and serves it read-only at /api/nse_industry for the nightly scan.
Runs at most once every 6 days, only outside 08:30-16:00 IST, ~3 requests a second (about 15 minutes for ~2,200 symbols).
Public, non-account data. Output: DATA/nse_industry.json
20 Nov 2026: NSE moved to www.nseindia.in and the old api/quote-equity now answers 403 to everyone; the new quote page reads
api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData -> equityResponse[0].secInfo (macro, sector, industryInfo,
basicIndustry). A pass that finds almost nothing (blocked) is retried after 6 hours instead of waiting 6 days."""
import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.in/"}
BASE = "https://www.nseindia.in"


class NseIndustry:
    MIN = 500          # fewer rows than this = the pass was blocked; retry sooner
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
        if not a:
            return True
        age = now - datetime.fromisoformat(a)
        if len(self.st.get("rows") or {}) < self.MIN:
            return age >= timedelta(hours=6)
        return age.days >= 6

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start(); return True

    def _sess(self):
        if self._session is not None:
            return self._session
        import requests
        s = requests.Session(); s.headers.update(UA)
        for u in (BASE + "/", BASE + "/get-quote/equity/SBIN/State-Bank-of-India"):
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
            # pilot (Amritpal, 20 Nov 2026: always pilot-check before a batch): 5 large stocks first; stop if none comes back
            pilot = {}
            for sym in ("RELIANCE", "SBIN", "BALRAMCHIN", "SUPREMEIND", "TCS"):
                row = self._one(s, sym)
                if row:
                    pilot[sym] = row
                time.sleep(0.5)
            if not pilot:
                raise RuntimeError("pilot failed: NSE returned no industry for 5 test stocks (blocked or the address changed)")
            self.log("nse_industry_pilot", ok=len(pilot), sample=pilot.get("BALRAMCHIN") or next(iter(pilot.values())))
            for i, sym in enumerate(syms):
                self.progress = f"{i + 1}/{len(syms)} found {len(out) - len(self.st.get('rows') or {})}"
                try:
                    r = s.get(BASE + "/api/NextApi/apiClient/GetQuoteApi",
                              params={"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym}, timeout=20)
                    if r.status_code in (401, 403):
                        fails += 1
                        if fails % 20 == 0:
                            s = self._sess() if self._session is None else s      # cookies expired: warm up again
                        time.sleep(2); continue
                    er = (r.json() or {}).get("equityResponse") or [{}]
                    si = (er[0] if er else {}).get("secInfo") or {}
                    if si.get("basicIndustry"):
                        out[sym] = [(si.get("macro") or "").strip(), (si.get("sector") or "").strip(),
                                    (si.get("industryInfo") or "").strip(), si["basicIndustry"].strip()]
                    else:
                        fails += 1
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

    def _one(self, s, sym):
        try:
            r = s.get(BASE + "/api/NextApi/apiClient/GetQuoteApi",
                      params={"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym}, timeout=20)
            er = (r.json() or {}).get("equityResponse") or [{}] if r.status_code == 200 else [{}]
            si = (er[0] if er else {}).get("secInfo") or {}
            if si.get("basicIndustry"):
                return [(si.get("macro") or "").strip(), (si.get("sector") or "").strip(), (si.get("industryInfo") or "").strip(), si["basicIndustry"].strip()]
        except Exception:  # noqa: BLE001
            pass
        return None

    def loop(self):
        while True:
            try:
                if self.due():
                    self._run()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1800)
