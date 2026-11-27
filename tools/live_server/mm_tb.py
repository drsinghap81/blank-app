"""Top Bottom on moomoo - US and ASX ETFs, buy only (24 Nov 2026, Amritpal: "set up moomoo API and enable it for auto trading like Angel").

Tested versions: claude/top-bottom-us-screen.md (QQQ, SMH, XLF, XLE, XLK, SLV) and claude/top-bottom-asx-etf-test.md (TECH, HACK, OZR, ...).
Rules (ETF 1/2/2, buffer 0.05%): buy when price trades above the last swing top + 0.05% (skip if it opens > 1% above it); stop =
max(entry - 2%, last swing bottom - 0.05%), raised to the entry once the trade has been +2%; if the entry day CLOSES > 1% below the
entry, sell at the next open. Levels come from data/scan/tb_world.json (GitHub job after each close, tools/tb_world_prep.py).

What the server does, per market (US New York time, AU Sydney time):
  pre-open (US 09:05-09:29, AU 09:35-09:59), once a day:
    open trades  -> entry-day rule (sell at the open) or raise the GTC stop on moomoo to today's level
    flat ETFs    -> only if this market's automation is ON: a STOP-LIMIT buy for the day (trigger = level, limit = level + 1%)
                    sized at RISK % of the capital you set, capped at capital / number of ETFs, rounded down to whole shares
  in market hours every 2 minutes: fills -> protective GTC STOP sell; stop filled -> trade closed and logged.
If moomoo refuses stop orders (some paper accounts / markets) the server watches the price itself and sends limit orders instead.
MANUAL (automation off) stops NEW entries only; open trades keep their stops and the server keeps managing them.
Orders go to the account set on the server (MOOMOO_ENV: SIMULATE = paper by default, REAL only when you change it)."""
from __future__ import annotations

import json
import math
import os
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MKT = {
    "US": dict(tz=ZoneInfo("America/New_York"), pre=(9, 5), open=(9, 30), close=(16, 0), cur="USD", name="US"),
    "AU": dict(tz=ZoneInfo("Australia/Sydney"), pre=(9, 35), open=(10, 0), close=(16, 0), cur="AUD", name="ASX"),
}
DEFAULT_SYMS = {"US": ["QQQ", "SMH", "XLF", "XLE"], "AU": ["TECH", "HACK", "OZR", "ASIA"]}
DAY_SL, MAX_SL, BE, GAP = 0.01, 0.02, 0.02, 0.01


def tick(px, mk):
    return 0.005 if mk == "AU" and px < 2 else 0.01


def up(px, mk):
    t = tick(px, mk); return round(math.ceil(px / t - 1e-9) * t, 3)


def down(px, mk):
    t = tick(px, mk); return round(math.floor(px / t + 1e-9) * t, 3)


class MMTB:
    def __init__(self, mm, data_dir, levels, log, alert, auto_on, live_on):
        self.mm, self.levels, self.log, self.alert, self.auto_on, self.live_on = mm, levels, log, alert, auto_on, live_on
        self.path = os.path.join(data_dir, "mm_tb.json"); self.lock = threading.Lock()
        try:
            self.st = json.load(open(self.path))
        except Exception:  # noqa: BLE001
            self.st = {}
        self.st.setdefault("cfg", {}); self.st.setdefault("pos", {}); self.st.setdefault("day", {}); self.st.setdefault("trades", [])
        self.st.setdefault("notes", [])
        for mk in MKT:
            c = self.st["cfg"].setdefault(mk, {}); c.setdefault("capital", 0.0); c.setdefault("risk_pct", 1.0); c.setdefault("symbols", DEFAULT_SYMS[mk])
            self.st["pos"].setdefault(mk, {})

    # ------------------------------------------------------------------ helpers
    def _save(self):
        tmp = self.path + ".tmp"; json.dump(self.st, open(tmp, "w"), default=str); os.replace(tmp, self.path)

    def note(self, mk, txt):
        t = datetime.now(MKT[mk]["tz"]).strftime("%d %b %H:%M")
        self.st["notes"] = (self.st["notes"] + [f"{t} {MKT[mk]['name']}: {txt}"])[-60:]; self.log("mm_tb", mk=mk, note=txt)

    def now(self, mk):
        return datetime.now(MKT[mk]["tz"])

    def set_cfg(self, mk, capital=None, risk_pct=None, symbols=None):
        with self.lock:
            c = self.st["cfg"][mk]
            if capital is not None:
                c["capital"] = max(0.0, float(capital))
            if risk_pct is not None:
                c["risk_pct"] = min(2.0, max(0.1, float(risk_pct)))
            if symbols:
                c["symbols"] = [s.strip().upper() for s in symbols if s.strip()][:10]
            self._save(); return c

    def status(self):
        L = {}
        try:
            W = self.levels() or {}
            for mk in MKT:
                M = (W.get("markets") or {}).get(mk) or {}
                L[mk] = dict(asof=M.get("asof"), rows={s: dict(close=r.get("close"), buy_lvl=r.get("buy_lvl"), bot_stop=r.get("bot_stop"))
                                                     for s, r in (M.get("symbols") or {}).items() if s in self.st["cfg"][mk]["symbols"]})
        except Exception as ex:  # noqa: BLE001
            L["error"] = str(ex)[:160]
        return dict(cfg=self.st["cfg"], pos=self.st["pos"], trades=self.st["trades"][-40:], notes=self.st["notes"][-20:], levels=L,
                    unsupported=self.st.get("unsupported", {}), au_paper_blocked=getattr(self.mm, "env_name", "") == "SIMULATE",
                    env=getattr(self.mm, "env_name", "?"), enabled=bool(getattr(self.mm, "enabled", False) and getattr(self.mm, "trade_on", False)))

    def _place(self, mk, sym, side, qty, otype, price, aux=None, tif="DAY"):
        no = self.st.setdefault("unsupported", {}).setdefault(mk, [])
        if otype in no:
            raise RuntimeError(f"{otype} not supported on this account (remembered)")
        if not self.live_on():
            self.note(mk, f"DRY RUN (Live orders off): would {side} {qty} {sym} {otype} {price}{' trigger ' + str(aux) if aux else ''}")
            return "DRY"
        try:
            return self.mm.place(sym, side, qty, otype, price, aux=aux, tif=tif, mk=mk, remark="trenddesk-tb")
        except Exception as ex:
            if otype in ("STOP", "STOP_LIMIT") and "not support" in str(ex).lower():
                no.append(otype); self.note(mk, f"moomoo: {otype} orders not supported here - the server watches prices and sends limit orders instead")
            raise

    def _order(self, mk, oid):
        if oid == "DRY":
            return dict(status="DRY", dealt=0.0, avg=0.0)
        return self.mm.order(oid, mk=mk)

    def _cancel(self, mk, oid):
        if oid and oid != "DRY":
            try:
                self.mm.cancel(oid, mk=mk)
            except Exception as ex:  # noqa: BLE001
                self.note(mk, f"cancel {oid} failed: {str(ex)[:80]}")

    # ------------------------------------------------------------------ loop
    def step(self):
        if not (getattr(self.mm, "enabled", False) and getattr(self.mm, "trade_on", False)):
            return
        with self.lock:
            for mk in MKT:
                try:
                    self._step(mk)
                except Exception as ex:  # noqa: BLE001
                    self.note(mk, f"error: {str(ex)[:160]}")
            self._save()

    def _step(self, mk):
        n = self.now(mk); hm = (n.hour, n.minute); today = n.date().isoformat(); M = MKT[mk]
        if n.weekday() >= 5:
            return
        if M["pre"] <= hm < (M["close"][0] - 1, M["close"][1]) and self.st["day"].get(mk) != today:
            # 27 Nov 2026: also when the server was down / restarting through the pre-open window - run it late (no chasing)
            self.st["day"][mk] = today; self._preopen(mk, n, late=hm >= M["open"])
        # 27 Nov 2026 (Amritpal switched ASX on at 09:51, after the 09:35 check had already passed with it off): automation turned on
        # later in the day still places today's buy-stops while the market is open - only for ETFs still BELOW their buy level
        # (a level already crossed today is skipped, not chased), up to an hour before the close.
        if M["pre"] <= hm < (M["close"][0] - 1, M["close"][1]) and self.st.setdefault("ent", {}).get(mk) != today and self.auto_on(mk) \
                and self.st["day"].get(mk) == today:
            self._entries(mk, n, late=hm >= M["open"])
        if M["open"] <= hm <= (M["close"][0], M["close"][1] + 10) and self.st["pos"][mk]:
            self._monitor(mk, n, hm >= M["close"])

    def _preopen(self, mk, n, late=False):
        if mk == "AU" and getattr(self.mm, "env_name", "") == "SIMULATE":
            if self.st["pos"]["AU"] or self.auto_on("AU"):
                self.note(mk, "moomoo's paper trading does not cover ASX through the API - ASX runs only on the real account")
                self.alert("moomoo Top Bottom ASX: moomoo's paper account can't trade ASX through the API - nothing placed (US paper works)",
                           key=f"mmtb:aupaper:{n.date()}")
            return
        W = self.levels() or {}; Mk = (W.get("markets") or {}).get(mk) or {}; asof = Mk.get("asof"); S = Mk.get("symbols") or {}
        today = n.date()
        if not asof or date.fromisoformat(asof) >= today or (today - date.fromisoformat(asof)).days > 5:
            self.note(mk, f"levels are not from the last session (as of {asof}) - nothing placed today")
            self.alert(f"moomoo Top Bottom {MKT[mk]['name']}: levels are stale (as of {asof}); no new orders today", key=f"mmtb:stale:{mk}:{today}")
            return
        P = self.st["pos"][mk]; cfg = self.st["cfg"][mk]
        # 1. open trades: entry-day rule, then the stop
        for sym, p in list(P.items()):
            bar = S.get(sym)
            if p["state"] == "pending" or p["state"] == "watch":
                P.pop(sym)                               # yesterday's day order expired at the close
                continue
            if p["state"] != "open" or not bar:
                continue
            e = p["entry"]; p["hi"] = max(p.get("hi") or e, bar["high"]); p["be"] = p.get("be") or p["hi"] >= e * (1 + BE)
            if p.get("entry_date") == bar["date"] and bar["close"] < e * (1 - DAY_SL):
                self._cancel(mk, p.get("stop_oid")); px = down(bar["close"] * 0.97, mk)
                try:
                    p["exit_oid"] = self._place(mk, sym, "SELL", p["qty"], "NORMAL", px)
                    p["state"] = "exiting"; p["why"] = "entry-day close more than 1% below entry"
                    self.note(mk, f"{sym}: entry day closed {bar['close']} < {e * (1 - DAY_SL):.3f} -> sell {p['qty']} at the open")
                    self.alert(f"moomoo {sym}: entry-day rule - selling {p['qty']} at the open", key=f"mmtb:eds:{mk}:{sym}:{today}")
                except Exception as ex:  # noqa: BLE001
                    self.note(mk, f"{sym}: exit order refused ({str(ex)[:100]}) - sell it in moomoo")
                continue
            ns = max(e * (1 - MAX_SL), bar.get("bot_stop") or 0.0)
            if p["be"]:
                ns = max(ns, e)
            ns = down(ns, mk)
            if ns > (p.get("stop") or 0) + tick(ns, mk) / 2:
                old = p.get("stop"); p["stop"] = ns
                if p.get("stop_oid"):
                    self._cancel(mk, p["stop_oid"]); p["stop_oid"] = None
                    try:
                        p["stop_oid"] = self._place(mk, sym, "SELL", p["qty"], "STOP", ns, aux=ns, tif="GTC")
                    except Exception as ex:  # noqa: BLE001
                        self.note(mk, f"{sym}: stop order refused ({str(ex)[:80]}) - the server watches {ns} itself")
                self.note(mk, f"{sym}: stop raised {old} -> {ns}{' (breakeven)' if p['be'] and ns >= e else ''}")
        if self.auto_on(mk):
            self._entries(mk, n, late=late)

    def _entries(self, mk, n, late=False):
        """2. new entries (only with this market's automation on). late = placed during the session: skip ETFs already at / above
        their level today (the rule doesn't chase)."""
        W = self.levels() or {}; Mk = (W.get("markets") or {}).get(mk) or {}; S = Mk.get("symbols") or {}; asof = Mk.get("asof")
        if not asof or date.fromisoformat(asof) >= n.date() or (n.date() - date.fromisoformat(asof)).days > 5:
            return                                                   # stale levels: the pre-open check already said so
        P = self.st["pos"][mk]; cfg = self.st["cfg"][mk]
        cap = float(cfg.get("capital") or 0); syms = cfg.get("symbols") or []
        if cap <= 0 or not syms:
            self.note(mk, "automation on but no capital set - nothing placed"); return
        snap = {}
        if late:
            try:
                snap = self.mm.snapshot([x for x in syms if x not in P], mk=mk) or {}
            except Exception as ex:  # noqa: BLE001
                # 27 Nov 2026: moomoo gives no ASX quotes to this account ("Unsupported quote market"). Place the day's stop-limits
                # anyway: one only fills between the level and level + 1% - the same window the pre-open order allows.
                snap = None; self.note(mk, f"no live price from moomoo ({str(ex)[:60]}) - placing the stop-limits without the price check")
        self.st.setdefault("ent", {})[mk] = n.date().isoformat()
        cap = float(cfg.get("capital") or 0); syms = cfg.get("symbols") or []
        if cap <= 0 or not syms:
            self.note(mk, "automation on but no capital set - nothing placed"); return
        used = sum(p.get("qty", 0) * (p.get("entry") or p.get("trig") or 0) for p in P.values())
        try:
            cash = float(self.mm.cash(mk))
        except Exception:  # noqa: BLE001
            cash = cap
        for sym in syms:
            if sym in P or sym not in S:
                continue
            bar = S[sym]; lv = bar.get("buy_lvl")
            if not lv:
                continue
            if late and snap is not None:
                q0 = snap.get(sym) or {}; hi = q0.get("high") or q0.get("last")
                if not hi:
                    self.note(mk, f"{sym}: no price - not placed"); continue
                if hi >= lv:
                    self.note(mk, f"{sym}: already traded at/above {lv} today ({hi}) - level skipped, not chased"); continue
            trig = up(lv, mk); lim = down(lv * (1 + GAP), mk); st0 = max(lv * (1 - MAX_SL), bar.get("bot_stop") or 0.0)
            if st0 >= trig * 0.995:
                st0 = trig * (1 - MAX_SL)
            st0 = down(st0, mk)
            q = math.floor(min(cap * cfg["risk_pct"] / 100 / max(trig - st0, 1e-9), cap / len(syms) / lim))
            if q < 1:
                self.note(mk, f"{sym}: capital too small for one share at {trig}"); continue
            if used + q * lim > cap or q * lim > cash:
                self.note(mk, f"{sym}: skipped - not enough of the capital / cash left for {q} x {lim}"); continue
            try:
                oid = self._place(mk, sym, "BUY", q, "STOP_LIMIT", lim, aux=trig, tif="DAY"); soft = False
            except Exception as ex:  # noqa: BLE001
                oid = None; soft = True; self.note(mk, f"{sym}: stop-limit refused ({str(ex)[:80]}) - the server watches {trig} itself")
            P[sym] = dict(state="watch" if soft else "pending", entry_oid=oid, trig=trig, lim=lim, qty=q, stop0=st0, placed=n.date().isoformat())
            used += q * lim
            self.note(mk, f"{sym}: buy-stop {q} @ {trig} (limit {lim}, stop {st0})")
        n_new = sum(1 for p in P.values() if p["state"] in ("pending", "watch") and p.get("placed") == n.date().isoformat())
        if n_new:
            self.alert(f"moomoo Top Bottom {MKT[mk]['name']}: {n_new} buy-stop(s) for today: " + ", ".join(
                f"{s} {p['qty']} @ {p['trig']}" for s, p in P.items() if p["state"] in ("pending", "watch")), key=f"mmtb:pre:{mk}:{n.date()}")

    def _monitor(self, mk, n, after_close):
        P = self.st["pos"][mk]; snap = None
        soft = [s for s, p in P.items() if p["state"] == "watch" or (p["state"] == "open" and not p.get("stop_oid"))]
        if soft:
            try:
                snap = self.mm.snapshot(soft, mk=mk)
            except Exception as ex:  # noqa: BLE001
                self.note(mk, f"price check failed: {str(ex)[:80]}")
        for sym, p in list(P.items()):
            st = p["state"]
            if st == "pending":
                o = self._order(mk, p["entry_oid"])
                if o["dealt"] > 0 and ("FILLED_ALL" in o["status"] or after_close or "CANCEL" in o["status"]):
                    self._opened(mk, sym, p, o["avg"], o["dealt"], n)
                elif "CANCEL" in o["status"] or "FAIL" in o["status"] or "DELETED" in o["status"] or (after_close and o["dealt"] == 0):
                    P.pop(sym); self.note(mk, f"{sym}: buy-stop not filled today ({o['status']})")
            elif st == "watch":
                q = (snap or {}).get(sym) or {}; last = q.get("last")
                if last and p["trig"] <= last <= p["lim"] and not after_close:
                    try:
                        p["entry_oid"] = self._place(mk, sym, "BUY", p["qty"], "NORMAL", p["lim"]); p["state"] = "pending"
                        self.note(mk, f"{sym}: traded {last} above {p['trig']} -> limit buy {p['qty']} @ {p['lim']}")
                    except Exception as ex:  # noqa: BLE001
                        self.note(mk, f"{sym}: buy refused ({str(ex)[:80]})"); P.pop(sym)
                elif after_close:
                    P.pop(sym)
            elif st == "open":
                if p.get("stop_oid"):
                    o = self._order(mk, p["stop_oid"])
                    if o["dealt"] >= p["qty"] - 1e-9 and o["dealt"] > 0:
                        self._closed(mk, sym, p, o["avg"], "stop", n)
                else:
                    last = ((snap or {}).get(sym) or {}).get("last")
                    if last and last <= p["stop"]:
                        try:
                            p["exit_oid"] = self._place(mk, sym, "SELL", p["qty"], "NORMAL", down(last * 0.99, mk)); p["state"] = "exiting"
                            p["why"] = "stop (watched by the server)"; self.note(mk, f"{sym}: {last} at/below stop {p['stop']} -> sell")
                        except Exception as ex:  # noqa: BLE001
                            self.note(mk, f"{sym}: sell refused ({str(ex)[:80]}) - sell it in moomoo")
            elif st == "exiting":
                o = self._order(mk, p.get("exit_oid"))
                if o["dealt"] >= p["qty"] - 1e-9 and o["dealt"] > 0:
                    self._closed(mk, sym, p, o["avg"], p.get("why") or "exit", n)

    def _opened(self, mk, sym, p, avg, qty, n):
        p.update(state="open", entry=round(float(avg), 4), qty=float(qty), entry_date=n.date().isoformat(), hi=float(avg), be=False)
        st0 = min(p.get("stop0") or avg * (1 - MAX_SL), down(avg * 0.999, mk)); p["stop"] = st0
        try:
            p["stop_oid"] = self._place(mk, sym, "SELL", qty, "STOP", st0, aux=st0, tif="GTC")
        except Exception as ex:  # noqa: BLE001
            p["stop_oid"] = None; self.note(mk, f"{sym}: stop order refused ({str(ex)[:80]}) - the server watches {st0} itself")
        self.note(mk, f"{sym}: BOUGHT {qty:g} @ {avg} - stop {st0}")
        self.alert(f"moomoo {sym}: bought {qty:g} @ {avg} (Top Bottom {MKT[mk]['name']}); stop {st0}", key=f"mmtb:fill:{mk}:{sym}:{n.date()}")

    def _closed(self, mk, sym, p, px, why, n):
        pnl = (float(px) - p["entry"]) * p["qty"]
        self.st["trades"].append(dict(mk=mk, sym=sym, entry=p["entry"], exit=round(float(px), 4), qty=p["qty"], entry_date=p.get("entry_date"),
                                      exit_date=n.date().isoformat(), pnl=round(pnl, 2), pct=round((float(px) / p["entry"] - 1) * 100, 2), why=why))
        self.st["pos"][mk].pop(sym, None)
        self.note(mk, f"{sym}: SOLD {p['qty']:g} @ {px} ({why}) P&L {pnl:+.2f} {MKT[mk]['cur']}")
        self.alert(f"moomoo {sym}: sold {p['qty']:g} @ {px} ({why}), P&L {pnl:+.2f} {MKT[mk]['cur']}", key=f"mmtb:sold:{mk}:{sym}:{n.date()}")
