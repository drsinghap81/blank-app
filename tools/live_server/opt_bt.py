"""Backtest of the 5-minute ATM option RSI-60 basket (18 Nov 2026, Amritpal: "can you backtest this for some time back").

Rules (exactly the basket checked live on 18 Nov):
  each liquid F&O name + NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY; contract = near MONTHLY expiry with >= 3 days left, strike nearest
  the underlying's previous close; CE and PE of that strike on 5-minute bars.
  ENTRY (18 Nov 2026): buy-stop above the signal candle's high for the next 3 candles, cancelled if its low breaks first.
  signal on a 5-minute close (before 15:00): RSI(14) of the option crosses above 60, the option is above its session VWAP and the
  OTHER option (PE for a CE signal) is below its session VWAP  ->  BUY that option (CE = bullish, PE = bearish; never a sale).
  stop = the signal candle's low (at least 3% of the premium), target = entry + 3 x risk; first touched wins (stop first if both in
  one bar); otherwise out at the day's last 5-minute close (intraday). One open trade per contract.
  index filter (the version Amritpal asked for): CE buys only while Nifty AND Bank Nifty are above yesterday's close at the
  signal bar, PE buys only while both are below.
  costs: 1% of the premium round trip (brokerage, taxes, slippage), charged in R.
  SMA-20 trail version (Amritpal's chart): RSI 60 cross + close above a rising 20 SMA, buy next open, exit on a close below
  the 20 SMA (held overnight), on 5- and 15-minute bars.
  BB: also split by the signal candle closing above the option's upper Bollinger band (20, 2).
  sector: CE/PE kept only if the stock's sector (average day % of its other F&O stocks, from put-call parity) agrees.
  Pulse (20 Nov 2026, Amritpal: "put buys should be on low-strength stocks and vice versa"): each stock trade carries its NSE
  industry's Pulse rank (0-1 across industries) as of the PREVIOUS session (data/research/nse_pulse_daily.json, built on GitHub).
  PCR: each trade also carries the stock's PCR quintile from the previous session (data/scan/pcr_hist.json) to see if it adds value.
Data: Angel 5-minute candles. Angel only serves LIVE contracts, so the history reaches back to the day after the previous monthly
expiry (about 3-4 weeks) - a short sample. Downloads only outside market hours (~1-2 requests a second); resumable.
Output: DATA/research/optbt/results.json"""
VERSION = 13                    # 26 Nov 2026: index 5-minute bars fetched in 20-day pieces (v12 got none for the longer window) + a run-debug block in the results.
# v12: 26 Nov 2026: index + daily-close cache keys include the start date (v11 reused v10's files, which began on ~19 Nov).
# v11: 26 Nov 2026: reuse cached 5-minute bars of EXPIRED monthly contracts, so the test keeps the weeks before the last expiry (v10 ran on 1 day after the 24 Nov expiry).
# v10: 23 Nov 2026: sector-green + green index slices (Amritpal: "enter after the first 5 minutes with the option trader's conditions" in green sectors)
# v8: 21 Nov 2026: rotation quadrant slices; 20 Nov 2026: Pulse slices (puts on weak-Pulse stocks, calls on strong) | bump to re-run the backtest after a server update (18 Nov 2026: sell-the-opposite variants)
import glob
import gzip
import json
import os
import threading
import time
from datetime import date, datetime, timedelta

IDXTOK = {"NIFTY": "99926000", "BANKNIFTY": "99926009", "FINNIFTY": "99926037", "MIDCPNIFTY": "99926074", "SENSEX": "99919000"}
IDXEX = {"SENSEX": "BSE"}          # index exchange for the daily closes (the rest are NSE)
COST = 0.01


def _ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _quiet():
    t = _ist()
    return t.weekday() >= 5 or not ((9, 0) <= (t.hour, t.minute) <= (15, 45))


def bb_upper(c, n=20, k=2.0):
    """upper Bollinger band (20-bar SMA + 2 population standard deviations) per bar; None before 20 bars."""
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]; m = sum(w) / n
        out[i] = m + k * (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return out


def sma(c, n):
    out = [None] * len(c); s_ = 0.0
    for i, v in enumerate(c):
        s_ += v
        if i >= n:
            s_ -= c[i - n]
        if i >= n - 1:
            out[i] = s_ / n
    return out


def ema(c, n):
    out, k, e = [], 2 / (n + 1), None
    for v in c:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out


def resample(B, mins):
    """5-minute bars (iso time, o, h, l, c, v) -> `mins`-minute bars from 09:15 IST each day."""
    out = []
    for b in B:
        hh, mm = int(b[0][11:13]), int(b[0][14:16]); k = ((hh * 60 + mm) - 555) // mins
        key = b[0][:10] + "#" + str(k)
        if out and out[-1][6] == key:
            o_ = out[-1]; out[-1] = (o_[0], o_[1], max(o_[2], b[2]), min(o_[3], b[3]), b[4], o_[5] + b[5], key)
        else:
            out.append((b[0], b[1], b[2], b[3], b[4], b[5], key))
    return [x[:6] for x in out]


def rsi_series(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l_ = 0.0
    for i in range(1, n + 1):
        d_ = c[i] - c[i - 1]; g += max(d_, 0); l_ += max(-d_, 0)
    g /= n; l_ /= n; out[n] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    for i in range(n + 1, len(c)):
        d_ = c[i] - c[i - 1]; g = (g * (n - 1) + max(d_, 0)) / n; l_ = (l_ * (n - 1) + max(-d_, 0)) / n
        out[i] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    return out


def prev_expiry(e):
    """the monthly expiry of the month before e's: NSE's last Tuesday (close enough when a holiday moves it a day)."""
    first = e.replace(day=1); d = first - timedelta(days=1)
    while d.weekday() != 1:
        d -= timedelta(days=1)
    return d


class OptBT:
    def __init__(self, broker, data_dir, rows_fn, log=print, pcr_fn=None):
        self.b, self.rows_fn, self.log, self.pcr_fn = broker, rows_fn, log, pcr_fn
        self.dir = os.path.join(data_dir, "research", "optbt"); os.makedirs(self.dir, exist_ok=True)
        self.sp = os.path.join(self.dir, "state.json")
        try:
            self.st = json.load(open(self.sp))
        except Exception:  # noqa: BLE001
            self.st = dict(state="idle", progress="", errors=0)
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
        self.st.update(state="running", started=_ist().isoformat(timespec="minutes"), errors=0); self._save()
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()
        return True

    # ------------------------------------------------------------------ data
    def _get(self, exchange, token, interval, d0, d1):
        while not _quiet():
            self.st["progress"] = "paused for market hours"; self._save(); time.sleep(300)
        api = self.b._session()
        r = self.b._call(api.getCandleData, dict(exchange=exchange, symboltoken=str(token), interval=interval,
                                                 fromdate=d0.strftime("%Y-%m-%d 09:15"), todate=d1.strftime("%Y-%m-%d 15:30")), tries=4) or {}
        time.sleep(0.45)
        return [(str(x[0])[:16], float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5] if len(x) > 5 else 0)) for x in (self.b._data(r) or [])]

    def _cached(self, key, exchange, token, interval, d0, d1):
        p = os.path.join(self.dir, key + ".json.gz")
        if os.path.exists(p):
            return json.load(gzip.open(p, "rt"))
        try:
            B = self._get(exchange, token, interval, d0, d1)
        except Exception as ex:  # noqa: BLE001
            self.st["errors"] = self.st.get("errors", 0) + 1; self.log("optbt_fetch_error", key=key, error=str(ex)[:120]); return []
        json.dump(B, gzip.open(p, "wt"))
        return B

    def _chain(self, seg="NFO"):
        """name -> {expiry date: sorted strikes} from Angel's scrip master (options only)."""
        ch = {}
        for x in self.b._master():
            if x.get("exch_seg") != seg or not str(x.get("instrumenttype", "")).startswith("OPT"):
                continue
            try:
                e = datetime.strptime(str(x["expiry"]).title(), "%d%b%Y").date()
            except Exception:  # noqa: BLE001
                continue
            ch.setdefault(x["name"], {}).setdefault(e, set()).add(round(float(x.get("strike") or 0) / 100, 2))
        return {n: {e: sorted(s) for e, s in d.items()} for n, d in ch.items()}

    # ------------------------------------------------------------------ run
    def _run(self):
        """18 Nov 2026: touch nothing (not even Angel's login) until the market is closed; retry a failed run up to 3 times."""
        for attempt in range(3):
            while not _quiet():
                self.st["progress"] = "waiting for the market to close"; self._save(); time.sleep(300)
            self._run_once()
            if self.st.get("state") == "done":
                return
            time.sleep(600)

    def _run_once(self):
        try:
            self.st.update(state="running", progress="starting"); self._save()
            rows = self.rows_fn()
            today = _ist().date(); last = today if (_ist().hour, _ist().minute) >= (15, 30) else today - timedelta(days=1)
            ch = self._chain()
            monthly = {}
            for n, d in ch.items():
                by_m = {}
                for e in d:
                    by_m[(e.year, e.month)] = max(by_m.get((e.year, e.month), e), e)
                monthly[n] = sorted(by_m.values())
            start = min((m[0] for m in monthly.values() if m), default=today) - timedelta(days=40)
            start = min(start, prev_expiry(min((m[0] for m in monthly.values() if m), default=today)) - timedelta(days=40))   # v11: expired month too
            idx = {}
            for nm in ("NIFTY", "BANKNIFTY"):        # v13: 20-day pieces (one long 5-minute request came back empty in v12)
                bars, a = {}, start
                while a <= last:
                    b_ = min(a + timedelta(days=19), last)
                    for x in self._cached(f"idx5_{nm}_{a}_{b_}", "NSE", IDXTOK[nm], "FIVE_MINUTE", a, b_):
                        bars[x[0]] = x
                    a = b_ + timedelta(days=1)
                idx[nm] = [bars[k] for k in sorted(bars)]
            days = sorted({b[0][:10] for b in idx["NIFTY"]})
            trades = []; self.syn = {}; self.trail = []; self.sym_err = []
            for k, r in enumerate(rows):
                sym = r["symbol"]; self.st["progress"] = f"{k + 1}/{len(rows)} {sym}"; self._save()
                try:
                    trades += self._symbol(sym, r.get("kind"), ch.get(sym) or {}, monthly.get(sym) or [], days, idx, last, r.get("lot") or 0)
                except Exception as ex:  # noqa: BLE001
                    self.log("optbt_symbol_error", symbol=sym, error=str(ex)[:160])
                    self.sym_err = (getattr(self, "sym_err", []) + [f"{sym}: {str(ex)[:120]}"])[:5]
            # 18 Nov 2026 (Amritpal: "weekly options for indices?"): Nifty again on its nearest WEEKLY expiry (>= 2 days left);
            # kept apart from the main results and compared with Nifty on the monthly
            try:
                nr = next((r for r in rows if r["symbol"] == "NIFTY"), None)
                if nr and ch.get("NIFTY"):
                    ntr = len(self.trail)
                    wk = self._symbol("NIFTY", "index", ch["NIFTY"], sorted(ch["NIFTY"]), days, idx, last, nr.get("lot") or 0, weekly=True)
                    del self.trail[ntr:]
                    for t in wk:
                        t["wk"] = True
                    trades += wk
            except Exception as ex:  # noqa: BLE001
                self.log("optbt_weekly_error", error=str(ex)[:160])
            # Sensex (BSE options, weekly + monthly) - same rules, kept apart from the main results
            self.sx_debug = {}
            try:
                bch = self._chain("BFO").get("SENSEX") or {}
                self.sx_debug = dict(bfo_names=sorted(self._chain("BFO"))[:15], expiries=[str(e) for e in sorted(bch)][:12],
                                     strikes_sample=(bch[min(bch)][::max(1, len(bch[min(bch)]) // 6)][:8] if bch else None))
                if bch:
                    lot_s = next((int(float(x.get("lotsize") or 0)) for x in self.b._master() if x.get("exch_seg") == "BFO" and x.get("name") == "SENSEX"), 0)
                    mon_s = sorted({max(e for e in bch if (e.year, e.month) == (m.year, m.month)) for m in bch})
                    ntr = len(self.trail)
                    self.sx_debug["lot"] = lot_s
                    for wkly, L in ((False, mon_s), (True, sorted(bch))):
                        got = self._symbol("SENSEX", "index", bch, L, days, idx, last, lot_s, weekly=wkly, seg="BFO")
                        self.sx_debug["weekly" if wkly else "monthly"] = dict(trades=len(got), plan_days=self._last_plan_days, series=self._last_series)
                        for t in got:
                            t["sx"] = "weekly" if wkly else "monthly"; trades.append(t)
                    del self.trail[ntr:]
            except Exception as ex:  # noqa: BLE001
                self.log("optbt_sensex_error", error=str(ex)[:160]); self.sx_debug["error"] = str(ex)[:300]
            try:                                                   # sector: average day % of the OTHER F&O stocks in the sector
                sec = sector_map()
                for t in trades:
                    g = sec.get(t["s"]); t["sector"] = g
                    if not g or t["idx"]:
                        t["sec"] = None; continue
                    vals = []
                    for s2, dd in self.syn.items():
                        if s2 == t["s"] or sec.get(s2) != g:
                            continue
                        path = dd.get(t["d"]) or {}
                        v = [path[x] for x in path if x <= t["t"]]
                        if v:
                            vals.append(v[-1])
                    t["sec"] = round(sum(vals) / len(vals), 2) if len(vals) >= 2 else None
                    t["sec_n"] = len(vals)
            except Exception as ex:  # noqa: BLE001
                self.log("optbt_sector_error", error=str(ex)[:120])
            try:                                                   # PCR quintile of the PREVIOUS session (known before the open)
                H = self.pcr_fn() if self.pcr_fn else {}
                hd = sorted(H)
                for t in trades:
                    prev = [x for x in hd if x < t["d"]]
                    t["pcrq"] = H[prev[-1]].get(t["s"]) if prev else None
            except Exception as ex:  # noqa: BLE001
                self.log("optbt_pcr_error", error=str(ex)[:120])
            try:                                                   # Pulse rank of the stock's NSE industry, previous session
                PH = pulse_hist(); pd_ = sorted(PH)
                for t in trades:
                    prev = [x for x in pd_ if x < t["d"]]
                    t["pulse"] = None if t["idx"] or not prev else PH[prev[-1]].get(t["s"])
                QH = quad_hist(); qd = sorted(QH)            # 21 Nov 2026: industry rotation quadrant (L / I / W / G), previous session
                for t in trades:
                    prev = [x for x in qd if x < t["d"]]
                    t["quad"] = None if t["idx"] or not prev else QH[prev[-1]].get(t["s"])
            except Exception as ex:  # noqa: BLE001
                self.log("optbt_pulse_error", error=str(ex)[:120])
            json.dump(trades, gzip.open(os.path.join(self.dir, "trades.json.gz"), "wt"))
            res = summarise([t for t in trades if not t.get("wk") and not t.get("sx")])
            try:
                M = [t for t in trades if not t.get("wk") and not t.get("sx")]
                up = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] > 0 and t["bn"] > 0      # noqa: E731
                dn = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] < 0 and t["bn"] < 0      # noqa: E731
                F = [t for t in M if (t["side"] == "CE" and up(t)) or (t["side"] == "PE" and dn(t))]
                paper = [dict(t, **t["alt"]["ema5"]) for t in F if (t.get("alt") or {}).get("ema5") and not ("11:00" <= t.get("et", t["t"]) < "14:30")
                         and t.get("bb") and t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))]
                res["Pulse"] = pulse_rows(F, paper)
                res["Pulse"]["trades with Pulse"] = sum(t.get("pulse") is not None for t in F)
                res["Rotation"] = quad_rows(F, paper); res["Rotation"]["trades with a quadrant"] = sum(t.get("quad") is not None for t in F)
                res["Sector green"] = sector_rows(F, paper)
            except Exception as ex:  # noqa: BLE001
                res["Pulse"] = dict(error=str(ex)[:200])
            res["NIFTY monthly vs weekly"] = nifty_weekly([t for t in trades if t["s"] == "NIFTY" and not t.get("wk")], [t for t in trades if t.get("wk")])
            res["SENSEX debug"] = getattr(self, "sx_debug", None)
            res["SENSEX monthly vs weekly"] = nifty_weekly([t for t in trades if t.get("sx") == "monthly"], [t for t in trades if t.get("sx") == "weekly"])
            res["SMA-20 trail version"] = trail_summary(self.trail)
            res["run debug"] = dict(start=str(start), last=str(last), days=len(days), first_day=days[0] if days else None, last_day=days[-1] if days else None,
                                    idx_bars={nm: len(v) for nm, v in idx.items()}, symbols=len(rows), trades=len(trades),
                                    fetch_errors=self.st.get("errors", 0), symbol_errors=getattr(self, "sym_err", []),
                                    trade_days=sorted({t["d"] for t in trades})[:40])
            json.dump(self.trail, gzip.open(os.path.join(self.dir, "trail.json.gz"), "wt"))
            res.update(method=__doc__, built=_ist().isoformat(timespec="minutes"), version=VERSION)
            json.dump(res, open(os.path.join(self.dir, "results.json"), "w"))
            self.st.update(state="done", progress="done", finished=_ist().isoformat(timespec="minutes"))
        except Exception as ex:  # noqa: BLE001
            self.st.update(state="error", progress=str(ex)[:200]); self.log("optbt_error", error=str(ex)[:200])
        self._save()

    def _symbol(self, sym, kind, chain, months, days, idx, last, lot=0, weekly=False, seg="NFO"):
        self._last_plan_days, self._last_series = 0, {}
        if kind == "index" or sym in IDXTOK:
            if sym not in IDXTOK:
                return []
            D = self._cached(f"d_{sym}_{days[0]}_{last}", IDXEX.get(sym, "NSE"), IDXTOK[sym], "ONE_DAY", date.fromisoformat(days[0]) - timedelta(days=10), last)
        else:
            _, t = self.b._ts(sym)
            D = self._cached(f"d_{sym}_{days[0]}_{last}", "NSE", t["token"], "ONE_DAY", date.fromisoformat(days[0]) - timedelta(days=10), last)
        closes = {b[0][:10]: b[4] for b in D}
        dl = sorted(closes)
        # v11 (26 Nov 2026): 5-minute bars of expired monthly contracts that earlier runs saved in the cache
        # (Angel no longer serves them), as {expiry: {strike: {"CE": path, "PE": path}}} - only strikes with both sides
        old = {}
        if not weekly:
            for f in glob.glob(os.path.join(self.dir, f"o_{sym}_*.json.gz")):
                try:
                    pre, ex_s, k_s, typ, _l = os.path.basename(f)[:-8].rsplit("_", 4)
                    if pre != f"o_{sym}":
                        continue
                    ex_d = date.fromisoformat(ex_s)
                    if months and ex_d >= months[0]:
                        continue
                    cur = old.setdefault(ex_d, {}).setdefault(float(k_s), {})
                    if typ not in cur or os.path.getmtime(f) > os.path.getmtime(cur[typ]):
                        cur[typ] = f
                except Exception:  # noqa: BLE001
                    continue
            old = {e: {k: v for k, v in K.items() if "CE" in v and "PE" in v} for e, K in old.items()}
            old = {e: K for e, K in old.items() if K}
        # which contract on which day
        plan = {}
        for d in days:
            dd = date.fromisoformat(d)
            if d not in closes:
                continue
            prev = [x for x in dl if x < d]
            if not prev:
                continue
            # Angel serves live contracts only: skip days whose near monthly (the previous month's) has already expired
            if not months or dd <= (months[0] - timedelta(days=7) if weekly else prev_expiry(months[0])):
                oe = next((e for e in sorted(old) if (e - dd).days >= 3 and dd > prev_expiry(e)), None) if not weekly else None
                if oe is not None:       # v11: an expired contract whose bars are cached
                    pc = closes[prev[-1]]; plan[d] = (oe, min(old[oe], key=lambda s_: abs(s_ - pc)))
                continue
            ex = next((e for e in months if (e - dd).days >= (2 if weekly else 3)), None)
            if ex is None:
                continue
            strikes = chain.get(ex) or []
            if not strikes:
                continue
            pc = closes[prev[-1]]; k = min(strikes, key=lambda s: abs(s - pc))
            plan[d] = (ex, k)
        out = []
        need = sorted(set(plan.values())); self._last_plan_days = len(plan)
        series = {}
        for ex, k in need:
            if ex in old and k in old[ex]:        # v11: expired contract, bars from the cache only
                for typ in ("CE", "PE"):
                    try:
                        series[(ex, k, typ)] = json.load(gzip.open(old[ex][k][typ], "rt"))
                    except Exception:  # noqa: BLE001
                        pass
                continue
            for typ in ("CE", "PE"):
                tk = self.b.opt_token(sym, ex, k, typ, exchange=seg)
                if not tk:
                    continue
                first = min(d for d, v in plan.items() if v == (ex, k))
                d0 = date.fromisoformat(first) - timedelta(days=12)
                series[(ex, k, typ)] = self._cached(f"o_{sym}_{ex}_{k:g}_{typ}_{last}", seg, tk[0], "FIVE_MINUTE", d0, last)
        self._last_series = {f"{a}|{b_:g}|{c_}": len(v) for (a, b_, c_), v in list(series.items())[:6]}; self._last_series["daily_closes"] = len(closes)
        ib = {nm: {b[0]: b[4] for b in idx[nm]} for nm in idx}
        ipc = {}
        for nm in idx:
            byday = {}
            for b in idx[nm]:
                byday[b[0][:10]] = b[4]
            dd = sorted(byday); ipc[nm] = {dd[i]: byday[dd[i - 1]] for i in range(1, len(dd))}
        for d, (ex, k) in plan.items():
            C, P = series.get((ex, k, "CE")), series.get((ex, k, "PE"))
            if not C or not P:
                continue
            # the stock's own day % from put-call parity (K + CE - PE ~ future), vs the same contract's previous-day last bar
            pm = {x[0]: x[4] for x in P}; synp = {}
            prevd = [x[0] for x in C if x[0][:10] < d]
            if prevd and prevd[-1] in pm:
                ref = k + [x[4] for x in C if x[0] == prevd[-1]][0] - pm[prevd[-1]]
                if ref > 0:
                    for x in C:
                        if x[0][:10] == d and x[0] in pm:
                            synp[x[0][11:16]] = (k + x[4] - pm[x[0]]) / ref * 100 - 100
            self.syn.setdefault(sym, {})[d] = synp
            for side, A, B in (("CE", C, P), ("PE", P, C)):
                rs = rsi_series([x[4] for x in A])
                bbu = bb_upper([x[4] for x in A]); sm20 = sma([x[4] for x in A], 20); em5 = ema([x[4] for x in A], 5); em3 = ema([x[4] for x in A], 3)
                trA = [max(x[2] - x[3], abs(x[2] - A[q - 1][4]), abs(x[3] - A[q - 1][4])) if q else x[2] - x[3] for q, x in enumerate(A)]
                atr14 = [sum(trA[max(0, q - 13):q + 1]) / len(trA[max(0, q - 13):q + 1]) for q in range(len(trA))]
                ia = [i for i, x in enumerate(A) if x[0][:10] == d]
                if len(ia) < 3:
                    continue
                bmap = {}; pv = vv = 0.0; bfull = {x[0]: x for x in B}

                def short_other(fi_, xi_, how_):
                    """18 Nov 2026 (Amritpal: "instead of buying the CE, sell the PE"): SELL the other option of the same strike at
                    the close of the fill candle, buy it back at the close of the exit candle (at that candle's HIGH when the trade
                    stopped out - conservative); 1% of the premium cost; margin ~18% (stocks) / 9% (indices) of strike x lot."""
                    bi_, bx_ = bfull.get(A[fi_][0]), bfull.get(A[xi_][0])
                    if not (bi_ and bx_ and lot):
                        return None
                    pin, pout = bi_[4], (bx_[2] if how_ == "SL" else bx_[4])
                    mg = (0.09 if kind == "index" else 0.18) * k * lot
                    return dict(pnl=round((pin - pout - COST * pin) * lot), inv=round(mg), pct=round((pin - pout - COST * pin) * lot / mg * 100, 2),
                                how=how_, prem=pin)
                for x in B:
                    if x[0][:10] == d:
                        pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]; bmap[x[0]] = (x[4], pv / vv if vv else x[4])
                pv = vv = 0.0; busy = -1
                for i in ia:
                    x = A[i]; pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]; vw = pv / vv if vv else x[4]
                    if x[0][11:16] >= "15:00" or i <= busy or rs[i] is None or rs[i - 1] is None or not (rs[i] > 60 >= rs[i - 1]):
                        continue
                    o = bmap.get(x[0])
                    if not o or not (x[4] > vw and o[0] < o[1]):
                        continue
                    tr = entry_sim([b[1] for b in A], [b[2] for b in A], [b[3] for b in A], [b[4] for b in A], i, ia[-1])
                    if tr is None:
                        continue
                    e, risk, how, exitp, j, fi = tr
                    R = -1.0 if how == "SL" else 3.0 if how == "target" else (exitp - e) / risk
                    busy = j
                    nf = ib["NIFTY"].get(x[0]); bn = ib["BANKNIFTY"].get(x[0])
                    nfp = (nf / ipc["NIFTY"][d] - 1) * 100 if nf and d in ipc["NIFTY"] else None
                    bnp = (bn / ipc["BANKNIFTY"][d] - 1) * 100 if bn and d in ipc["BANKNIFTY"] else None
                    # realistic version: stop-limit at most 1% above the trigger, and the signal candle must have traded >= 20 lots
                    trl = entry_sim([b[1] for b in A], [b[2] for b in A], [b[3] for b in A], [b[4] for b in A], i, ia[-1], limit=LIMIT)
                    real = None
                    if trl is not None and lot and x[5] >= 20 * lot:
                        e2, r2, h2, x2, _, _ = trl
                        R2 = -1.0 if h2 == "SL" else 3.0 if h2 == "target" else (x2 - e2) / r2
                        real = dict(R=round(R2 - COST * e2 / r2, 3), pct=round((x2 / e2 - 1 - COST) * 100, 2), how=h2,
                                    inv=round(e2 * lot), pnl=round((x2 - e2 - COST * e2) * lot))
                    # 18 Nov 2026 ("1:2 or 1:3?"): the same trade with a 1.5R / 2R target
                    alt = {}
                    for tr_ in (1.5, 2.0, "trail", "ema5"):
                        ta = entry_sim([b[1] for b in A], [b[2] for b in A], [b[3] for b in A], [b[4] for b in A], i, ia[-1],
                                       tgt_r=3.0 if tr_ in ("trail", "ema5") else tr_,
                                       trail=sm20 if tr_ == "trail" else em5 if tr_ == "ema5" else None)
                        if ta:
                            ea, ra, ha, xa, xia, fia = ta
                            if tr_ == "ema5":
                                alt["short_ema5"] = short_other(fia, xia, ha)
                            Ra = -1.0 if ha == "SL" else tr_ if ha == "target" else (xa - ea) / ra
                            alt[str(tr_)] = dict(R=round(Ra - COST * ea / ra, 3), pct=round((xa / ea - 1 - COST) * 100, 2), how=ha,
                                                 inv=round(ea * lot) if lot else None, pnl=round((xa - ea - COST * ea) * lot) if lot else None)
                    alt["short_13"] = short_other(fi, j, how)
                    # 25 Nov 2026 (Amritpal: CE trades "gave up most of the gains after triggering" - "test all"): exit variants
                    # on the same fills, 1% cost; the live trader = "ema5" (close below the 5 EMA, stop at the signal low)
                    OA, HA, LA, CA = [b[1] for b in A], [b[2] for b in A], [b[3] for b in A], [b[4] for b in A]
                    for mode in ("x_be1", "x_half15", "x_prevlow", "x_be1_prevlow", "x_ema3", "x_atr2", "x_t15_be"):
                        xr = exit_sim(OA, HA, LA, CA, i, ia[-1], mode, em3=em3, em5=em5, atr=atr14)
                        if xr:
                            ea, ra, ha, xa = xr
                            Ra = (xa - ea) / ra
                            alt[mode] = dict(R=round(Ra - COST * ea / ra, 3), pct=round((xa / ea - 1 - COST) * 100, 2), how=ha,
                                             inv=round(ea * lot) if lot else None, pnl=round((xa - ea - COST * ea) * lot) if lot else None)
                    out.append(dict(s=sym, d=d, t=x[0][11:16], et=A[fi][0][11:16], alt=alt, xt=A[j][0][11:16], real=real, vol_lots=round(x[5] / lot, 1) if lot else None, bb=bool(bbu[i] is not None and x[4] > bbu[i]), side=side, e=e, risk_pct=round(risk / e * 100, 1), how=how,
                                    R=round(R - COST * e / risk, 3), pct=round((exitp / e - 1 - COST) * 100, 2),
                                    inv=round(e * lot) if lot else None, pnl=round((exitp - e - COST * e) * lot) if lot else None,
                                    nf=None if nfp is None else round(nfp, 2), bn=None if bnp is None else round(bnp, 2), idx=kind == "index"))
        # 18 Nov 2026 (Amritpal's chart): TREND version - RSI(14) crosses above 60 with the close above a RISING 20-bar SMA;
        # buy at the next candle's open, hold (overnight too) until a candle CLOSES below the 20 SMA -> sell at that close.
        # On 5- and 15-minute bars of the day's ATM CE/PE; a position stays in its contract until 2 days before expiry.
        for tf in (5, 15):
            for (ex, k_), _ in [((e_, kk), None) for e_, kk in set(plan.values())]:
                for side in ("CE", "PE"):
                    S = series.get((ex, k_, side))
                    if not S:
                        continue
                    B = S if tf == 5 else resample(S, tf)
                    c = [b[4] for b in B]; rs = rsi_series(c); sm = sma(c, 20); n = len(B); i = 21; stop_day = str(ex - timedelta(days=2))
                    while i < n - 1:
                        b = B[i]; d = b[0][:10]
                        ok = plan.get(d) == (ex, k_) and b[0][11:16] < "15:00" and rs[i] is not None and rs[i - 1] is not None \
                            and rs[i] > 60 >= rs[i - 1] and sm[i] is not None and sm[i - 1] is not None and c[i] > sm[i] and sm[i] > sm[i - 1]
                        if not ok:
                            i += 1; continue
                        e = B[i + 1][1]; j = i + 1
                        while j < n - 1 and not (c[j] < sm[j]) and B[j][0][:10] < stop_day:
                            j += 1
                        xp = c[j]
                        nf = ib["NIFTY"].get(b[0][:16]) if tf == 5 else None
                        nfp = bnp = None
                        try:
                            tt = b[0][:16]; nfv = ib["NIFTY"].get(tt); bnv = ib["BANKNIFTY"].get(tt)
                            nfp = (nfv / ipc["NIFTY"][d] - 1) * 100 if nfv and d in ipc["NIFTY"] else None
                            bnp = (bnv / ipc["BANKNIFTY"][d] - 1) * 100 if bnv and d in ipc["BANKNIFTY"] else None
                        except Exception:  # noqa: BLE001
                            pass
                        if e > 0:
                            self.trail.append(dict(s=sym, tf=tf, side=side, d=d, t=b[0][11:16], xd=B[j][0][:10], xt=B[j][0][11:16], bars=j - i,
                                                   e=e, x=xp, pct=round((xp / e - 1 - COST) * 100, 2), nf=nfp, bn=bnp, idx=kind == "index",
                                                   inv=round(e * lot) if lot else None, pnl=round((xp - e - COST * e) * lot) if lot else None))
                        i = j + 1
        return out


LIMIT = 0.01           # stop-limit: pay at most 1% above the trigger
TRIG_BARS = 3          # the buy-stop above the signal candle's high stays for the next 3 candles (15 minutes)


def entry_sim(o, h, l, c, i, last, limit=None, tgt_r=3.0, trail=None):
    """18 Nov 2026 (Amritpal: "entry when the high of the signal candle is breached, or low"): after the signal candle i, a
    buy-stop just above its high; filled at max(high, that bar's open) on the first of the next TRIG_BARS candles to trade above it,
    cancelled if a candle breaks the signal low first (or touches both: no fill). Stop = the signal candle's low (at least 3% under
    the entry), target = entry + 3 x risk; stop first if both in one bar; else out at bar `last`'s close.
    limit (18 Nov 2026, "limit orders, spreads"): a buy STOP-LIMIT - the order may pay at most high x (1 + limit); a candle that
    opens above that fills only if it trades back down to the limit (filled at the limit), otherwise no fill on that candle.
    Returns (entry, risk, how, exit price, exit index, fill index) or None (no fill)."""
    hi, lo = h[i], l[i]; e = f = None
    for k in range(i + 1, min(last, i + TRIG_BARS) + 1):
        if l[k] < lo:
            return None
        if h[k] > hi:
            e = max(hi, o[k])
            if limit is not None and e > hi * (1 + limit):
                cap = hi * (1 + limit)
                if l[k] <= cap:
                    e = cap
                else:
                    e = None                         # gapped through the limit: not filled on this candle
                    continue
            f = k; break
    if e is None or e <= 0:
        return None
    risk = max(e - lo, e * 0.03); sl, tg = e - risk, e + tgt_r * risk
    if trail is not None:                                # 18 Nov 2026: no target - stop at the signal low, else out on a close below the 20 SMA
        for k in range(f, last + 1):
            if l[k] <= sl:
                return e, risk, "SL", sl, k, f
            if k > f and trail[k] is not None and c[k] < trail[k]:
                return e, risk, "trail", c[k], k, f
        return e, risk, "close", c[last], last, f
    if l[f] <= sl:                                       # the fill bar itself (after the fill) touched the stop
        return e, risk, "SL", sl, f, f
    if c[f] >= tg:
        return e, risk, "target", tg, f, f
    for k in range(f + 1, last + 1):
        if l[k] <= sl:
            return e, risk, "SL", sl, k, f
        if h[k] >= tg:
            return e, risk, "target", tg, k, f
    return e, risk, "close", c[last], last, f


def quad_hist():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "research", "nse_quad_daily.json")
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {}


def quad_rows(F, paper):
    """21 Nov 2026 (Amritpal: "and what about leading and lagging sectors"): rotation slices. agrees = CE in a Leading / Improving
    industry, PE in a Lagging / Weakening one; against = the opposite. L Leading, I Improving, W Weakening, G Lagging."""
    up, dn = ("L", "I"), ("G", "W")
    out = {}
    for nm, X in (("basket 1:3", F), ("paper-trader rules", paper)):
        out[f"{nm} + rotation agrees (CE Leading/Improving, PE Lagging/Weakening)"] = _agg([t for t in X if (t["side"] == "CE" and t.get("quad") in up) or (t["side"] == "PE" and t.get("quad") in dn)])
        out[f"{nm} + rotation AGAINST"] = _agg([t for t in X if (t["side"] == "CE" and t.get("quad") in dn) or (t["side"] == "PE" and t.get("quad") in up)])
        for side in ("CE", "PE"):
            for q, qn in (("L", "Leading"), ("I", "Improving"), ("W", "Weakening"), ("G", "Lagging")):
                out[f"{nm}, {side} in {qn}"] = _agg([t for t in X if t["side"] == side and t.get("quad") == q])
        out[f"{nm}, no industry (indices / unmapped)"] = _agg([t for t in X if t.get("quad") is None])
    return out


def pulse_hist():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "research", "nse_pulse_daily.json")
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {}


def pulse_rows(F, paper):
    """20 Nov 2026: Pulse slices. agrees = CE on a strong-Pulse stock (top 25% of industries) / PE on a weak one (bottom 25%);
    'leans' = CE above the middle / PE below it; against = the opposite. Indices have no Pulse and are shown apart."""
    ag = lambda t, lo, hi: t.get("pulse") is not None and ((t["side"] == "CE" and t["pulse"] >= hi) or (t["side"] == "PE" and t["pulse"] <= lo))  # noqa: E731
    out = {}
    for nm, X in (("basket 1:3", F), ("paper-trader rules", paper)):
        out[f"{nm} + Pulse agrees (CE top 25%, PE bottom 25%)"] = _agg([t for t in X if ag(t, 0.25, 0.75)])
        out[f"{nm} + Pulse leans the right way (CE top half, PE bottom half)"] = _agg([t for t in X if ag(t, 0.5, 0.5)])
        out[f"{nm} + Pulse AGAINST (CE bottom half, PE top half)"] = _agg([t for t in X if t.get("pulse") is not None and not ag(t, 0.5, 0.5)])
        out[f"{nm}, stocks without Pulse (indices / unmapped)"] = _agg([t for t in X if t.get("pulse") is None])
        out[f"{nm}, PE + Pulse bottom half"] = _agg([t for t in X if t["side"] == "PE" and t.get("pulse") is not None and t["pulse"] <= 0.5])
        out[f"{nm}, PE + Pulse top half"] = _agg([t for t in X if t["side"] == "PE" and t.get("pulse") is not None and t["pulse"] > 0.5])
        out[f"{nm}, CE + Pulse top half"] = _agg([t for t in X if t["side"] == "CE" and t.get("pulse") is not None and t["pulse"] >= 0.5])
        out[f"{nm}, CE + Pulse bottom half"] = _agg([t for t in X if t["side"] == "CE" and t.get("pulse") is not None and t["pulse"] < 0.5])
    return out


def sector_rows(F, paper):
    """23 Nov 2026 (Amritpal: green sectors on a green Nifty / Bank Nifty, option-trader rules after the first 5 minutes): the index
    filter is already in F (CE only while Nifty AND Bank Nifty are up). Slices by the stock's sector move at the signal bar (average
    day % of its other F&O stocks, from put-call parity): agrees = CE with the sector up / PE with it down; strong = by more than 0.5%;
    and by signal time (first 30 minutes vs later)."""
    out = {}
    for nm, X in (("Basket 1:3", F), ("Paper-trader rules", paper)):
        has = [t for t in X if t.get("sec") is not None]
        ag = lambda t, m=0.0: (t["side"] == "CE" and t["sec"] > m) or (t["side"] == "PE" and t["sec"] < -m)  # noqa: E731
        out[f"{nm}, all"] = _agg(X)
        out[f"{nm} + sector agrees (CE sector green, PE sector red)"] = _agg([t for t in has if ag(t)])
        out[f"{nm} + sector agrees strongly (> 0.5%)"] = _agg([t for t in has if ag(t, 0.5)])
        out[f"{nm} + sector AGAINST"] = _agg([t for t in has if not ag(t)])
        out[f"{nm}, CE + sector green"] = _agg([t for t in has if t["side"] == "CE" and t["sec"] > 0])
        out[f"{nm}, CE + sector red"] = _agg([t for t in has if t["side"] == "CE" and t["sec"] <= 0])
        out[f"{nm}, no sector (indices / unmapped)"] = _agg([t for t in X if t.get("sec") is None])
        out[f"{nm}, signal 09:20-09:45"] = _agg([t for t in X if t["t"] <= "09:45"])
        out[f"{nm}, signal after 09:45"] = _agg([t for t in X if t["t"] > "09:45"])
        out[f"{nm} + sector agrees, signal 09:20-09:45"] = _agg([t for t in has if ag(t) and t["t"] <= "09:45"])
    for v in out.values():
        v.pop("by_day", None); v.pop("by_day_rs", None)
    return out


def sector_map():
    """symbol -> sector (Nifty 500 industry; Financial Services split into Banks and other financials)."""
    import csv
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "universe")
    ind = {}
    try:
        for r in csv.DictReader(open(os.path.join(base, "nse_industry.csv"))):
            ind[r["symbol"]] = r.get("industry") or ""
    except Exception:  # noqa: BLE001
        pass
    out = {}
    for r in csv.DictReader(open(os.path.join(base, "nifty500.csv"))):
        g = r["Industry"]
        if g == "Financial Services":
            g = "Banks" if "bank" in ind.get(r["Symbol"], "").lower() else "Financials (non-bank)"
        out[r["Symbol"]] = g
    return out


def exit_sim(o, h, l, c, i, last, mode, em3=None, em5=None, atr=None):
    """25 Nov 2026: the paper trader's entry (buy-stop above the signal high, stop at the signal low >= 3%), other exits:
      x_be1        5-EMA close exit; stop to the entry once the high reaches +1R
      x_half15     half off at +1.5R, the rest on the 5-EMA close exit with the stop at the entry (blended exit price)
      x_prevlow    stop trails under the previous 5-min candle's low (from the candle after the fill)
      x_be1_prevlow  breakeven at +1R, then the previous-candle-low trail
      x_ema3       close below the 3 EMA instead of the 5 EMA
      x_atr2       stop trails 2 x ATR(14, 5-min) under the highest high since the fill
      x_t15_be     fixed target +1.5R, stop to the entry at +1R
    Same-bar order: the stop first. Out at bar `last` (15:15) otherwise. Returns (entry, risk, how, blended exit price) or None."""
    base = entry_sim(o, h, l, c, i, last, trail=em5)
    if base is None:
        return None
    e, risk, _, _, _, f = base
    sl = e - risk; hi = h[f]; half = None
    if l[f] <= sl:
        return e, risk, "SL", sl
    for k in range(f + 1, last + 1):
        st = sl
        if mode in ("x_be1", "x_be1_prevlow", "x_t15_be") and hi >= e + risk:
            st = max(st, e)
        if mode == "x_half15" and half is not None:
            st = max(st, e)
        if mode in ("x_prevlow", "x_be1_prevlow"):
            st = max(st, l[k - 1]) if (mode == "x_prevlow" or hi >= e + risk) else st
        if mode == "x_atr2" and atr is not None:
            st = max(st, hi - 2 * atr[k - 1])
        if l[k] <= st:
            px = min(o[k], st) if o[k] < st else st
            return (e, risk, "stop", (half + px) / 2) if half is not None else (e, risk, "SL" if st <= sl else "stop", px)
        if mode == "x_half15" and half is None and h[k] >= e + 1.5 * risk:
            half = e + 1.5 * risk
        if mode == "x_t15_be" and h[k] >= e + 1.5 * risk:
            return e, risk, "target", e + 1.5 * risk
        trail = em3 if mode == "x_ema3" else em5 if mode in ("x_be1", "x_half15") else None
        if trail is not None and trail[k] is not None and c[k] < trail[k]:
            return (e, risk, "trail", (half + c[k]) / 2) if half is not None else (e, risk, "trail", c[k])
        hi = max(hi, h[k])
    return (e, risk, "close", (half + c[last]) / 2) if half is not None else (e, risk, "close", c[last])


def _agg(T):
    if not T:
        return dict(n=0)
    R = [t["R"] for t in T]; P = [t["pct"] for t in T]
    days = {}
    for t in T:
        days[t["d"]] = days.get(t["d"], 0) + t["R"]
    eq = pk = dd = 0.0
    for d in sorted(days):
        eq += days[d]; pk = max(pk, eq); dd = min(dd, eq - pk)
    # 18 Nov 2026 (Amritpal: "money freed by stops is reused"): the money actually needed = the most tied up at any moment of a day
    # (1 lot each; a trade holds its cost from its entry candle to its exit candle)
    money = {}
    if all(t.get("inv") is not None and t.get("et") and t.get("xt") for t in T):
        byd = {}
        for t in T:
            byd.setdefault(t["d"], []).append(t)
        peaks, dp = [], []
        for d, L in byd.items():
            ev = sorted([(t["xt"], 0, -t["inv"]) for t in L] + [(t["et"], 1, t["inv"]) for t in L])
            cur = pk_ = 0.0
            for _, _, v in ev:
                cur += v; pk_ = max(pk_, cur)
            peaks.append(pk_); dp.append(sum(t["pnl"] for t in L) / pk_ * 100 if pk_ else 0)
        pnl = sum(t["pnl"] for t in T)
        money = dict(pnl_rs=round(pnl), sum_inv_rs=round(sum(t["inv"] for t in T)), peak_money_rs=round(max(peaks)),
                     avg_day_peak_rs=round(sum(peaks) / len(peaks)), avg_day_return_on_peak_pct=round(sum(dp) / len(dp), 2),
                     total_return_on_max_peak_pct=round(pnl / max(peaks) * 100, 1) if max(peaks) else None)
    return dict(**money, n=len(T), total_R=round(sum(R), 1), avg_R=round(sum(R) / len(R), 3), win=round(sum(r > 0 for r in R) / len(R) * 100, 1),
                target=sum(t["how"] == "target" for t in T), sl=sum(t["how"] == "SL" for t in T), at_close=sum(t["how"] in ("close", "open") for t in T),
                trailed=sum(t["how"] == "trail" for t in T),
                avg_pct=round(sum(P) / len(P), 2), days=len(days), up_days=sum(v > 0 for v in days.values()), worst_dd_R=round(dd, 1),
                by_day={d: round(v, 1) for d, v in sorted(days.items())},
                by_day_rs={d: round(sum(t["pnl"] for t in T if t["d"] == d)) for d in sorted(days)} if all(t.get("pnl") is not None for t in T) else None)


def trail_summary(T):
    """SMA-20 trail version: % per trade (equal money), by timeframe, with / without the Nifty + Bank Nifty filter."""
    def agg(L):
        if not L:
            return dict(n=0)
        P = [t["pct"] for t in L]; bars = sorted(t["bars"] for t in L)
        days = {}
        for t in L:
            days[t["d"]] = days.get(t["d"], 0) + t["pct"]
        o_ = dict(n=len(L), avg_pct=round(sum(P) / len(P), 2), win=round(sum(p > 0 for p in P) / len(P) * 100, 1), best=round(max(P), 1),
                  worst=round(min(P), 1), median_bars_held=bars[len(bars) // 2], overnight=sum(t["xd"] != t["d"] for t in L),
                  days=len(days), up_days=sum(v > 0 for v in days.values()))
        if all(t.get("pnl") is not None for t in L):
            o_["pnl_rs_1lot"] = round(sum(t["pnl"] for t in L))
        return o_
    up = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] > 0 and t["bn"] > 0      # noqa: E731
    dn = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] < 0 and t["bn"] < 0      # noqa: E731
    out = {}
    for tf in (5, 15):
        L = [t for t in T if t["tf"] == tf]; F = [t for t in L if (t["side"] == "CE" and up(t)) or (t["side"] == "PE" and dn(t))]
        out[f"{tf}m all"] = agg(L); out[f"{tf}m index filter"] = agg(F)
        out[f"{tf}m index filter, no entries 11:00-14:30"] = agg([t for t in F if not ("11:00" <= t["t"] < "14:30")])
    return out


WIN = [("09:15-11:15", "09:15", "11:15"), ("11:15-13:15", "11:15", "13:15"), ("13:15-15:30", "13:15", "15:31")]


def one_at_a_time(T):
    out, busy = [], {}
    for t in sorted(T, key=lambda x: (x["d"], x.get("et") or x["t"], x["s"])):
        if (t.get("et") or t["t"]) < busy.get(t["d"], "00:00"):
            continue
        out.append(t); busy[t["d"]] = (t.get("xt") or "15:30") if t["how"] != "SL" or t.get("xt") else "15:30"
        if busy[t["d"]] <= (t.get("et") or t["t"]):
            busy[t["d"]] = (t.get("et") or t["t"]) + "~"          # exit in the entry candle: the next trade starts from the next candle
    return out


def money_agg(T):
    """rupee view for the option-SELLING variants: profit, win rate, most margin tied up at once, return on it."""
    if not T:
        return dict(n=0)
    P = [t["pnl"] for t in T]; days = {}
    for t in T:
        days[t["d"]] = days.get(t["d"], 0) + t["pnl"]
    byd = {}
    for t in T:
        byd.setdefault(t["d"], []).append(t)
    peaks = []
    for L in byd.values():
        ev = sorted([(t["xt"], 0, -t["inv"]) for t in L] + [(t["et"], 1, t["inv"]) for t in L]); cur = pk = 0.0
        for _, _, v in ev:
            cur += v; pk = max(pk, cur)
        peaks.append(pk)
    eq = pk = dd = 0.0
    for d in sorted(days):
        eq += days[d]; pk = max(pk, eq); dd = min(dd, eq - pk)
    return dict(n=len(T), pnl_rs=round(sum(P)), win=round(sum(p > 0 for p in P) / len(P) * 100, 1), avg_rs=round(sum(P) / len(P)),
                worst_trade_rs=round(min(P)), peak_margin_rs=round(max(peaks)), return_on_peak_pct=round(sum(P) / max(peaks) * 100, 1) if max(peaks) else None,
                worst_run_rs=round(dd), days=len(days), up_days=sum(v > 0 for v in days.values()), stopped=sum(t["how"] == "SL" for t in T),
                by_day_rs={d: round(v) for d, v in sorted(days.items())})


def nifty_weekly(M, W):
    up = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] > 0 and t["bn"] > 0      # noqa: E731
    dn = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] < 0 and t["bn"] < 0      # noqa: E731
    out = {}
    for nm, T in (("monthly", M), ("weekly", W)):
        F = [t for t in T if (t["side"] == "CE" and up(t)) or (t["side"] == "PE" and dn(t))]
        nl = [t for t in F if not ("11:00" <= t.get("et", t["t"]) < "14:30")]
        out[f"{nm}: basket 1:3"] = _agg(F)
        out[f"{nm}: 5 EMA trail, no 11:00-14:30"] = _agg([dict(t, **t["alt"]["ema5"]) for t in nl if (t.get("alt") or {}).get("ema5")])
        out[f"{nm}: paper-trader rules (+ PCR + BB)"] = _agg([dict(t, **t["alt"]["ema5"]) for t in nl if (t.get("alt") or {}).get("ema5") and t.get("bb")
                                                             and t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))])
        out[f"{nm}: median premium"] = sorted(t["e"] for t in F)[len(F) // 2] if F else None
    return out


def summarise(T):
    up = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] > 0 and t["bn"] > 0      # noqa: E731
    dn = lambda t: t["nf"] is not None and t["bn"] is not None and t["nf"] < 0 and t["bn"] < 0      # noqa: E731
    F = [t for t in T if (t["side"] == "CE" and up(t)) or (t["side"] == "PE" and dn(t))]
    return {"all signals": _agg(T), "all CE": _agg([t for t in T if t["side"] == "CE"]), "all PE": _agg([t for t in T if t["side"] == "PE"]),
            "index filter (basket)": _agg(F), "filter CE": _agg([t for t in F if t["side"] == "CE"]), "filter PE": _agg([t for t in F if t["side"] == "PE"]),
            "filter, indices only": _agg([t for t in F if t["idx"]]), "filter, before 10:00": _agg([t for t in F if t["t"] < "10:00"]),
            "filter, 10:00 and later": _agg([t for t in F if t["t"] >= "10:00"]),
            # PCR as a guide (high PCR = bullish in the 2020-26 daily test): agrees = CE with q 4-5 / PE with q 1-2
            "filter + PCR agrees": _agg([t for t in F if t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))]),
            "filter + PCR neutral (q3)": _agg([t for t in F if t.get("pcrq") == 3]),
            "filter + PCR disagrees": _agg([t for t in F if t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] <= 2) or (t["side"] == "PE" and t["pcrq"] >= 4))]),
            # 18 Nov 2026: sector as a further filter - the stock's sector (other F&O members, put-call parity) up for CE / down for PE
            "filter + sector agrees": _agg([t for t in F if t.get("sec") is not None and ((t["side"] == "CE" and t["sec"] > 0) or (t["side"] == "PE" and t["sec"] < 0))]),
            "filter + sector disagrees": _agg([t for t in F if t.get("sec") is not None and ((t["side"] == "CE" and t["sec"] < 0) or (t["side"] == "PE" and t["sec"] > 0))]),
            "filter + sector unknown (index / small sector)": _agg([t for t in F if t.get("sec") is None]),
            "no index filter, sector agrees": _agg([t for t in T if t.get("sec") is not None and ((t["side"] == "CE" and t["sec"] > 0) or (t["side"] == "PE" and t["sec"] < 0))]),
            # 18 Nov 2026: the signal candle must also CLOSE above the upper Bollinger band (20, 2) of the option
            "basket + BB close": _agg([t for t in F if t.get("bb")]),
            "basket, no BB close": _agg([t for t in F if not t.get("bb")]),
            "basket + BB + sector agrees": _agg([t for t in F if t.get("bb") and t.get("sec") is not None and ((t["side"] == "CE" and t["sec"] > 0) or (t["side"] == "PE" and t["sec"] < 0))]),
            # 18 Nov 2026: realistic fills - buy stop-LIMIT (max 1% above the trigger, no chasing a gap) and only options whose
            # signal candle traded >= 20 lots (thin strikes have wide spreads)
            "basket, realistic fills": _agg([dict(t, **t["real"]) for t in F if t.get("real")]),
            "basket + BB, realistic fills": _agg([dict(t, **t["real"]) for t in F if t.get("real") and t.get("bb")]),
            # 18 Nov 2026: when do the stops hit? basket trades by 2-hour window of ENTRY, and stop hits by 2-hour window of the HIT
            "basket by entry window": {w: _agg([t for t in F if lo_ <= t.get("et", t["t"]) < hi_]) for w, lo_, hi_ in WIN},
            # Amritpal: "markets are quiet 11:00-14:30" - skip entries in that window
            "basket, no entries 11:00-14:30": _agg([t for t in F if not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            "basket, only entries 11:00-14:30": _agg([t for t in F if "11:00" <= t.get("et", t["t"]) < "14:30"]),
            "basket, realistic fills, no entries 11:00-14:30": _agg([dict(t, **t["real"]) for t in F if t.get("real") and not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            "basket, target 1.5R": _agg([dict(t, **t["alt"]["1.5"]) for t in F if (t.get("alt") or {}).get("1.5")]),
            "basket, target 2R": _agg([dict(t, **t["alt"]["2.0"]) for t in F if (t.get("alt") or {}).get("2.0")]),
            "basket, target 2R, no entries 11:00-14:30": _agg([dict(t, **t["alt"]["2.0"]) for t in F if (t.get("alt") or {}).get("2.0") and not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            "basket, trail (stop at signal low, out on a close below the 20 SMA)": _agg([dict(t, **t["alt"]["trail"]) for t in F if (t.get("alt") or {}).get("trail")]),
            "basket, trail, no entries 11:00-14:30": _agg([dict(t, **t["alt"]["trail"]) for t in F if (t.get("alt") or {}).get("trail") and not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            "basket, trail on the 5 EMA (out on a close below it)": _agg([dict(t, **t["alt"]["ema5"]) for t in F if (t.get("alt") or {}).get("ema5")]),
            "basket, trail 5 EMA, no entries 11:00-14:30": _agg([dict(t, **t["alt"]["ema5"]) for t in F if (t.get("alt") or {}).get("ema5") and not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            # 18 Nov 2026 (Amritpal: "one trade at a time, then the next"): take the first basket trade that triggers; nothing new until
            # it is closed (stop / target / trail / day end); then the next signal that triggers after that exit
            "one at a time, 1:3": _agg(one_at_a_time(F)),
            "one at a time, 1:2": _agg(one_at_a_time([dict(t, **t["alt"]["2.0"]) for t in F if (t.get("alt") or {}).get("2.0")])),
            "one at a time, 5 EMA trail": _agg(one_at_a_time([dict(t, **t["alt"]["ema5"]) for t in F if (t.get("alt") or {}).get("ema5")])),
            "one at a time, 1:3, indices only": _agg(one_at_a_time([t for t in F if t["idx"]])),
            "basket stop hits by window": {w: sum(1 for t in F if t["how"] == "SL" and lo_ <= t.get("xt", "") < hi_) for w, lo_, hi_ in WIN},
            # 18 Nov 2026: SELL the opposite option instead of buying (CE signal -> sell the PE, PE signal -> sell the CE)
            "SELL opposite, basket, 1:3 exits": money_agg([dict(t, **t["alt"]["short_13"]) for t in F if (t.get("alt") or {}).get("short_13")]),
            "SELL opposite, basket, 5 EMA exits": money_agg([dict(t, **t["alt"]["short_ema5"]) for t in F if (t.get("alt") or {}).get("short_ema5")]),
            "SELL opposite, 5 EMA exits, no entries 11:00-14:30": money_agg([dict(t, **t["alt"]["short_ema5"]) for t in F if (t.get("alt") or {}).get("short_ema5") and not ("11:00" <= t.get("et", t["t"]) < "14:30")]),
            "SELL opposite, 5 EMA exits, no lull + PCR + BB": money_agg([dict(t, **t["alt"]["short_ema5"]) for t in F if (t.get("alt") or {}).get("short_ema5") and not ("11:00" <= t.get("et", t["t"]) < "14:30") and t.get("bb") and t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))]),
            **{f"PAPER TRADER rules, exit {nm_}": _agg([dict(t, **t["alt"][m_]) for t in F if (t.get("alt") or {}).get(m_) and not ("11:00" <= t.get("et", t["t"]) < "14:30") and t.get("bb") and t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))])
               for m_, nm_ in (("ema5", "5 EMA close (live)"), ("x_be1", "5 EMA + breakeven at 1R"), ("x_half15", "half at 1.5R + 5 EMA"),
                               ("x_prevlow", "previous candle low trail"), ("x_be1_prevlow", "breakeven 1R then prev-low trail"),
                               ("x_ema3", "3 EMA close"), ("x_atr2", "2 ATR trail"), ("x_t15_be", "target 1.5R, breakeven at 1R"), ("1.5", "target 1.5R"), ("2.0", "target 2R"))},
            "BUY, 5 EMA exits, no lull + PCR + BB (the paper trader)": _agg([dict(t, **t["alt"]["ema5"]) for t in F if (t.get("alt") or {}).get("ema5") and not ("11:00" <= t.get("et", t["t"]) < "14:30") and t.get("bb") and t.get("pcrq") and ((t["side"] == "CE" and t["pcrq"] >= 4) or (t["side"] == "PE" and t["pcrq"] <= 2))]),
            "all signals by PCR quintile": {f"{side} q{q}": _agg([t for t in T if t["side"] == side and t.get("pcrq") == q]) for side in ("CE", "PE") for q in range(1, 6)}}
