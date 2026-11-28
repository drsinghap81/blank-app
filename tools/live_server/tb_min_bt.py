"""Bank Nifty / Nifty Top Bottom replayed on Angel 1-minute bars (29 Nov 2026, Amritpal: "10000 points can easily be made in bn per year"
-> "Yes" to a minute replay exactly as the live bot trades).

Why: on daily bars the live bot's entry-day stop (a real 1% stop, live all day) can only be bracketed - "stop" (checked on the close,
booked at the level: flattering), "close" (exit at the close) and "intraday" (any touch of the day's range: worst case, even a low
that came BEFORE the entry). Minute bars give the real order of events.
Data: Angel INDEX 1-minute bars (tokens 99926009 / 99926000) from 2016 - Angel keeps no minute history for expired futures, so this is
the index, not the near-month future. DATA/research/idx_*.csv.gz (downloaded for the ORB study) is copied, then topped up to yesterday.
Rules = run_live / tools/angel/tb_live.py: levels = last top / bottom of the daily CLOSE (1-day turns) known at the previous close;
buy above top + buffer, sell below bottom - buffer (Bank Nifty 25 pts both sides, Nifty 12 pts buy only); each level once; a day that
OPENS > 1% beyond a level does not trade it; entry at max(open, level); entry-day stop 1% live all day; later days the opposite system
point (max 2%), breakeven after a later day +2%; stop at the system point -> reverse (both sides). Event exits are OFF in every column
(minute and daily) so the columns compare like for like. Points per round trip, gross (Bank Nifty costs ~10 pts a round trip).
Results: DATA/research/tbmin/results.json, /api/research/tbmin/summary (statistics only, no account data)."""
import gzip
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta

VERSION = 2   # v2: v1's analysis died saving numpy year keys to JSON
HERE = os.path.dirname(os.path.abspath(__file__))
INST = {"BANKNIFTY": dict(tok="99926009", buf=25.0, long_only=False), "NIFTY": dict(tok="99926000", buf=12.0, long_only=True)}
DAY_SL, MAX_SL, BE, GAP = 1.0, 2.0, 2.0, 1.0


def _ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _quiet():
    t = _ist()
    return t.weekday() >= 5 or not ((9, 0) <= (t.hour, t.minute) <= (15, 45))


# ------------------------------------------------------------------ pure analysis (runs in a low-priority subprocess)
def load_minutes(path):
    rows = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) < 5 or len(p[0]) < 16:
                continue
            hm = p[0][11:16]
            if not ("09:15" <= hm <= "15:29"):
                continue
            try:
                rows[p[0][:16]] = (float(p[1]), float(p[2]), float(p[3]), float(p[4]))
            except ValueError:
                continue
    days = {}
    for k in sorted(rows):
        days.setdefault(k[:10], []).append((k, *rows[k]))
    return {d: v for d, v in days.items() if len(v) >= 60}         # drop special short sessions


def minute_engine(days, buf, long_only):
    """days: {date: [(time, o, h, l, c), ...]} in order. Returns closed trades (entry_day, side, entry, exit_day, exit, why)."""
    import numpy as np
    sys.path.insert(0, os.path.dirname(HERE))
    from topbottom_backtest import confirmed_swings
    D = sorted(days)
    c = np.array([days[d][-1][4] for d in D], float)
    T, B, _ = confirmed_swings(c, 0.0)
    used_T = used_B = None
    pos, ent, ent_i, be_on = 0, 0.0, -1, False
    tr = []; cur = None
    nan = lambda x: x != x  # noqa: E731
    for i in range(1, len(D)):
        bars = days[D[i]]; o = bars[0][1]
        top, bot = T[i - 1], B[i - 1]
        buy = None if nan(top) or top == used_T else top + buf
        sell = None if nan(bot) or bot == used_B else bot - buf
        prot = sys_ = None
        if pos and ent_i < i:
            prot = ent * (1 - pos * MAX_SL / 100)
            if pos > 0 and not nan(bot):
                prot = max(prot, bot - buf)
            if pos < 0 and not nan(top):
                prot = min(prot, top + buf)
            if be_on:
                prot = max(prot, ent) if pos > 0 else min(prot, ent)
            sys_ = (pos > 0 and sell is not None and abs(prot - sell) < 1e-6) or (pos < 0 and buy is not None and abs(prot - buy) < 1e-6)
        entered = False; done = False; since = None; dh, dl = -1e18, 1e18; stopped = False
        for (_, bo, bh, bl, bc) in bars:
            dh = max(dh, bh); dl = min(dl, bl)
            if done:
                continue
            if pos and not entered:
                if (pos > 0 and bl <= prot) or (pos < 0 and bh >= prot):
                    side = pos
                    px = min(o, prot) if side > 0 else max(o, prot)
                    gap_open = px != prot
                    why = ("System point" if sys_ else ("Breakeven" if be_on else "Max SL")) + (" (gap)" if gap_open else "")
                    tr.append((*cur, D[i], px, why)); pos = 0; stopped = True
                    if sys_ and not (long_only and side > 0):
                        lvl = sell if side > 0 else buy
                        if side > 0:
                            used_B = bot
                        else:
                            used_T = top
                        gapped = ((side > 0 and o < lvl) or (side < 0 and o > lvl)) and abs(o - lvl) / lvl * 100 > GAP
                        if not gapped:
                            pos, ent, ent_i, be_on = -side, px, i, False; cur = (D[i], -side, px); entered = True; since = [px, px]
                            continue
                    done = True
                continue
            if pos and entered:
                since = [max(since[0], bh), min(since[1], bl)]
                stop = ent * (1 - pos * DAY_SL / 100)
                if (pos > 0 and since[1] <= stop) or (pos < 0 and since[0] >= stop):
                    tr.append((*cur, D[i], stop, "Entry-day SL")); pos = 0; done = True
                continue
            if not pos:
                go_l = buy is not None and dh >= buy
                go_s = (not long_only) and sell is not None and dl <= sell
                if go_l and go_s:
                    go_l = abs(o - buy) <= abs(o - sell); go_s = not go_l
                if go_l:
                    used_T = top
                    if o > buy and (o - buy) / buy * 100 > GAP:
                        done = True; continue
                    px = max(o, buy); pos, ent, ent_i, be_on = 1, px, i, False; cur = (D[i], 1, px); entered = True; since = [px, px]; continue
                elif go_s:
                    used_B = bot
                    if o < sell and (sell - o) / sell * 100 > GAP:
                        done = True; continue
                    px = min(o, sell); pos, ent, ent_i, be_on = -1, px, i, False; cur = (D[i], -1, px); entered = True; since = [px, px]; continue
        if pos and not entered and not stopped:
            fav = (dh - ent) / ent * 100 if pos > 0 else (ent - dl) / ent * 100
            if fav >= BE:
                be_on = True
    return tr, (cur if pos else None)


def analyse(dirp):
    import pandas as pd
    sys.path.insert(0, os.path.dirname(HERE))
    import topbottom_backtest as tbb
    out = dict(version=VERSION, built=_ist().isoformat(timespec="minutes"), method=__doc__.split("\n\n")[0][:300], inst={})
    for name, cfg in INST.items():
        p = os.path.join(dirp, f"idx_{name}.csv.gz")
        if not os.path.exists(p):
            continue
        days = load_minutes(p)
        D = sorted(days)
        tr, op = minute_engine(days, cfg["buf"], cfg["long_only"])
        df = pd.DataFrame([(days[d][0][1], max(b[2] for b in days[d]), min(b[3] for b in days[d]), days[d][-1][4]) for d in D],
                          columns=["Open", "High", "Low", "Close"], index=pd.to_datetime(D))
        res = dict(first=D[0], last=D[-1], days=len(D), years={}, open=op)
        def add(lab, rows):
            for ed, ex_day, pts in rows:
                y = res["years"].setdefault(ex_day[:4], {})
                y[lab] = y.get(lab, 0) + pts; y[lab + "_n"] = y.get(lab + "_n", 0) + 1
                y[lab + "_w"] = y.get(lab + "_w", 0) + (pts > 0)
        add("minute", [(t[0], t[3], t[1] * (t[4] - t[2])) for t in tr])
        for fill in ("stop", "close", "intraday"):
            t = tbb.run_live(df, tbb.Params(buffer_pts=cfg["buf"], buffer_pct=None, day_sl_fill=fill, event_exit=False, gap_pct=GAP,
                                            long_only=cfg["long_only"]))
            t = t[~t.Open]
            add(fill, [(str(r.EntryDate)[:10], str(r.ExitDate)[:10], (1 if r.Side == "BUY" else -1) * (r.Exit - r.Entry)) for r in t.itertuples()])
        for y in res["years"].values():
            for k in list(y):
                if isinstance(y[k], float):
                    y[k] = round(y[k], 1)
        res["avg_close"] = {str(int(y)): round(float(v), 0) for y, v in df.Close.groupby(df.index.year).mean().items()}
        res["last_trades"] = [dict(entry_day=t[0], side="BUY" if t[1] > 0 else "SELL", entry=round(t[2], 2), exit_day=t[3], exit=round(t[4], 2),
                                   why=t[5], pts=round(t[1] * (t[4] - t[2]), 1)) for t in tr[-40:]]
        out["inst"][name] = res
    return json.loads(json.dumps(out, default=lambda o: o.item() if hasattr(o, "item") else str(o)))   # numpy -> plain numbers


# ------------------------------------------------------------------ server job
class TbMinBT:
    def __init__(self, broker, data_dir, log=print):
        self.b, self.log = broker, log
        self.src = os.path.join(data_dir, "research")
        self.dir = os.path.join(data_dir, "research", "tbmin"); os.makedirs(self.dir, exist_ok=True)
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

    def _last_day(self, path):
        last = None
        try:
            with gzip.open(path, "rt") as f:
                for line in f:
                    if len(line) >= 10:
                        last = line[:10] if (last is None or line[:10] > last) else last
        except Exception:  # noqa: BLE001
            return None
        return last

    def _fetch(self, name, tok, path, start):
        d = start; end = _ist().date() - timedelta(days=1); got = 0
        while d <= end:
            while not _quiet():
                self.st["progress"] = f"paused for market hours ({name})"; self._save(); time.sleep(300)
            d1 = min(end, d + timedelta(days=29))
            api = self.b._session()
            try:
                r = self.b._call(api.getCandleData, dict(exchange="NSE", symboltoken=tok, interval="ONE_MINUTE",
                                                         fromdate=d.strftime("%Y-%m-%d 09:15"), todate=d1.strftime("%Y-%m-%d 15:30")), tries=3) or {}
                rows = self.b._data(r) or []
            except Exception as ex:  # noqa: BLE001
                self.log("tbmin_fetch_error", name=name, error=str(ex)[:160]); time.sleep(10)
                self.st["errors"] = self.st.get("errors", 0) + 1
                if self.st["errors"] > 60:
                    raise
                continue
            if rows:
                with gzip.open(path, "at") as f:
                    for x in rows:
                        f.write(f"{str(x[0])[:16]},{x[1]},{x[2]},{x[3]},{x[4]},{x[5] if len(x) > 5 else 0}\n")
                got += len(rows)
            self.st["progress"] = f"{name} minutes to {d1}"; self._save()
            d = d1 + timedelta(days=1); time.sleep(0.6)
        return got

    def _run(self):
        try:
            for name, cfg in INST.items():
                path = os.path.join(self.dir, f"idx_{name}.csv.gz")
                if not os.path.exists(path):
                    srcp = os.path.join(self.src, f"idx_{name}.csv.gz")
                    if os.path.exists(srcp):
                        shutil.copy(srcp, path)
                last = self._last_day(path) if os.path.exists(path) else None
                start = date.fromisoformat(last) + timedelta(days=1) if last else date(2016, 1, 1)
                self.st["progress"] = f"{name}: data to {last or 'none'}, fetching from {start}"; self._save()
                n = self._fetch(name, cfg["tok"], path, start)
                self.st.setdefault("fetched", {})[name] = dict(had_to=last, new_rows=n)
            self.st["progress"] = "analysing"; self._save()
            out = os.path.join(self.dir, "results.tmp.json")
            code = f"import sys, json; sys.path.insert(0, {HERE!r}); import tb_min_bt as m; json.dump(m.analyse({self.dir!r}), open({out!r}, 'w'))"
            cmd = [sys.executable, "-c", code]
            if os.name == "posix":
                cmd = ["nice", "-n", "19"] + cmd
            r = subprocess.run(cmd, timeout=3 * 3600, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"analysis failed (exit {r.returncode}): " + (r.stderr or "")[-600:])
            os.replace(out, os.path.join(self.dir, "results.json"))
            self.st.update(state="done", finished=_ist().isoformat(timespec="minutes"), progress="done", version=VERSION)
        except Exception as ex:  # noqa: BLE001
            self.st.update(state="error", progress=str(ex)[:800]); self.log("tbmin_error", error=str(ex)[:200])
        self._save()
