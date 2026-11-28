"""Arbitrage PILOT backtest (27 Nov 2026, Amritpal: "identify arbitrage opportunities in two ways: NSE vs BSE price of the same stock;
synthetic future (CE buy + PE sell) vs future buy and vice versa" -> "do a pilot backtest first").
Angel 1-minute candles, last ~10 trading days, downloaded on the server outside market hours.
A) NSE vs BSE: 20 liquid stocks. Per minute, gap = (NSE close - BSE close) / mid. Capturing it needs shares already held (sell the
   dear exchange, buy the cheap one), so the bar is the cost of two delivery legs: ~0.25% (STT 0.1% a side + charges + slippage).
B) Synthetic vs future (conversion / reversal): NIFTY, BANKNIFTY + 5 big F&O stocks, current monthly expiry, the 7 strikes around
   the future. Synthetic = K + (CE - PE) x e^(rT) (same expiry, r = 6.5%); gap = future - synthetic in points.
   gap > 0: future dear -> sell future, buy CE, sell PE (conversion); gap < 0 -> reversal. Bar: round-trip costs of 3 legs
   (brokerage, STT on option / future sells, exchange charges) + slippage of ~1 tick-spread a leg, in points (COST_PTS below).
Caveat: 1-minute CLOSES are last trades, not simultaneous bid / ask - gaps are an UPPER bound. A gap counts as tradable only if it
clears the bar on 3 minutes in a row (time to place 2-3 legs). Results: DATA/research/arb/results.json and /api/research/arb/summary."""
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta

VERSION = 4
# v4 (28 Nov 2026): the v3 run (Saturday 04:19 IST) got no candles at all from Angel - an empty run now raises so it is retried
# (3 tries, 15 minutes apart) instead of saving an empty result.
# v3 (28 Nov 2026): the server's scrip master keeps only F&O rows (memory), so no NSE / BSE equity token was found and part A never
# ran - equity tokens are now fixed here (from Angel's public master, 28 Nov 2026). Part B adds samples of the biggest gaps
# (future, CE, PE) and the median gap per day, to check the large synthetic gaps of v2 (likely stale or re-used option tokens).
NSE_TOK = {"NTPC": "11630", "BHARTIARTL": "10604", "HDFCBANK": "1333", "POWERGRID": "14977", "INFY": "1594", "TCS": "11536", "RELIANCE": "2885",
           "ITC": "1660", "KOTAKBANK": "1922", "M&M": "2031", "BAJFINANCE": "317", "SUNPHARMA": "3351", "TATASTEEL": "3499", "AXISBANK": "5900",
           "MARUTI": "10999", "HINDUNILVR": "1394", "LT": "11483", "TITAN": "3506", "ICICIBANK": "4963", "SBIN": "3045"}
BSE_TOK = {"TITAN": "500114", "M&M": "500520", "BAJFINANCE": "500034", "KOTAKBANK": "500247", "TATASTEEL": "500470", "SBIN": "500112",
           "INFY": "500209", "HDFCBANK": "500180", "LT": "500510", "RELIANCE": "500325", "HINDUNILVR": "500696", "ITC": "500875",
           "MARUTI": "532500", "AXISBANK": "532215", "TCS": "532540", "POWERGRID": "532898", "SUNPHARMA": "524715", "BHARTIARTL": "532454",
           "ICICIBANK": "532174", "NTPC": "532555"}
STOCKS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK", "AXISBANK", "HINDUNILVR",
          "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL", "NTPC", "POWERGRID", "M&M", "TITAN"]
SYN = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "SBIN"]
NSE_BSE_COST = 0.25            # % - two delivery legs
COST_PTS = {"NIFTY": 4.0, "BANKNIFTY": 10.0}     # points per conversion round trip (fees + ~1 tick-spread a leg); stocks: 0.08% of price
RATE = 0.065


def _ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _quiet():
    t = _ist()
    return t.weekday() >= 5 or not ((9, 0) <= (t.hour, t.minute) <= (15, 45))


class ArbBT:
    def __init__(self, broker, data_dir, log=print):
        self.b, self.log = broker, log
        self.dir = os.path.join(data_dir, "research", "arb"); os.makedirs(self.dir, exist_ok=True)
        self.sp = os.path.join(self.dir, "state.json")
        try:
            self.st = json.load(open(self.sp))
        except Exception:  # noqa: BLE001
            self.st = dict(state="idle", progress="")
        self.thread = None

    def _save(self):
        json.dump(self.st, open(self.sp, "w"))

    def status(self):
        try:
            res = json.load(open(os.path.join(self.dir, "results.json")))
        except Exception:  # noqa: BLE001
            res = None
        return dict(self.st, running=bool(self.thread and self.thread.is_alive()), results=res)

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self.st.update(state="running", started=_ist().isoformat(timespec="minutes")); self._save()
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()
        return True

    def _get(self, exchange, token, d0, d1):
        while not _quiet():
            self.st["progress"] = "paused for market hours"; self._save(); time.sleep(300)
        # v2 (27 Nov 2026): the first run died on "Access denied because of exceeding access rate" (it overlapped the option
        # backtest) - slower requests, and a rate-limit answer waits and retries instead of ending the run
        for wait in (20, 60, 120, 300, 0):
            try:
                api = self.b._session()
                r = self.b._call(api.getCandleData, dict(exchange=exchange, symboltoken=str(token), interval="ONE_MINUTE",
                                                         fromdate=d0.strftime("%Y-%m-%d 09:15"), todate=d1.strftime("%Y-%m-%d 15:30")), tries=4) or {}
                time.sleep(1.2)
                return {str(x[0])[:16]: float(x[4]) for x in (self.b._data(r) or [])}
            except Exception as ex:  # noqa: BLE001
                if "rate" not in str(ex).lower() or not wait:
                    raise
                self.st["progress"] = f"Angel rate limit - waiting {wait} s"; self._save(); time.sleep(wait)
        return {}

    def _optbt_busy(self):
        try:
            return json.load(open(os.path.join(os.path.dirname(self.dir), "optbt", "state.json"))).get("state") == "running"
        except Exception:  # noqa: BLE001
            return False

    def _run(self):
        while not _quiet() or self._optbt_busy():        # v2: never alongside the option backtest (shared Angel rate limit)
            self.st["progress"] = "waiting for the market to close" if not _quiet() else "waiting for the option backtest to finish"
            self._save(); time.sleep(300)
        for attempt in range(3):
            try:
                self._run_once(); return
            except Exception as ex:  # noqa: BLE001
                self.st.update(state="error", progress=f"try {attempt + 1}: {str(ex)[:180]}"); self._save(); self.log("arb_bt_error", error=str(ex)[:200])
                time.sleep(900)
                while not _quiet():
                    time.sleep(300)

    def _run_once(self):
        today = _ist().date(); d1 = today if _ist().hour >= 16 else today - timedelta(days=1); d0 = d1 - timedelta(days=14)
        M = self.b._master()
        eq_nse, eq_bse, fut, opt = {}, {}, {}, {}
        for x in M:
            seg, nm, sym = x.get("exch_seg"), x.get("name"), str(x.get("symbol", ""))
            it = str(x.get("instrumenttype", ""))
            if seg == "NSE" and sym.endswith("-EQ") and nm in STOCKS:
                eq_nse[nm] = x["token"]
            elif seg == "BSE" and nm in STOCKS and not it:
                eq_bse.setdefault(nm, x["token"])
            elif seg == "NFO" and nm in SYN and it in ("FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK"):
                try:
                    e = datetime.strptime(str(x["expiry"]).title(), "%d%b%Y").date()
                except Exception:  # noqa: BLE001
                    continue
                if e < today:
                    continue
                if it.startswith("FUT"):
                    fut.setdefault(nm, []).append((e, x["token"], int(float(x.get("lotsize") or 0))))
                else:
                    opt.setdefault((nm, e), {}).setdefault(round(float(x.get("strike") or 0) / 100, 2), {})[sym[-2:]] = x["token"]
        for k, v in NSE_TOK.items():
            eq_nse.setdefault(k, v)
        for k, v in BSE_TOK.items():
            eq_bse.setdefault(k, v)
        res = dict(version=VERSION, method=__doc__, built=None, window=f"{d0} -> {d1}", nse_bse={}, synthetic={})
        # ---- A) NSE vs BSE
        for i, nm in enumerate(STOCKS):
            self.st["progress"] = f"NSE vs BSE {i + 1}/{len(STOCKS)} {nm}"; self._save()
            if nm not in eq_nse or nm not in eq_bse:
                res["nse_bse"][nm] = dict(note="no BSE / NSE token"); continue
            a, b = self._get("NSE", eq_nse[nm], d0, d1), self._get("BSE", eq_bse[nm], d0, d1)
            ks = sorted(set(a) & set(b))
            if len(ks) < 100:
                res["nse_bse"][nm] = dict(note=f"only {len(ks)} common minutes"); continue
            g = [(a[k] - b[k]) / ((a[k] + b[k]) / 2) * 100 for k in ks]
            ag = sorted(abs(x) for x in g)
            over = [abs(x) > NSE_BSE_COST for x in g]
            runs = sum(1 for j in range(2, len(over)) if over[j] and over[j - 1] and over[j - 2] and not (j > 2 and over[j - 3]))
            res["nse_bse"][nm] = dict(minutes=len(ks), median_abs_gap_pct=round(ag[len(ag) // 2], 4), p99_abs_gap_pct=round(ag[int(len(ag) * 0.99)], 4),
                                      max_abs_gap_pct=round(ag[-1], 4), minutes_over_cost=sum(over), runs_3min_over_cost=runs,
                                      biggest=[dict(t=ks[j], gap_pct=round(g[j], 3)) for j in sorted(range(len(g)), key=lambda q: -abs(g[q]))[:3]])
            self.log("arb_nse_bse", name=nm, **{k: v for k, v in res["nse_bse"][nm].items() if k != "biggest"})
        # ---- B) synthetic vs future
        for nm in SYN:
            self.st["progress"] = f"synthetic {nm}"; self._save()
            F = sorted(fut.get(nm) or [])
            if not F:
                res["synthetic"][nm] = dict(note="no future"); continue
            e, ftok, lot = F[0]
            fb = self._get("NFO", ftok, d0, d1)
            if not fb:
                res["synthetic"][nm] = dict(note="no future candles"); continue
            fl = fb[sorted(fb)[-1]]
            ch = opt.get((nm, e)) or {}
            ks = sorted((k for k in ch if "CE" in ch[k] and "PE" in ch[k]), key=lambda k: abs(k - fl))[:7]
            cost = COST_PTS.get(nm, fl * 0.0008)
            per = {}; allg = []
            for K in sorted(ks):
                ce, pe = self._get("NFO", ch[K]["CE"], d0, d1), self._get("NFO", ch[K]["PE"], d0, d1)
                tt = sorted(set(fb) & set(ce) & set(pe))
                if len(tt) < 30:
                    continue
                g = []
                for t in tt:
                    T = max((e - datetime.strptime(t[:10], "%Y-%m-%d").date()).days, 0) / 365
                    g.append(fb[t] - (K + (ce[t] - pe[t]) * math.exp(RATE * T)))
                byd = {}
                for t, x in zip(tt, g):
                    byd.setdefault(t[:10], []).append(x)
                top = sorted(range(len(g)), key=lambda q: -abs(g[q]))[:3]
                diag = dict(by_day_median={d: round(sorted(v)[len(v) // 2], 1) for d, v in byd.items()},
                            biggest=[dict(t=tt[q], fut=fb[tt[q]], ce=ce[tt[q]], pe=pe[tt[q]], gap=round(g[q], 1)) for q in top])
                over = [abs(x) > cost for x in g]
                runs = sum(1 for j in range(2, len(over)) if over[j] and over[j - 1] and over[j - 2] and not (j > 2 and over[j - 3]))
                ag = sorted(abs(x) for x in g); allg += g
                per[str(K)] = dict(minutes=len(tt), median_gap_pts=round(sorted(g)[len(g) // 2], 2), median_abs_pts=round(ag[len(ag) // 2], 2),
                                   p95_abs_pts=round(ag[int(len(ag) * 0.95)], 2), max_abs_pts=round(ag[-1], 2), minutes_over_cost=sum(over),
                                   runs_3min_over_cost=runs, best_rs_per_lot=round((ag[-1] - cost) * lot, 0), **diag)
            sg = sorted(abs(x) for x in allg) if allg else [0]
            res["synthetic"][nm] = dict(expiry=str(e), lot=lot, future_last=fl, cost_pts=round(cost, 2), strikes=per,
                                        all_median_abs_pts=round(sg[len(sg) // 2], 2), all_p99_abs_pts=round(sg[int(len(sg) * 0.99)], 2),
                                        all_minutes_over_cost=sum(1 for x in allg if abs(x) > cost), all_minutes=len(allg))
            self.log("arb_synthetic", name=nm, **{k: v for k, v in res["synthetic"][nm].items() if k != "strikes"})
        if not any("minutes" in v for v in res["nse_bse"].values()) and not any("strikes" in v for v in res["synthetic"].values()):
            raise RuntimeError("Angel returned no candles for any symbol - will retry")
        res["built"] = _ist().isoformat(timespec="minutes")
        json.dump(res, open(os.path.join(self.dir, "results.json"), "w"), indent=1)
        self.st.update(state="done", progress="done"); self._save()
