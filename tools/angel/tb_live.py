"""Top Bottom live trading core — the same rules as tools/topbottom_backtest.run_live,
driven intraday by price polling instead of daily bars.

Design (SEBI 2026: no market / IOC orders for API algos):
  * The bot WATCHES the near-month future (the same contract the backtest series uses)
    and, when a level trades, sends a marketable LIMIT order (ltp +/- slippage) and
    re-prices it until filled ("chase").
  * While a position is open, a resting STOP-LOSS-LIMIT "backstop" order sits at the
    exchange slightly beyond the system stop, so the position is still protected if
    this computer / internet dies.
  * Entries (and stop-and-reverse) can require approval on Telegram.

This file has no broker or Telegram code; those are injected (angel_broker.py, notify.py),
so the exact same logic runs in the simulator (sim_check.py).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # tools/
from topbottom_backtest import confirmed_swings     # noqa: E402  (identical top/bottom logic)

EPS = 1e-6


# --------------------------------------------------------------------------- config / state
DEFAULT_CFG = {
    "symbol": "BANKNIFTY",
    "lots": 2,
    "buffer_pts": 25,
    "day_sl_pct": 1.0,
    "max_sl_pct": 2.0,
    "be_pct": 2.0,
    "gap_pct": 2.0,
    "use_once": True,
    "entry_day_sl": "intraday",      # "intraday" = real 1% stop all day; "close" = check at 15:20 only (backtest style)
    "confirm_entries": True,         # ask on Telegram before a NEW entry
    "confirm_reversals": True,       # ask before stop-and-reverse at a system point
    "no_reply": "skip",              # what to do if you don't answer by the open: "skip" or "trade"
    "slippage_pct": 0.2,             # marketable-limit offset from LTP
    "backstop_pct": 0.5,             # exchange stop sits this far beyond the bot's stop
    "poll_seconds": 2,
    "close_check_time": "15:20",
    "roll_time": "15:10",
    "next_month_on_expiry_day": True,
    "dry_run": True,                 # True = real prices, simulated orders (nothing sent to Angel)
    "start_date": None,
}


@dataclass
class State:
    pos: int = 0                 # +1 long, -1 short, 0 flat
    lots: int = 0
    entry: float = 0.0           # system entry price (reference series)
    entry_date: str | None = None
    be_on: bool = False
    used_T: float | None = None
    used_B: float | None = None
    contract: str | None = None  # trading symbol held
    qty: int = 0                 # signed quantity held
    backstop_id: str | None = None
    halted: bool = False
    trades: list = field(default_factory=list)

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        d = json.load(open(path))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path):
        tmp = path + ".tmp"
        json.dump(asdict(self), open(tmp, "w"), indent=2, default=str)
        os.replace(tmp, path)


def same(a, b):
    return a is not None and b is not None and not (isinstance(a, float) and math.isnan(a)) and abs(a - b) < EPS


# --------------------------------------------------------------------------- daily plan (mirrors run_live exactly)
def levels(hist: pd.DataFrame):
    """latest confirmed top / bottom known at the end of the last bar in hist."""
    T, B, _ = confirmed_swings(hist["Close"].to_numpy(float), 0.0)
    t, b = T[-1], B[-1]
    return (None if np.isnan(t) else float(t)), (None if np.isnan(b) else float(b))


def make_plan(hist: pd.DataFrame, st: State, cfg: dict) -> dict:
    buf = cfg["buffer_pts"]
    top, bot = levels(hist)
    buy_lvl = top + buf if top is not None and (not cfg["use_once"] or not same(top, st.used_T)) else None
    sell_lvl = bot - buf if bot is not None and (not cfg["use_once"] or not same(bot, st.used_B)) else None
    plan = dict(date=str(hist.index[-1].date()), top=top, bot=bot, buy_lvl=buy_lvl, sell_lvl=sell_lvl,
                prot=None, prot_is_sys=False, reverse_lvl=None)
    if st.pos != 0:
        ent = st.entry
        prot = ent * (1 - st.pos * cfg["max_sl_pct"] / 100)
        if st.pos > 0 and bot is not None:
            prot = max(prot, bot - buf)
        if st.pos < 0 and top is not None:
            prot = min(prot, top + buf)
        if st.be_on:
            prot = max(prot, ent) if st.pos > 0 else min(prot, ent)
        is_sys = (st.pos > 0 and sell_lvl is not None and abs(prot - sell_lvl) < EPS) or \
                 (st.pos < 0 and buy_lvl is not None and abs(prot - buy_lvl) < EPS)
        plan.update(prot=prot, prot_is_sys=bool(is_sys), reverse_lvl=(sell_lvl if st.pos > 0 else buy_lvl) if is_sys else None)
    return plan


def init_flat_state(hist: pd.DataFrame, cfg: dict) -> State:
    """Start flat; a top/bottom price has ALREADY broken is spent (same as run_live start_flat_on)."""
    st = State()
    c = hist["Close"].to_numpy(float); h = hist["High"].to_numpy(float); l = hist["Low"].to_numpy(float)
    T, B, _ = confirmed_swings(c, 0.0)
    buf = cfg["buffer_pts"]
    n = len(c)
    for arr, is_top in ((T, True), (B, False)):
        v = arr[n - 1]
        if np.isnan(v):
            continue
        k = int(np.argmax(arr == v))
        seg_h, seg_l = h[k + 1:n], l[k + 1:n]
        if is_top and len(seg_h) and seg_h.max() >= v + buf:
            st.used_T = float(v)
        if not is_top and len(seg_l) and seg_l.min() <= v - buf:
            st.used_B = float(v)
    return st


def describe_plan(plan: dict, st: State, cfg: dict) -> str:
    f = lambda x: f"{x:,.2f}"
    L = [f"TOP BOTTOM {cfg['symbol']} FUT — plan for the session after {plan['date']}",
         f"Prev top {f(plan['top']) if plan['top'] else '-'} | prev bottom {f(plan['bot']) if plan['bot'] else '-'}"]
    if st.pos == 0:
        L.append("Position: FLAT")
        L.append(f"BUY {st.lots or cfg['lots']} lots above {f(plan['buy_lvl'])}" if plan["buy_lvl"] else "No buy: awaiting new top")
        L.append(f"SELL {st.lots or cfg['lots']} lots below {f(plan['sell_lvl'])}" if plan["sell_lvl"] else "No sell: awaiting new bottom")
        L.append(f"Entry-day stop {cfg['day_sl_pct']}% from entry ({cfg['entry_day_sl']})")
    else:
        side = "LONG" if st.pos > 0 else "SHORT"
        L.append(f"Position: {side} {st.lots} lots from {f(st.entry)} ({st.entry_date}) in {st.contract}")
        L.append(f"Stop {f(plan['prot'])}" + (" = system point → reverse" if plan["prot_is_sys"] else (" (breakeven)" if st.be_on else "")))
    L.append(f"Open beyond a level by > {cfg['gap_pct']}%: no new trade")
    return "\n".join(L)


# --------------------------------------------------------------------------- the trading day
class TradingDay:
    """One session. Call: start() -> on_open() -> tick() repeatedly -> end_of_day(bar)."""

    def __init__(self, today: date, hist: pd.DataFrame, st: State, cfg: dict, broker, notify, approvals,
                 log=print, state_path: str | None = None):
        self.today, self.hist, self.st, self.cfg = today, hist, st, cfg
        self.br, self.nt, self.ap, self.log = broker, notify, approvals, log
        self.state_path = state_path
        self.plan = make_plan(hist, st, cfg)
        self.ref = broker.reference_contract(today)            # contract the levels are measured on
        self.open_px = None
        self.done_for_day = False       # after a non-system stop-out: no new entries today (as backtest)
        self.entered_today = st.entry_date == str(today)
        self.close_checked = False
        self.rolled = False
        self.keys = {}
        self._since_entry = (float("-inf"), float("inf"))

    # ---- helpers
    def save(self):
        if self.state_path:
            self.st.save(self.state_path)

    def say(self, msg):
        self.log(msg)
        self.nt.send(msg)

    def lots_qty(self, contract, lots):
        return lots * self.br.lot_size(contract)

    def trade_contract(self):
        """contract for NEW positions"""
        if self.cfg["next_month_on_expiry_day"] and self.br.expiry(self.ref) == self.today:
            return self.br.next_contract(self.ref)
        return self.ref

    def approved(self, key):
        need = self.cfg["confirm_reversals"] if key.endswith("REV") else self.cfg["confirm_entries"]
        if not need:
            return True
        a = self.ap.get(key)
        if a is None:
            return None if not self.open_px else (self.cfg["no_reply"] == "trade")
        return a

    # ---- before the open
    def start(self):
        st, p, c = self.st, self.plan, self.cfg
        if not st.lots:
            st.lots = c["lots"]
        self.say(describe_plan(p, st, c))
        d = str(self.today)
        if st.pos == 0:
            if p["buy_lvl"]:
                self.keys["BUY"] = f"{d}:BUY"
                if c["confirm_entries"]:
                    self.ap.ask(self.keys["BUY"], f"Approve BUY {st.lots} lots {c['symbol']} FUT above {p['buy_lvl']:,.2f} today?")
            if p["sell_lvl"]:
                self.keys["SELL"] = f"{d}:SELL"
                if c["confirm_entries"]:
                    self.ap.ask(self.keys["SELL"], f"Approve SELL {st.lots} lots {c['symbol']} FUT below {p['sell_lvl']:,.2f} today?")
        elif p["prot_is_sys"]:
            self.keys["REV"] = f"{d}:REV"
            if c["confirm_reversals"]:
                side = "SELL" if st.pos > 0 else "BUY"
                self.ap.ask(self.keys["REV"], f"If the stop {p['prot']:,.2f} hits, also REVERSE ({side} {st.lots} lots)? "
                                              f"No = exit only.")

    # ---- at 09:15
    def on_open(self, q):
        self.open_px = q["open"]
        self.log(f"open {self.open_px}")
        if self.st.pos != 0:
            self.place_backstop()
        self.tick(q)

    def late_start(self, q):
        """Bot started after the open: a level that already traded while the bot was off
        is marked used (no late chase entry). Stops are still honoured on the next tick."""
        st, p = self.st, self.plan
        self.open_px = q["open"]
        if st.pos == 0 and not self.entered_today:
            if p["buy_lvl"] is not None and q["high"] >= p["buy_lvl"] and not same(p["top"], st.used_T):
                st.used_T = p["top"]
                self.say(f"Started late: BUY level {p['buy_lvl']:,.2f} already traded today — skipped (level used).")
            if p["sell_lvl"] is not None and q["low"] <= p["sell_lvl"] and not same(p["bot"], st.used_B):
                st.used_B = p["bot"]
                self.say(f"Started late: SELL level {p['sell_lvl']:,.2f} already traded today — skipped (level used).")
        if st.pos != 0:
            self.place_backstop(None if not self.entered_today else st.entry * (1 - st.pos * self.cfg["day_sl_pct"] / 100))
        self.save()
        self.tick(q)

    # ---- every poll
    def tick(self, q):
        if self.st.halted:
            return
        st, p, c = self.st, self.plan, self.cfg
        hi, lo, ltp = q["high"], q["low"], q["ltp"]
        o = self.open_px
        if st.pos != 0 and not self.entered_today:
            prot = p["prot"]
            hit = (st.pos > 0 and lo <= prot + EPS) or (st.pos < 0 and hi >= prot - EPS)
            if hit:
                side = st.pos
                is_sys = p["prot_is_sys"]
                gap_open = (side > 0 and o < prot) or (side < 0 and o > prot)
                reason = "System point" if is_sys else ("Breakeven" if st.be_on else "Max SL")
                ref_px = min(o, prot) if side > 0 else max(o, prot)          # backtest booking price
                reverse = False
                if is_sys:
                    lvl = p["reverse_lvl"]
                    if side > 0:
                        st.used_B = p["bot"]
                    else:
                        st.used_T = p["top"]
                    gapped = gap_open and abs(o - lvl) / lvl * 100 > c["gap_pct"]
                    ok = self.approved(self.keys["REV"]) if "REV" in self.keys else True
                    reverse = (not gapped) and bool(ok)
                    if gapped:
                        self.say(f"Opened > {c['gap_pct']}% beyond the system point: exit only, no reversal.")
                self.exit_position(reason + (" (gap)" if gap_open else ""), ref_px)
                if reverse:
                    self.enter(-side, ref_px, "Reverse at system point")
                    self.entered_today = True
                else:
                    self.done_for_day = True
                self.save()
                return
        if st.pos != 0 and self.entered_today and c["entry_day_sl"] == "intraday":
            h0, l0 = self._since_entry
            self._since_entry = (max(h0, ltp), min(l0, ltp))
            stop = st.entry * (1 - st.pos * c["day_sl_pct"] / 100)
            if (st.pos > 0 and self._since_entry[1] <= stop) or (st.pos < 0 and self._since_entry[0] >= stop):
                self.exit_position("Entry-day SL", stop)
                self.done_for_day = True
                self.save()
                return
        if st.pos == 0 and not self.done_for_day:
            self.check_entries(hi, lo, ltp)

    def check_entries(self, hi, lo, ltp):
        st, p, c = self.st, self.plan, self.cfg
        o = self.open_px
        go_l = p["buy_lvl"] is not None and hi >= p["buy_lvl"] and not same(p["top"], st.used_T)
        go_s = p["sell_lvl"] is not None and lo <= p["sell_lvl"] and not same(p["bot"], st.used_B)
        if go_l and go_s:
            go_l = abs(o - p["buy_lvl"]) <= abs(o - p["sell_lvl"])
            go_s = not go_l
        if go_l:
            st.used_T = p["top"]
            lvl = p["buy_lvl"]
            if o > lvl and (o - lvl) / lvl * 100 > c["gap_pct"]:
                self.say(f"BUY level {lvl:,.2f} gapped over by > {c['gap_pct']}% at the open: no trade (level used).")
            elif not self.approved(self.keys.get("BUY", "")):
                self.say(f"BUY level {lvl:,.2f} traded but the entry was not approved: no trade (level used).")
            else:
                self.enter(1, max(o, lvl), "Buy above prev top")
                self.entered_today = True
            self.save()
        elif go_s:
            st.used_B = p["bot"]
            lvl = p["sell_lvl"]
            if o < lvl and (lvl - o) / lvl * 100 > c["gap_pct"]:
                self.say(f"SELL level {lvl:,.2f} gapped under by > {c['gap_pct']}% at the open: no trade (level used).")
            elif not self.approved(self.keys.get("SELL", "")):
                self.say(f"SELL level {lvl:,.2f} traded but the entry was not approved: no trade (level used).")
            else:
                self.enter(-1, min(o, lvl), "Sell below prev bottom")
                self.entered_today = True
            self.save()

    # ---- order actions
    def enter(self, side, sys_px, why):
        st = self.st
        con = self.trade_contract()
        qty = self.lots_qty(con, st.lots)
        fill = self.br.execute(con, "BUY" if side > 0 else "SELL", qty, why)
        if fill is None:
            self.say(f"⚠️ {why}: order NOT filled — staying flat. Check Angel.")
            return
        st.pos, st.entry, st.entry_date, st.be_on = side, float(sys_px), str(self.today), False
        st.contract, st.qty = con, side * qty
        self._since_entry = (fill, fill)
        st.trades.append(dict(EntryDate=str(self.today), Side="BUY" if side > 0 else "SELL", Entry=round(sys_px, 2),
                              Fill=fill, Contract=con, Qty=qty, Signal=why))
        stop = sys_px * (1 - side * self.cfg["day_sl_pct"] / 100)
        self.say(f"✅ {'BOUGHT' if side > 0 else 'SOLD'} {st.lots} lots {con} @ {fill:,.2f} (level {sys_px:,.2f}) — {why}. "
                 f"Entry-day SL {stop:,.2f}")
        self.place_backstop(stop)

    def exit_position(self, why, sys_px):
        st = self.st
        self.cancel_backstop()
        side = "SELL" if st.qty > 0 else "BUY"
        fill = self.br.execute(st.contract, side, abs(st.qty), why, must_fill=True)
        if fill is None:
            st.halted = True
            self.say(f"🚨 EXIT {why} NOT FILLED for {st.contract} — bot halted, close it manually in Angel!")
            return
        sign = 1 if st.qty > 0 else -1
        pts_sys = (sys_px - st.entry) * sign
        last = st.trades[-1] if st.trades else {}
        last.update(ExitDate=str(self.today), Exit=round(sys_px, 2), ExitFill=fill, Reason=why,
                    Points=round(pts_sys, 2), PnL_fill=round((fill - last.get("Fill", st.entry)) * sign * abs(st.qty), 0))
        self.say(f"⏹ Exit {st.contract} @ {fill:,.2f} ({why}). System points {pts_sys:+,.1f}, "
                 f"fill P&L ₹{last['PnL_fill']:,.0f}")
        st.pos, st.qty, st.contract, st.be_on = 0, 0, None, False

    def place_backstop(self, stop=None):
        """resting exchange stop just beyond the bot stop (protection if the bot dies)."""
        st, c = self.st, self.cfg
        if st.pos == 0:
            return
        self.cancel_backstop()
        stop = stop if stop is not None else self.plan["prot"]
        if stop is None:
            return
        k = c["backstop_pct"] / 100
        trig = stop * (1 - k) if st.pos > 0 else stop * (1 + k)
        st.backstop_id = self.br.stop_limit(st.contract, "SELL" if st.pos > 0 else "BUY", abs(st.qty), trig)
        self.log(f"backstop {st.backstop_id} trigger {trig:,.2f}")
        self.save()

    def cancel_backstop(self):
        if self.st.backstop_id:
            self.br.cancel(self.st.backstop_id)
            self.st.backstop_id = None

    # ---- late in the day
    def before_close(self, q):
        """15:20 IST: entry-day stop on the close (backtest-style mode) and expiry rollover."""
        st, c = self.st, self.cfg
        if st.pos != 0 and self.entered_today and c["entry_day_sl"] == "close" and not self.close_checked:
            self.close_checked = True
            stop = st.entry * (1 - st.pos * c["day_sl_pct"] / 100)
            if (st.pos > 0 and q["ltp"] <= stop) or (st.pos < 0 and q["ltp"] >= stop):
                self.exit_position("Entry-day SL (close)", stop)
                self.save()

    def roll(self):
        st = self.st
        if self.rolled or st.pos == 0 or self.br.expiry(st.contract) != self.today:
            return
        self.rolled = True
        new = self.br.next_contract(st.contract)
        side = "BUY" if st.qty > 0 else "SELL"
        self.cancel_backstop()
        out = self.br.execute(st.contract, "SELL" if st.qty > 0 else "BUY", abs(st.qty), "Roll out", must_fill=True)
        if out is None:
            st.halted = True
            self.say("🚨 Rollover exit failed — bot halted, check Angel!")
            return
        qty = self.lots_qty(new, st.lots)
        inn = self.br.execute(new, side, qty, "Roll in", must_fill=True)
        if inn is None:
            st.halted = True
            st.pos, st.qty, st.contract = 0, 0, None
            self.say("🚨 Rolled OUT but roll-in failed — you are FLAT, bot halted. Check Angel!")
            self.save()
            return
        if st.trades:
            st.trades[-1].setdefault("Rolls", []).append(dict(date=str(self.today), out=out, inn=inn, to=new))
        st.contract, st.qty = new, (1 if side == "BUY" else -1) * qty
        self.say(f"🔁 Rolled {side} {st.lots} lots into {new} (out {out:,.2f}, in {inn:,.2f})")
        self.place_backstop(None if not self.entered_today else st.entry * (1 - st.pos * self.cfg['day_sl_pct'] / 100))
        self.save()

    # ---- after the close
    def end_of_day(self, bar: dict):
        """bar = today's OHLC of the reference contract. Updates breakeven, appends history."""
        st, c = self.st, self.cfg
        if st.pos != 0 and not self.entered_today:
            fav = (bar["High"] - st.entry) / st.entry * 100 if st.pos > 0 else (st.entry - bar["Low"]) / st.entry * 100
            if c["be_pct"] and fav >= c["be_pct"] and not st.be_on:
                st.be_on = True
                self.say(f"Breakeven armed: stop moves to entry {st.entry:,.2f} from tomorrow.")
        row = pd.DataFrame([bar], index=[pd.Timestamp(self.today)])
        self.hist = pd.concat([self.hist[self.hist.index < pd.Timestamp(self.today)], row[["Open", "High", "Low", "Close"]]])
        self.save()
        return self.hist
