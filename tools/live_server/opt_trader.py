"""5-minute ATM option trader - PAPER always, LIVE only when switched on in the app (18 Nov 2026, Amritpal: "create a provision for
paper trade and also live trade in the app"; his choices: 5 EMA trail + PCR + BB, 1 lot, max 3 open, indices + top 30 liquid).

Rules (claude/option-rsi60-basket-test.md, best version):
  universe : NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY + the 30 stocks with the most ATM option contracts traded (nightly optscan.json);
             their ATM CE and PE of the chosen monthly expiry (68 contracts), 5-minute candles from Angel every 5 minutes.
  signal   : on a COMPLETED 5-minute candle of an option - RSI(14) crosses above 60, the candle closes above its upper Bollinger band
             (20, 2), the option is above its session VWAP and the other option is below its own; CE only while Nifty AND Bank Nifty
             are both up on the day (put-call parity of their ATM options), PE only while both are down; the stock's PCR fifth
             (previous evening) agrees: CE needs 4-5, PE needs 1-2; not 11:00-14:30, not after 15:00.
  entry    : buy STOP-LIMIT just above the signal candle's high (limit 1% above the trigger), valid for the next 3 candles;
             cancelled if a candle breaks the signal low first.
  stop     : the signal candle's low (at least 3% under the entry) - a stop-limit sell is placed on Angel right after the fill.
  exit     : a completed 5-minute close below the 5 EMA, or 15:15 - limit sell 2% under the last price (re-priced if unfilled).
  limits   : 1 lot, at most 3 positions open (pending buys count), stop for the day after -Rs 10,000 (paper P&L), "Stop today" button.
Paper and live share one book: every trade is simulated on the candles (paper result); when LIVE is on the same trade is also sent
to Angel and its real fills are recorded beside the paper prices. Live is off by default; switching it on needs the app password."""
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
CFG = dict(max_open=3, lots=1, day_loss=10000.0, lull=("11:00", "14:30"), last_entry="15:00", eod="15:15", trig_bars=3,
           limit_pct=0.01, top=30, tick=0.05)
BUSY = threading.Event()           # set while a cycle is fetching candles: the slower 15-minute scan waits


def now_ist():
    return datetime.now(IST)


def ema(c, n):
    out, k, e = [], 2 / (n + 1), None
    for v in c:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out


def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l_ = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]; g += max(d, 0); l_ += max(-d, 0)
    g /= n; l_ /= n; out[n] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]; g = (g * (n - 1) + max(d, 0)) / n; l_ = (l_ * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    return out


def bb_upper(c, n=20, k=2.0):
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]; m = sum(w) / n
        out[i] = m + k * (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return out


def rnd(v, tick=0.05, up=False):
    import math
    n = v / tick
    return round((math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)) * tick, 2)


class OptTrader:
    def __init__(self, broker, data_dir, rows_fn, pcr_fn, log=lambda ev, **kw: print(ev, kw)):
        self.b, self.rows_fn, self.pcr_fn, self.log = broker, rows_fn, pcr_fn, log
        self.dir = data_dir
        self.sp = os.path.join(data_dir, "opt_trader.json"); self.mp = os.path.join(data_dir, "opt_trader_mode.json")
        self.hp = os.path.join(data_dir, "opt_trader_hist.jsonl")
        self.st = self._load()
        self.uni = None; self.uni_day = None; self.pcr = {}
        self.lock = threading.Lock(); self.thread = None; self.last_cycle = None; self.last_error = None
        self.stage = "waiting for 09:25"; self.stage_at = None; self.fast = None

    # ------------------------------------------------------------------ state
    def _load(self):
        try:
            st = json.load(open(self.sp))
            if st.get("day") == str(now_ist().date()):
                return st
        except Exception:  # noqa: BLE001
            pass
        return dict(day=str(now_ist().date()), trades=[], stopped=False, notes=[])

    def _save(self):
        tmp = self.sp + ".tmp"; json.dump(self.st, open(tmp, "w")); os.replace(tmp, self.sp)

    def live(self):
        try:
            return bool(json.load(open(self.mp)).get("live"))
        except Exception:  # noqa: BLE001
            return False

    def set_live(self, on):
        json.dump(dict(live=bool(on), at=time.time()), open(self.mp, "w"))

    def note(self, txt):
        self.st.setdefault("notes", []).append(f"{now_ist():%H:%M} {txt}"); self.st["notes"] = self.st["notes"][-40:]
        self.log("opt_trader", note=txt)

    # ------------------------------------------------------------------ universe
    def universe(self):
        d = str(now_ist().date())
        if self.uni is not None and self.uni_day == d:
            return self.uni
        self._stage("building today's contract list")
        rows = self.rows_fn() or []
        idx = [r for r in rows if r.get("kind") == "index"]
        stk = sorted([r for r in rows if r.get("kind") != "index"], key=lambda r: -(r.get("atm_vol5") or 0))[:CFG["top"]]
        uni = []
        for r in idx + stk:
            try:
                ex = date.fromisoformat(r["expiry"])
                ce = self.b.opt_token(r["symbol"], ex, r["strike"], "CE"); pe = self.b.opt_token(r["symbol"], ex, r["strike"], "PE")
            except Exception:  # noqa: BLE001
                ce = pe = None
            if ce and pe:
                uni.append(dict(symbol=r["symbol"], kind=r.get("kind"), strike=r["strike"], expiry=r["expiry"], lot=r.get("lot") or 1,
                                ce=dict(token=ce[0], tsym=ce[1]), pe=dict(token=pe[0], tsym=pe[1])))
        try:
            self.pcr = {k: v.get("q") for k, v in ((self.pcr_fn() or {}).get("rows") or {}).items()}
        except Exception:  # noqa: BLE001
            self.pcr = {}
        self.uni, self.uni_day = uni, d
        self.note(f"contract list ready: {len(uni)} underlyings ({len(idx)} indices + {len(stk)} stocks), PCR for {len(self.pcr)}")
        return uni

    # ------------------------------------------------------------------ loop
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True); self.thread.start()
        self.fast = threading.Thread(target=self._fast_loop, daemon=True); self.fast.start()

    def _stage(self, txt):
        self.stage = txt; self.stage_at = now_ist().strftime("%H:%M:%S")

    def _fast_loop(self):
        """19 Nov 2026 (Amritpal: a 5-minute delay before the stop is a risk): while a live buy is waiting on Angel, look at the order
        book every 10 seconds and put the stop-loss on Angel as soon as the buy fills."""
        while True:
            time.sleep(10)
            t0 = now_ist()
            if t0.weekday() >= 5 or not ((9, 15) <= (t0.hour, t0.minute) <= (15, 31)):
                continue
            try:
                self.watch_fills()
            except Exception as ex:  # noqa: BLE001
                self.log("opt_trader_fast", error=str(ex)[:160])

    def watch_fills(self):
        want = [t for t in self.st.get("trades", []) if t.get("oid") and t.get("live_entry") is None and t["state"] in ("pending", "open")]
        if not want:
            return
        om = self.b.order_map()
        if not self.lock.acquire(timeout=8):
            return
        try:
            for t in self.st.get("trades", []):
                if t.get("oid") and t.get("live_entry") is None and t["state"] in ("pending", "open"):
                    o = om.get(t["oid"]) or {}
                    if str(o.get("status", "")).lower() == "complete":
                        self._live_filled(t, o)
            self._save()
        finally:
            self.lock.release()

    def _live_filled(self, t, o):
        """Angel filled the live buy: record it and place the stop-limit sell right away (trigger = the trade's stop, limit 5% below)."""
        e = float(o.get("avg") or t.get("entry") or t["trigger"])
        stop = t.get("stop") or rnd(e - max(e - t["sig_low"], e * 0.03))
        t["live_entry"] = e; t["live_state"] = "bought on Angel"; t["live_fill_at"] = now_ist().strftime("%H:%M:%S")
        try:
            t["live_stop_oid"] = self.b.nfo_order(t["tsym"], t["token"], "SELL", t["lot"], rnd(stop * 0.95), trigger=stop)
            t["live_stop"] = stop; t["live_state"] = "bought · stop on Angel"
            self.note(f"{t['key']} bought on Angel {e} · stop {stop} placed")
        except Exception as ex:  # noqa: BLE001
            t["live_state"] = f"bought · STOP NOT PLACED - put it in Angel: {str(ex)[:100]}"
            self.note(f"{t['key']} bought on Angel {e} · STOP NOT PLACED: {str(ex)[:80]}")

    def _loop(self):
        while True:
            t = now_ist()
            if t.weekday() < 5 and (9, 20) <= (t.hour, t.minute) <= (15, 31):
                # run 25 s after each 5-minute candle closes
                nxt = (t.replace(second=0, microsecond=0) + timedelta(minutes=5 - t.minute % 5)) + timedelta(seconds=25)
                time.sleep(max(1, (nxt - now_ist()).total_seconds()))
                try:
                    self.cycle()
                except Exception as ex:  # noqa: BLE001
                    self.last_error = f"{now_ist():%H:%M} {str(ex)[:200]}"; self.log("opt_trader_error", error=str(ex)[:200])
            else:
                time.sleep(60)

    def _bars(self, token):
        B = self.b.candles_int("NFO", token, "FIVE_MINUTE", 6)
        cut = now_ist() - timedelta(minutes=5)
        out = []
        for x in B:
            try:
                ts = datetime.fromisoformat(x[0])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=IST)
            except Exception:  # noqa: BLE001
                continue
            if ts <= cut:                                   # completed candles only
                out.append((ts.astimezone(IST).strftime("%Y-%m-%dT%H:%M"), x[1], x[2], x[3], x[4], x[5]))
        return out

    def cycle(self):
        # 19 Nov 2026: candles are fetched OUTSIDE the lock (it takes tens of seconds) so the 10-second fill watcher can place stops meanwhile
        BUSY.set()
        try:
            uni = self.universe(); day = str(now_ist().date())
            bars = {}; N = 2 * len(uni); k = 0
            for u in uni:
                for side in ("ce", "pe"):
                    k += 1; self._stage(f"fetching 5-minute candles {k}/{N}")
                    try:
                        bars[(u["symbol"], side)] = self._bars(u[side]["token"])
                    except Exception as ex:  # noqa: BLE001
                        self.log("opt_trader_fetch", symbol=u["symbol"], error=str(ex)[:120])
        finally:
            BUSY.clear()
        self._stage("checking signals")
        with self.lock:
            if self.st.get("day") != str(now_ist().date()):
                for t in self.st.get("trades", []):
                    if t.get("hist_due"):
                        self._hist(t)
                self.st = dict(day=str(now_ist().date()), trades=[], stopped=False, notes=[])
            idx = {}
            for nm in ("NIFTY", "BANKNIFTY"):
                u = next((x for x in uni if x["symbol"] == nm), None)
                C, P = bars.get((nm, "ce")), bars.get((nm, "pe"))
                if u and C and P:
                    pm = {x[0]: x[4] for x in P}; prev = [x for x in C if x[0][:10] < day and x[0] in pm]
                    if prev:
                        ref = u["strike"] + prev[-1][4] - pm[prev[-1][0]]
                        idx[nm] = {x[0]: (u["strike"] + x[4] - pm[x[0]]) / ref * 100 - 100 for x in C if x[0][:10] == day and x[0] in pm and ref > 0}
            om = None
            if any(t.get("oid") or t.get("live_stop_oid") or t.get("live_exit_oid") for t in self.st["trades"]):
                try:
                    om = self.b.order_map()
                except Exception as ex:  # noqa: BLE001
                    self.note(f"order book unavailable: {ex}")
            for u in uni:
                for side, other in (("ce", "pe"), ("pe", "ce")):
                    A, B = bars.get((u["symbol"], side)), bars.get((u["symbol"], other))
                    if A and B:
                        self._contract(u, side, A, B, idx, day, om)
            # 19 Nov 2026: the live sell of a closed paper trade is checked / re-priced every cycle until Angel fills it
            for t in self.st["trades"]:
                if t["state"] == "closed" and t.get("live_entry") is not None and t.get("live_exit") is None:
                    self._live_exit(t, om)
            first = self.last_cycle is None
            self.last_cycle = now_ist().strftime("%H:%M:%S"); self._stage(f"check done at {self.last_cycle}, next in 5 minutes")
            if first:
                self.note(f"first check done: {sum(1 for v in bars.values() if v)} of {2 * len(uni)} contracts had candles")
            self._save()

    # ------------------------------------------------------------------ one contract
    def _open_count(self):
        return sum(1 for t in self.st["trades"] if t["state"] in ("pending", "open"))

    def day_pnl(self):
        return sum(t.get("pnl") or 0 for t in self.st["trades"] if t["state"] == "closed") + \
            sum(t.get("upnl") or 0 for t in self.st["trades"] if t["state"] == "open")

    def _contract(self, u, side, A, B, idx, day, om):
        key = f"{u['symbol']}|{side.upper()}"; c = [x[4] for x in A]; n = len(A)
        today = [i for i in range(n) if A[i][0][:10] == day]
        if not today:
            return
        last = today[-1]; info = u[side]; lot = u["lot"] * CFG["lots"]
        e5 = ema(c, 5)
        mine = [t for t in self.st["trades"] if t["key"] == key and t["state"] in ("pending", "open")]
        for t in mine:
            self._manage(t, A, e5, last, info, lot, om)
        if mine or self.st.get("stopped"):
            return
        # signal on the newest completed candle only (a cycle sees each candle once)
        i = last; hm = A[i][0][11:16]
        if self.st.get("seen", {}).get(key) == A[i][0]:
            return
        self.st.setdefault("seen", {})[key] = A[i][0]
        if hm >= CFG["last_entry"] or CFG["lull"][0] <= hm < CFG["lull"][1] or i < 1:
            return
        rs = rsi(c); bu = bb_upper(c)
        if rs[i] is None or rs[i - 1] is None or not (rs[i] > 60 >= rs[i - 1]) or bu[i] is None or c[i] <= bu[i]:
            return
        pv = vv = 0.0
        for k in today:
            x = A[k]; pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]
        va = pv / vv if vv else c[i]
        bm = [x for x in B if x[0][:10] == day]; pv = vv = 0.0; ob = None
        for x in bm:
            pv += (x[2] + x[3] + x[4]) / 3 * x[5]; vv += x[5]
            if x[0] == A[i][0]:
                ob = (x[4], pv / vv if vv else x[4])
        if not ob or not (c[i] > va and ob[0] < ob[1]):
            return
        nf, bn = (idx.get("NIFTY") or {}).get(A[i][0]), (idx.get("BANKNIFTY") or {}).get(A[i][0])
        if nf is None or bn is None or not ((side == "ce" and nf > 0 and bn > 0) or (side == "pe" and nf < 0 and bn < 0)):
            return
        q = self.pcr.get(u["symbol"])
        if q is None or not ((side == "ce" and q >= 4) or (side == "pe" and q <= 2)):
            return
        if self._open_count() >= CFG["max_open"]:
            self.note(f"{key} signal {hm} skipped: {CFG['max_open']} already open"); return
        if self.day_pnl() <= -CFG["day_loss"]:
            self.st["stopped"] = True; self.note("daily loss limit reached: no new entries today"); return
        trig = rnd(A[i][2] + CFG["tick"], up=True); lim = rnd(trig * (1 + CFG["limit_pct"]), up=True)
        t = dict(key=key, symbol=u["symbol"], side=side.upper(), tsym=info["tsym"], token=info["token"], lot=lot, signal=A[i][0],
                 sig_low=A[i][3], trigger=trig, limit=lim, state="pending", bars_waited=0, pcr_q=q, nf=round(nf, 2), bn=round(bn, 2),
                 live=self.live())
        if t["live"]:
            try:
                t["oid"] = self.b.nfo_order(info["tsym"], info["token"], "BUY", lot, lim, trigger=trig)
                t["live_state"] = "buy order on Angel"
            except Exception as ex:  # noqa: BLE001
                t["live_state"] = f"buy order rejected: {str(ex)[:120]}"
        self.st["trades"].append(t)
        self.note(f"{key} signal {hm}: buy above {trig}{' (LIVE order sent)' if t.get('oid') else ''}")

    def _manage(self, t, A, e5, last, info, lot, om):
        idx_of = {x[0]: k for k, x in enumerate(A)}
        s = idx_of.get(t["signal"])
        if s is None:
            return
        live_o = (om or {}).get(t.get("oid")) if t.get("oid") else None
        if t["state"] == "pending" and live_o and str(live_o.get("status", "")).lower() == "complete":
            e = float(live_o.get("avg") or t["trigger"]); risk = max(e - t["sig_low"], e * 0.03)      # Angel filled first: follow it
            t.update(state="open", entry=round(e, 2), stop=rnd(e - risk), filled_at=A[last][0], fill_bar=last)
            self.note(f"{t['key']} bought on Angel {e}, stop {t['stop']}")
        if t["state"] == "pending":
            for k in range(s + 1 + t.get("checked", 0), last + 1):
                t["checked"] = k - s
                x = A[k]
                if x[3] < t["sig_low"]:
                    self._cancel(t, "signal low broke before the trigger"); return
                if x[2] > t["trigger"]:
                    e = max(t["trigger"], x[1])
                    if e > t["limit"]:
                        if x[3] <= t["limit"]:
                            e = t["limit"]
                        else:
                            continue
                    risk = max(e - t["sig_low"], e * 0.03)
                    t.update(state="open", entry=round(e, 2), stop=rnd(e - risk), filled_at=x[0], fill_bar=k)
                    self.note(f"{t['key']} bought (paper) {t['entry']} at {x[0][11:16]}, stop {t['stop']}")
                    break
                if k - s >= CFG["trig_bars"]:
                    self._cancel(t, "not triggered in 3 candles"); return
            if t["state"] == "pending":
                return
        if t["state"] == "open":
            if live_o and t.get("live_entry") is None and str(live_o.get("status", "")).lower() == "complete":
                self._live_filled(t, live_o)
            for k in range(max(t.get("fill_bar", s), t.get("walked", 0)) + 1, last + 1):
                t["walked"] = k; x = A[k]
                if x[3] <= t["stop"]:
                    self._close(t, min(t["stop"], x[1]), x[0], "stop"); break
                if x[4] < e5[k]:
                    self._close(t, x[4], x[0], "close below 5 EMA"); break
                if x[0][11:16] >= CFG["eod"]:
                    self._close(t, x[4], x[0], "15:15 square-off"); break
            if t["state"] == "open":
                t["now"] = A[last][4]; t["upnl"] = round((A[last][4] - t["entry"] - 0.01 * t["entry"]) * t["lot"])
            # a live stop that filled on Angel closes the live side even if the candles have not shown it yet
            if live_o is not None and t.get("live_stop_oid") and om and str((om.get(t["live_stop_oid"]) or {}).get("status", "")).lower() == "complete":
                t["live_exit"] = (om[t["live_stop_oid"]].get("avg") or t["stop"]); t["live_state"] = "stopped on Angel"

    def _cancel(self, t, why):
        t["state"] = "cancelled"; t["why"] = why
        if t.get("oid"):
            try:
                self.b.cancel_order(t["oid"], "STOPLOSS"); t["live_state"] = "buy order cancelled"
            except Exception as ex:  # noqa: BLE001
                t["live_state"] = f"CANCEL FAILED - check Angel: {str(ex)[:80]}"
        self.note(f"{t['key']} cancelled: {why}")

    def _close(self, t, px, at, why):
        t.update(state="closed", exit=round(px, 2), exit_at=at, why=why, upnl=None)
        t["pnl"] = round((t["exit"] - t["entry"] - 0.01 * t["entry"]) * t["lot"])
        if t.get("oid") and t.get("live_entry") is None:            # the live buy never filled: withdraw it
            try:
                self.b.cancel_order(t["oid"], "STOPLOSS"); t["live_state"] = "live buy not filled - cancelled"
            except Exception:  # noqa: BLE001
                pass
        self.note(f"{t['key']} sold (paper) {t['exit']} - {why}: {'+' if t['pnl'] >= 0 else '-'}Rs {abs(t['pnl']):,}")
        if t.get("live_entry") is not None and t.get("live_exit") is None:
            t["hist_due"] = True                                     # written when Angel's sell fills (paper vs live record)
        else:
            self._hist(t)

    def _hist(self, t):
        t["hist_due"] = False
        try:
            with open(self.hp, "a") as f:
                f.write(json.dumps({k: t.get(k) for k in ("key", "symbol", "side", "signal", "filled_at", "entry", "exit", "exit_at", "why",
                                                           "pnl", "lot", "live", "live_entry", "live_exit", "pcr_q")} | {"day": self.st["day"]}) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _live_exit(self, t, om):
        """the paper trade closed (5 EMA close / 15:15 / stop): sell the live lot with a limit 2% under the last price, re-priced each
        cycle until Angel fills it. Never places a second sell while an earlier one may still be working (no accidental short)."""
        if t.get("live_exit") is not None:
            return
        so, eo = t.get("live_stop_oid"), t.get("live_exit_oid")
        st = lambda oid: str(((om or {}).get(oid) or {}).get("status", "")).lower()  # noqa: E731
        for oid, how, px in ((so, "stopped on Angel", t.get("stop")), (eo, "sold on Angel", t.get("exit"))):
            if oid and st(oid) == "complete":
                t["live_exit"] = (om[oid].get("avg") or px); t["live_state"] = how
                if t.get("hist_due"):
                    self._hist(t)
                return
        if (so or eo) and om is None:                       # order book not visible: wait, never risk a double sell
            return
        try:
            if so and not t.get("stop_cancelled") and st(so) not in ("cancelled", "rejected"):
                self.b.cancel_order(so, "STOPLOSS")
            if so:
                t["stop_cancelled"] = True
            if eo and st(eo) not in ("cancelled", "rejected"):
                self.b.cancel_order(eo, "NORMAL")
        except Exception as ex:  # noqa: BLE001
            t["live_state"] = f"could not cancel the earlier order - check Angel: {str(ex)[:80]}"; return
        try:
            ltp = self.b.ltp_ex("NFO", t["tsym"], t["token"]) or t["exit"]
            t["live_exit_oid"] = self.b.nfo_order(t["tsym"], t["token"], "SELL", t["lot"], rnd(ltp * 0.98)); t["live_state"] = "sell order on Angel"
        except Exception as ex:  # noqa: BLE001
            t["live_state"] = f"SELL FAILED - close it in Angel: {str(ex)[:80]}"

    # ------------------------------------------------------------------ app
    def stop_today(self):
        with self.lock:
            self.st["stopped"] = True; self.note("stopped for today from the app"); self._save()

    def flat_all(self):
        """square off everything open now (paper at the last price; live with a sell limit)."""
        with self.lock:
            try:
                om = self.b.order_map()
            except Exception:  # noqa: BLE001
                om = None
            for t in self.st["trades"]:
                if t["state"] == "pending":
                    self._cancel(t, "square-off from the app")
                elif t["state"] == "open":
                    self._close(t, t.get("now") or t["entry"], now_ist().strftime("%Y-%m-%dT%H:%M"), "square-off from the app")
                if t["state"] == "closed" and t.get("live_entry") is not None and t.get("live_exit") is None:
                    self._live_exit(t, om)
            self.st["stopped"] = True; self._save()

    def status(self):
        hist = []
        try:
            for line in open(self.hp):
                try:
                    hist.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        days = {}
        cmp = dict(n=0, paper=0, live=0, slip_in=[], slip_out=[], unfilled=0)   # paper vs live on the trades that went live (gross, no cost)
        for h in hist:
            d = days.setdefault(h["day"], dict(day=h["day"], n=0, pnl=0, wins=0, live_pnl=0, live_n=0, paper_on_live=0))
            d["n"] += 1; d["pnl"] += h.get("pnl") or 0; d["wins"] += (h.get("pnl") or 0) > 0
            if h.get("live") and h.get("live_entry") is None:
                cmp["unfilled"] += 1
            if h.get("live_entry") is not None and h.get("live_exit") is not None:
                lot = h.get("lot") or 0; lp = round((h["live_exit"] - h["live_entry"]) * lot); pp = round((h["exit"] - h["entry"]) * lot)
                d["live_pnl"] += lp; d["live_n"] += 1; d["paper_on_live"] += pp
                cmp["n"] += 1; cmp["paper"] += pp; cmp["live"] += lp
                if h.get("entry"):
                    cmp["slip_in"].append((h["live_entry"] / h["entry"] - 1) * 100)
                if h.get("exit"):
                    cmp["slip_out"].append((h["live_exit"] / h["exit"] - 1) * 100)
        avg = lambda L: round(sum(L) / len(L), 2) if L else None  # noqa: E731
        cmp = dict(n=cmp["n"], paper=cmp["paper"], live=cmp["live"], diff=cmp["live"] - cmp["paper"], unfilled=cmp["unfilled"],
                   entry_slip_pct=avg(cmp["slip_in"]), exit_slip_pct=avg(cmp["slip_out"]))
        D = sorted(days.values(), key=lambda x: x["day"])
        return dict(live=self.live(), day=self.st.get("day"), stopped=self.st.get("stopped"), trades=self.st.get("trades", []),
                    notes=self.st.get("notes", [])[-12:], day_pnl=self.day_pnl(), open=self._open_count(), cfg=CFG,
                    universe=len(self.uni or []), last_cycle=self.last_cycle, last_error=self.last_error,
                    stage=self.stage, stage_at=self.stage_at, running=bool(self.thread and self.thread.is_alive()),
                    watcher=bool(self.fast and self.fast.is_alive()),
                    history=dict(days=len(D), trades=sum(d["n"] for d in D), pnl=sum(d["pnl"] for d in D),
                                 wins=sum(d["wins"] for d in D), up_days=sum(d["pnl"] > 0 for d in D), live_pnl=sum(d["live_pnl"] for d in D),
                                 by_day=D[-15:], compare=cmp))
