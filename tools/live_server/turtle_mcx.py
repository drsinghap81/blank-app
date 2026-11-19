"""Turtle 20/10 on MCX futures, live on Angel (19 Nov 2026, Amritpal: "natural gas ... push to live").

Rules (as tools/turtle_watch.py, long only): buy-stop one tick above the highest high of the last 20 completed days; N = ATR(20),
Wilder; fixed stop = entry - 2N; trailing stop = lowest low of the last 10 completed days; exit at the first hit. No target, no adds.
Uses the REAL MCX contract from Angel (nearest expiry at least 5 days away for a new entry), not the NYMEX x USD/INR estimate.

Orders (SEBI 2026: limit / stop-limit only), product CARRYFORWARD (NRML), DAY validity, so they are re-placed every MCX morning:
  flat  : STOPLOSS_LIMIT BUY, trigger = 20-day high + 1 tick, limit 0.5% above. If the price already trades above the trigger,
          a marketable LIMIT buy 0.3% above the last price instead (the rule fills at max(open, 20-day high)).
  filled: within ~1 minute a STOPLOSS_LIMIT SELL at max(entry - 2N, 10-day low), limit 1% below; re-placed each morning at the new
          trail. If the price is already below the stop, a marketable LIMIT sell.
  expiry: 3 days before the contract expires an alert asks to roll by hand (no automatic roll).
Quantity sent to Angel = lots x Angel's own lot size for the contract (scrip master), so it follows Angel's convention.
Dry run (default): computes and shows the orders it WOULD place; nothing is sent. Live needs the app password + typing LIVE.
Each market is armed separately from the app (Turtle row -> Push to Live), with its number of lots."""
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def rnd(v, tick):
    return round(round(v / tick) * tick, 2)


class TurtleMCX:
    def __init__(self, broker, data_dir, log=lambda ev, **kw: None, alert=None):
        self.b, self.log = broker, log
        self.alert = alert or (lambda text, key=None: None)
        self.sp = os.path.join(data_dir, "turtle_mcx.json")
        self.st = self._load()
        self.lock = threading.Lock(); self.thread = None; self.last_run = None; self.last_error = None

    def _load(self):
        try:
            return json.load(open(self.sp))
        except Exception:  # noqa: BLE001
            return dict(live=False, armed={}, pos={}, orders={}, hist=[], notes=[], plan={})

    def _save(self):
        json.dump(self.st, open(self.sp + ".tmp", "w")); os.replace(self.sp + ".tmp", self.sp)

    def note(self, txt):
        self.st.setdefault("notes", []).append(f"{now_ist():%d %b %H:%M} {txt}"); self.st["notes"] = self.st["notes"][-40:]
        self.log("turtle_mcx", note=txt)

    # ------------------------------------------------------------------ app
    def set_live(self, on):
        with self.lock:
            self.st["live"] = bool(on); self.note(f"mode: {'LIVE orders' if on else 'dry run'}")
            if on:   # 19 Nov 2026 bug: a buy planned in dry run earlier the same day blocked the live order until the next day
                for name, o in self.st.get("orders", {}).items():
                    if name not in self.st.get("pos", {}) and not o.get("entry_oid") and not o.get("stop_oid"):
                        o.pop("entry_day", None)
            self._save()

    def arm(self, name, lots, on=True, mult=None):
        name = name.upper().replace("MCX:", "")
        with self.lock:
            if on:
                self.st.setdefault("armed", {})[name] = dict(lots=max(1, int(lots)), mult=mult, at=now_ist().isoformat(timespec="minutes"))
                self.note(f"{name}: armed, {max(1, int(lots))} lot(s)")
            else:
                self.st.get("armed", {}).pop(name, None); self.note(f"{name}: disarmed (an open position is still managed)")
                o = self.st.get("orders", {}).get(name, {})
                if o.get("entry_oid") and self.st["live"] and name not in self.st.get("pos", {}):
                    try:
                        self.b.cancel_order(o["entry_oid"], "STOPLOSS")
                    except Exception:  # noqa: BLE001
                        pass
                    self.st["orders"].pop(name, None)
            self._save()
        threading.Thread(target=self.run_once, daemon=True).start()

    def status(self):
        return dict(live=self.st.get("live", False), armed=self.st.get("armed", {}), pos=self.st.get("pos", {}), orders=self.st.get("orders", {}),
                    plan=self.st.get("plan", {}), hist=self.st.get("hist", [])[-20:], notes=self.st.get("notes", [])[-15:],
                    last_run=self.last_run, last_error=self.last_error)

    # ------------------------------------------------------------------ loop
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True); self.thread.start()

    def _loop(self):
        while True:
            t = now_ist()
            if t.weekday() < 5 and (9, 1) <= (t.hour, t.minute) <= (23, 25) and (self.st.get("armed") or self.st.get("pos")):
                try:
                    self.run_once()
                except Exception as ex:  # noqa: BLE001
                    self.last_error = f"{now_ist():%H:%M} {str(ex)[:200]}"; self.log("turtle_mcx_error", error=str(ex)[:200])
            time.sleep(60)

    def levels(self, name, contract):
        """20-day high, N (ATR 20, Wilder), 10-day low from the contract's completed daily candles."""
        C = [x for x in self.b.candles_ex("MCX", contract["token"], 90) if x[0] < str(now_ist().date())]
        if len(C) < 25:
            raise RuntimeError(f"{name}: only {len(C)} daily candles from Angel")
        tr = [C[0][2] - C[0][3]] + [max(C[i][2] - C[i][3], abs(C[i][2] - C[i - 1][4]), abs(C[i][3] - C[i - 1][4])) for i in range(1, len(C))]
        N = sum(tr[:20]) / 20
        for x in tr[20:]:
            N = N + (x - N) / 20
        return dict(hh20=max(x[2] for x in C[-20:]), ll10=min(x[3] for x in C[-10:]), N=N, last_close=C[-1][4], last_day=C[-1][0])

    def run_once(self):
        with self.lock:
            self.last_run = now_ist().strftime("%H:%M:%S")
            day = str(now_ist().date()); live = self.st.get("live", False)
            names = set(self.st.get("armed", {})) | set(self.st.get("pos", {}))
            om = None
            if any(o.get("entry_oid") or o.get("stop_oid") for o in self.st.get("orders", {}).values()):
                om = self.b.order_map()
            for name in sorted(names):
                try:
                    self._one(name, day, live, om)
                except Exception as ex:  # noqa: BLE001
                    self.last_error = f"{now_ist():%H:%M} {name}: {str(ex)[:160]}"
                    self.alert(f"Turtle MCX {name}: {str(ex)[:140]}", key=f"tmcx:err:{name}:{day}")
            self._save()

    def _contract(self, name, pos):
        if pos:
            return pos["contract"]
        info = self.b.fut_info("MCX", name, now_ist().date() + timedelta(days=5))
        if not info:
            raise RuntimeError(f"no MCX futures contract found for {name}")
        return info

    def _one(self, name, day, live, om):
        pos = self.st.setdefault("pos", {}).get(name); arm = self.st.get("armed", {}).get(name)
        o = self.st.setdefault("orders", {}).setdefault(name, {})
        c = self._contract(name, pos)
        L = self.st.setdefault("plan", {}).get(name)
        if not L or L.get("day") != day or L.get("token") != c["token"]:
            lv = self.levels(name, c)
            L = dict(day=day, token=c["token"], tsym=c["tsym"], expiry=str(c["expiry"]), lotsize=c["lotsize"], tick=c["tick"], **lv)
            L["trigger"] = rnd(lv["hh20"] + c["tick"], c["tick"])
            self.st["plan"][name] = L
        tick = c["tick"]
        if pos:            # ---------------- a REAL position (only live fills create one): its stop is kept on Angel in any mode
            stop = max(pos["fixed"], L["ll10"])
            pos["stop"] = rnd(stop, tick)
            if o.get("stop_oid") and om:
                s = om.get(o["stop_oid"]) or {}
                if str(s.get("status", "")).lower() == "complete":
                    px = float(s.get("avg") or stop)
                    self._closed(name, pos, px, "stop / 10-day low"); return
            dte = (date.fromisoformat(str(c["expiry"])[:10]) - now_ist().date()).days
            if dte <= 3:
                self.alert(f"Turtle MCX {name}: {c['tsym']} expires in {dte} day(s). Roll it by hand: sell this contract, buy the next one, "
                           f"and set its stop at {pos['stop']}.", key=f"tmcx:roll:{name}:{day}")
            if o.get("stop_day") != day or abs((o.get("stop_px") or 0) - pos["stop"]) > tick / 2:
                if o.get("stop_oid") and o.get("stop_day") == day:
                    try:
                        self.b.cancel_order(o["stop_oid"], "STOPLOSS")
                    except Exception:  # noqa: BLE001
                        pass
                ltp = self.b.ltp_ex("MCX", c["tsym"], c["token"]) or pos["stop"]
                if ltp <= pos["stop"]:                            # already through the stop: get out with a marketable limit
                    oid = self.b.fut_order("MCX", c["tsym"], c["token"], "SELL", pos["qty"], rnd(ltp * 0.995, tick), tick=tick)
                    o.update(stop_oid=oid, stop_day=day, stop_px=pos["stop"]); self.note(f"{name}: below the stop {pos['stop']} - limit sell sent")
                    self.alert(f"Turtle MCX {name}: price {ltp} is below the stop {pos['stop']} - limit sell sent on Angel", key=f"tmcx:out:{name}:{day}")
                else:
                    oid = self.b.fut_order("MCX", c["tsym"], c["token"], "SELL", pos["qty"], rnd(pos["stop"] * 0.99, tick), trigger=pos["stop"], tick=tick)
                    o.update(stop_oid=oid, stop_day=day, stop_px=pos["stop"], planned=f"SELL {pos['qty']} {c['tsym']} stop-limit, trigger {pos['stop']}")
                    self.note(f"{name}: stop on Angel at {pos['stop']} for {day}")
            return
        if not arm:                                               # ---------------- flat
            return
        qty = int(arm["lots"]) * int(c["lotsize"] or 1)
        if live and o.get("entry_oid") and om:
            e = om.get(o["entry_oid"]) or {}
            if str(e.get("status", "")).lower() == "complete":
                px = float(e.get("avg") or L["trigger"]); N = L["N"]
                pos = dict(contract=c, qty=qty, lots=arm["lots"], entry=px, N=N, fixed=rnd(px - 2 * N, tick), stop=rnd(max(px - 2 * N, L["ll10"]), tick),
                           at=now_ist().isoformat(timespec="minutes"), mult=arm.get("mult"))
                self.st["pos"][name] = pos; self.st["orders"][name] = {}
                self.note(f"{name}: BOUGHT {qty} {c['tsym']} at {px} on Angel; stop {pos['stop']}")
                self.alert(f"Turtle MCX {name}: bought {arm['lots']} lot(s) {c['tsym']} at {px}. Stop {pos['stop']} goes on Angel now.", key=f"tmcx:buy:{name}:{day}")
                return self._one(name, day, live, om)
            if str(e.get("status", "")).lower() in ("rejected", "cancelled") and o.get("entry_day") == day:
                if not o.get("rej_alert"):
                    o["rej_alert"] = True
                    self.alert(f"Turtle MCX {name}: Angel {e.get('status')} the buy order: {str(e.get('text') or '')[:100]}", key=f"tmcx:rej:{name}:{day}")
                return
        if o.get("entry_day") == day and (o.get("entry_oid") or not live):
            return
        ltp = self.b.ltp_ex("MCX", c["tsym"], c["token"]) if live else 0
        if live and ltp and ltp >= L["trigger"]:
            kind, price, trig = "LIMIT", rnd(ltp * 1.003, tick), None
        else:
            kind, price, trig = "STOPLOSS_LIMIT", rnd(L["trigger"] * 1.005, tick), L["trigger"]
        txt = f"BUY {qty} {c['tsym']} ({arm['lots']} lot, Angel lot size {c['lotsize']}) {kind} {'trigger ' + str(trig) + ' ' if trig else ''}limit {price}"
        if not live:
            o.update(entry_day=day, entry_oid=None, planned=txt, risk_2N=round(2 * L["N"], 2)); return
        oid = self.b.fut_order("MCX", c["tsym"], c["token"], "BUY", qty, price, trigger=trig, tick=tick)
        o.update(entry_day=day, entry_oid=oid, planned=txt, rej_alert=False)
        self.note(f"{name}: {txt} - sent to Angel ({oid})")

    def _closed(self, name, pos, px, why):
        m = pos.get("mult") or 1
        pnl = round((px - pos["entry"]) * m * pos.get("lots", 1))
        self.st.setdefault("hist", []).append(dict(name=name, tsym=pos["contract"]["tsym"], entry=pos["entry"], exit=px, lots=pos.get("lots"),
                                                   at=pos["at"], out=now_ist().isoformat(timespec="minutes"), why=why, pnl=pnl))
        self.st["pos"].pop(name, None); self.st["orders"].pop(name, None)
        self.note(f"{name}: SOLD at {px} ({why}), about Rs {pnl:,}")
        self.alert(f"Turtle MCX {name}: sold at {px} ({why}), about Rs {pnl:,}", key=f"tmcx:sell:{name}:{pos['at']}")
