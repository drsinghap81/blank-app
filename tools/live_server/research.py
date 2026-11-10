"""Intraday research on the server (10 Nov 2026): Opening Range Breakout (ORB) tests on Angel's own 1-minute / 5-minute history.

Why on the server: only the server holds the Angel login, and the research sandbox can't reach it - so the server downloads the
candles (outside market hours, ~2 requests a second, resumable) and runs the tests itself; the app shows the summary.

Data (DATA/research/):
  idx_NIFTY.csv.gz, idx_BANKNIFTY.csv.gz  - index 1-minute bars from 2016 (Angel tokens 99926000 / 99926009)
  stk_<SYM>.csv.gz                        - Nifty 100 stocks, 5-minute bars from 2019 (data/universe/nifty50 + niftynext50)
Tests (pure Python, no numpy/pandas):
  A. Index ORB: range = first 5 / 15 / 30 minutes from 09:15. First 1-minute close beyond the range -> enter at that close in the
     break direction; stop = the other side of the range; exit 15:15 close, or at a 1R / 2R target. One trade a day.
     Control: the same entry time and stop distance in a RANDOM direction (seeded) - the edge is the difference.
  B. First-candle rule (Zarattini & Aziz): direction of the first 5-minute candle, enter at the next bar's open, stop at the other
     side of that candle, target 10R or exit 15:15.
  C. Stocks in play: each day the 10 Nifty 100 stocks with the highest first-15-minute volume vs their own 14-day average
     (relative volume >= 1). 15-minute range; green first candle -> buy-stop at the range high, red -> sell-stop at the low
     (shorts = intraday); stop 10% of the 14-day ATR (paper) or the other side of the range; exit 15:20. Equal 1% risk per trade.
Costs: index futures 0.02% of price + 1 pt (Nifty) / 3 pts (Bank Nifty) slippage round trip; stocks intraday 0.15% round trip
(charges + slippage).
  D. Intraday base breakout (11 Nov 2026): see intraday_base() - 5- and 15-minute tight bases broken on 2x volume, with daily-trend
     and in-play filters and a random-time control.
Results in R (multiples of the risk) net of costs, by year and 2016-20 / 2021-23 / 2024-26."""
import gzip
import json
import os
import random
import threading
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
IDX = {"NIFTY": "99926000", "BANKNIFTY": "99926009"}
CHUNK = {"ONE_MINUTE": 30, "FIVE_MINUTE": 100}


def _ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _quiet():
    """market hours (Mon-Fri 09:00-15:45 IST) are left to trading."""
    t = _ist()
    return t.weekday() >= 5 or not ((9, 0) <= (t.hour, t.minute) <= (15, 45))


def universe():
    out = []
    for f in ("nifty50.csv", "niftynext50.csv"):
        p = os.path.join(HERE, "..", "..", "data", "universe", f)
        try:
            for i, line in enumerate(open(p)):
                if i == 0:
                    continue
                s = line.split(",")[0].strip().strip('"')
                if s and s not in out:
                    out.append(s)
        except Exception:  # noqa: BLE001
            pass
    return out


class Job:
    def __init__(self, broker, data_dir, log=print):
        self.b, self.dir, self.log = broker, os.path.join(data_dir, "research"), log
        os.makedirs(self.dir, exist_ok=True)
        self.state_p = os.path.join(self.dir, "orb_state.json")
        self.st = self._load(self.state_p, dict(state="idle", done={}, errors=0, progress="", started=None, finished=None))
        self.thread = None

    @staticmethod
    def _load(p, d):
        try:
            return json.load(open(p))
        except Exception:  # noqa: BLE001
            return d

    def _save(self):
        json.dump(self.st, open(self.state_p, "w"))

    def status(self):
        r = self._load(os.path.join(self.dir, "orb_results.json"), None)
        return dict(self.st, results=r)

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self.st.update(state="running", started=_ist().isoformat(timespec="minutes"), finished=None, errors=0); self._save()
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()
        return True

    # ------------------------------------------------------------------ download
    def _candles(self, token, interval, d0, d1):
        api = self.b._session()
        r = self.b._call(api.getCandleData, dict(exchange="NSE", symboltoken=str(token), interval=interval,
                                                 fromdate=d0.strftime("%Y-%m-%d 09:15"), todate=d1.strftime("%Y-%m-%d 15:30")), tries=2) or {}
        return self.b._data(r) or []

    def _fetch(self, key, token, interval, start):
        path = os.path.join(self.dir, key + ".csv.gz")
        last = self.st["done"].get(key)
        d = date.fromisoformat(last) + timedelta(days=1) if last else start
        end = _ist().date() - timedelta(days=1)
        while d <= end:
            while not _quiet():
                self.st["progress"] = f"paused for market hours ({key})"; self._save(); time.sleep(300)
            d1 = min(end, d + timedelta(days=CHUNK[interval] - 1))
            try:
                rows = self._candles(token, interval, d, d1)
            except Exception as ex:  # noqa: BLE001
                self.st["errors"] += 1; self.log("research_fetch_error", key=key, error=str(ex)[:160]); time.sleep(5)
                if self.st["errors"] > 200:
                    raise
                continue
            if rows:
                with gzip.open(path, "at") as f:
                    for x in rows:
                        f.write(f"{str(x[0])[:16]},{x[1]},{x[2]},{x[3]},{x[4]},{x[5] if len(x) > 5 else 0}\n")
            self.st["done"][key] = d1.isoformat(); self.st["progress"] = f"{key} to {d1}"; self._save()
            d = d1 + timedelta(days=1); time.sleep(0.5)

    def _run(self):
        try:
            for name, tok in IDX.items():
                self._fetch("idx_" + name, tok, "ONE_MINUTE", date(2016, 1, 1))
            for s in universe():
                try:
                    _, t = self.b._ts(s)
                except Exception:  # noqa: BLE001
                    continue
                self._fetch("stk_" + s, t["token"], "FIVE_MINUTE", date(2019, 1, 1))
            self.st["progress"] = "analysing"; self._save()
            res = analyse(self.dir)
            json.dump(res, open(os.path.join(self.dir, "orb_results.json"), "w"))
            self.st.update(state="done", finished=_ist().isoformat(timespec="minutes"), progress="done")
        except Exception as ex:  # noqa: BLE001
            self.st.update(state="error", progress=str(ex)[:200]); self.log("research_error", error=str(ex)[:200])
        self._save()


# ------------------------------------------------------------------ analysis
def days(path):
    """-> list of (date, [(hhmm, o, h, l, c, v), ...]) in time order, duplicates dropped."""
    D = {}
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) < 6:
                    continue
                ts = p[0]; dd, hm = ts[:10], ts[11:16]
                D.setdefault(dd, {})[hm] = (hm, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5] or 0))
    except (OSError, EOFError):
        pass
    return [(k, [v[h] for h in sorted(v)]) for k, v in sorted(D.items())]


def _stats(R, years):
    if not R:
        return dict(n=0)
    w = [r for r in R if r > 0]; L = -sum(r for r in R if r <= 0)
    by = {}
    for y, r in zip(years, R):
        by.setdefault(y, []).append(r)
    per = lambda a, b: round(sum(sum(v) for y, v in by.items() if a <= y <= b) / max(1, sum(len(v) for y, v in by.items() if a <= y <= b)), 3)  # noqa: E731
    return dict(n=len(R), win=round(100 * len(w) / len(R), 1), avgR=round(sum(R) / len(R), 3), pf=round(sum(w) / L, 2) if L else None,
                sumR=round(sum(R), 1), y16_20=per(2016, 2020), y21_23=per(2021, 2023), y24_26=per(2024, 2026),
                by_year={y: round(sum(v), 1) for y, v in sorted(by.items())})


def index_orb(D, mins, tgt, slip_pts, rnd=None):
    """D from days() of an index; returns (R list, years)."""
    R, Y = [], []
    end_or = (9 * 60 + 15 + mins)
    for dd, bars in D:
        if len(bars) < 200:
            continue
        hm = lambda b: int(b[0][:2]) * 60 + int(b[0][3:5])  # noqa: E731
        orb = [b for b in bars if hm(b) < end_or]; rest = [b for b in bars if end_or <= hm(b) <= 15 * 60 + 15]
        if not orb or not rest:
            continue
        hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
        if hi <= lo:
            continue
        ent = None
        for i, b in enumerate(rest):
            if b[4] > hi or b[4] < lo:
                side = 1 if b[4] > hi else -1
                if rnd is not None:
                    side = rnd.choice((1, -1))
                e = b[4]; stop = lo if side > 0 else hi
                if rnd is not None:
                    stop = e - side * (hi - lo)
                ent = (i, side, e, stop); break
        if not ent:
            continue
        i, side, e, stop = ent; risk = abs(e - stop)
        if risk <= 0:
            continue
        T = e + side * tgt * risk if tgt else None; x = rest[-1][4]
        for b in rest[i + 1:]:
            if (side > 0 and b[3] <= stop) or (side < 0 and b[2] >= stop):
                x = stop; break
            if T is not None and ((side > 0 and b[2] >= T) or (side < 0 and b[3] <= T)):
                x = T; break
        cost = 0.0002 * e + slip_pts
        R.append(((x - e) * side - cost) / risk); Y.append(int(dd[:4]))
    return R, Y


def sweep_orb(D, mins, mode, tgt, slip_pts, rnd=None, back=10):
    """Liquidity sweep around the opening range (Amritpal, 10 Nov 2026). A sweep = a 1-minute bar trades beyond one side of the
    range, then within `back` bars price closes back inside it.
    mode 'reverse' (A): after a sweep of one side, enter on the first close beyond the OTHER side; stop = the sweep extreme.
    mode 'second' (B): after a sweep and the move back, enter on the next close beyond the SAME side; stop = the extreme of the
    move in between. Exit 15:15 or at `tgt` R. One trade a day. rnd -> random direction, same entry and stop distance."""
    R, Y = [], []
    end_or = 9 * 60 + 15 + mins
    for dd, bars in D:
        if len(bars) < 200:
            continue
        hm = lambda b: int(b[0][:2]) * 60 + int(b[0][3:5])  # noqa: E731
        orb = [b for b in bars if hm(b) < end_or]; rest = [b for b in bars if end_or <= hm(b) <= 15 * 60 + 15]
        if not orb or len(rest) < 30:
            continue
        hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
        if hi <= lo:
            continue
        sw = None                                   # (side swept: +1 high / -1 low, index where back inside, sweep extreme)
        for i, b in enumerate(rest):
            if b[2] > hi or b[3] < lo:
                side = 1 if b[2] > hi else -1; ext = b[2] if side > 0 else b[3]
                for j in range(i, min(len(rest), i + back)):
                    ext = max(ext, rest[j][2]) if side > 0 else min(ext, rest[j][3])
                    if lo <= rest[j][4] <= hi:
                        sw = (side, j, ext); break
                break                               # only the day's first poke counts
        if not sw:
            continue
        side, j0, ext = sw; ent = None; mid_ext = None
        for k in range(j0 + 1, len(rest)):
            b = rest[k]
            if mode == "reverse":
                if (side > 0 and b[4] < lo) or (side < 0 and b[4] > hi):
                    ent = (k, -side, b[4], ext * (1 + 0.0002 * side)); break
            else:
                x_ = b[3] if side > 0 else b[2]            # low of the pull-back (high-side sweep) / high of the bounce
                mid_ext = x_ if mid_ext is None else (min(mid_ext, x_) if side > 0 else max(mid_ext, x_))
                if (side > 0 and b[4] > hi) or (side < 0 and b[4] < lo):
                    ent = (k, side, b[4], mid_ext); break
        if not ent:
            continue
        k, d_, e, stop = ent
        if rnd is not None:
            dist = abs(e - stop); d_ = rnd.choice((1, -1)); stop = e - d_ * dist
        risk = abs(e - stop)
        if risk <= 0 or (d_ > 0 and stop >= e) or (d_ < 0 and stop <= e):
            continue
        T = e + d_ * tgt * risk if tgt else None; x = rest[-1][4]
        for b in rest[k + 1:]:
            if (d_ > 0 and b[3] <= stop) or (d_ < 0 and b[2] >= stop):
                x = stop; break
            if T is not None and ((d_ > 0 and b[2] >= T) or (d_ < 0 and b[3] <= T)):
                x = T; break
        R.append(((x - e) * d_ - (0.0002 * e + slip_pts)) / risk); Y.append(int(dd[:4]))
    return R, Y


def agg5(D):
    """1-minute day lists -> one continuous list of 5-minute bars (date, hhmm, o, h, l, c)."""
    out = []
    for dd, bars in D:
        g = {}
        for b in bars:
            m = int(b[0][:2]) * 60 + int(b[0][3:5]); k = m - (m - 555) % 5          # buckets from 09:15
            g.setdefault(k, []).append(b)
        for k in sorted(g):
            x = g[k]; out.append((dd, f"{k // 60:02d}:{k % 60:02d}", x[0][1], max(y[2] for y in x), min(y[3] for y in x), x[-1][4]))
    return out


def sma_cross(B, slip_pts, stopm="candle", exitm="cross", fast=20, slow=200, wait=12, rnd=None):
    """Amritpal 10 Nov 2026: on 5-minute bars, SMA20 crosses below SMA200 -> the first candle (within `wait` bars) that CLOSES
    below the crossing level is the signal; short on a break of its low (next bars, within `wait`). Mirror for longs.
    Crossing level = the average of the two SMAs on the cross bar. Stop: 'candle' = signal candle high (low for longs) or
    'sma' = SMA200 at entry. Exit: 'cross' = the opposite SMA cross (held overnight, futures) or 'eod' = 15:15 the same day;
    the stop always applies. One position at a time."""
    c = [b[5] for b in B]; n = len(c); R, Y = [], []
    def sma(k, i):
        return sum(c[i - k + 1:i + 1]) / k if i >= k - 1 else None
    f = [sma(fast, i) for i in range(n)]; sl = [sma(slow, i) for i in range(n)]
    i = slow + 1
    while i < n - 2:
        if f[i - 1] is None or sl[i - 1] is None:
            i += 1; continue
        up = f[i - 1] <= sl[i - 1] and f[i] > sl[i]; dn = f[i - 1] >= sl[i - 1] and f[i] < sl[i]
        if not (up or dn):
            i += 1; continue
        side = 1 if up else -1; lvl = (f[i] + sl[i]) / 2; sig = None
        for j in range(i, min(n - 1, i + wait)):
            if (side > 0 and c[j] > lvl) or (side < 0 and c[j] < lvl):
                sig = j; break
        if sig is None:
            i += 1; continue
        trig = B[sig][3] if side > 0 else B[sig][4]; ent = None
        for k in range(sig + 1, min(n, sig + 1 + wait)):
            if exitm == "eod" and (B[k][0] != B[sig][0] or B[k][1] > "15:10"):
                break
            if (side > 0 and B[k][3] > trig) or (side < 0 and B[k][4] < trig):
                e = max(B[k][2], trig) if side > 0 else min(B[k][2], trig); ent = (k, e); break
        if ent is None:
            i = sig + 1; continue
        k, e = ent
        d_ = side if rnd is None else rnd.choice((1, -1))
        stop = (B[sig][4] if side > 0 else B[sig][3]) if stopm == "candle" else sl[k]
        dist = abs(e - stop)
        if rnd is not None or (d_ > 0 and stop >= e) or (d_ < 0 and stop <= e):
            stop = e - d_ * dist
        if dist <= 0:
            i = k + 1; continue
        x = None; m = k
        while m < n - 1:
            m += 1; b = B[m]
            if (d_ > 0 and b[4] <= stop) or (d_ < 0 and b[3] >= stop):
                x = min(b[2], stop) if d_ > 0 else max(b[2], stop); break
            if exitm == "eod" and (b[0] != B[k][0] or b[1] >= "15:15"):
                x = b[5] if b[0] == B[k][0] else B[m - 1][5]; break
            if exitm == "cross" and f[m] is not None and ((side > 0 and f[m] < sl[m]) or (side < 0 and f[m] > sl[m])):
                x = b[5]; break
        if x is None:
            x = c[-1]
        R.append(((x - e) * d_ - (0.0002 * e + slip_pts)) / dist); Y.append(int(B[k][0][:4]))
        i = m + 1
    return R, Y


def first_candle(D, slip_pts, tgt=10.0):
    R, Y = [], []
    for dd, bars in D:
        five = [b for b in bars if b[0] < "09:20"]; rest = [b for b in bars if "09:20" <= b[0] <= "15:15"]
        if len(five) < 3 or len(rest) < 100:
            continue
        o, c = five[0][1], five[-1][4]; hi, lo = max(b[2] for b in five), min(b[3] for b in five)
        if c == o or hi <= lo:
            continue
        side = 1 if c > o else -1; e = rest[0][1]; stop = lo if side > 0 else hi; risk = (e - stop) * side
        if risk <= 0:
            continue
        T = e + side * tgt * risk; x = rest[-1][4]
        for b in rest:
            if (side > 0 and b[3] <= stop) or (side < 0 and b[2] >= stop):
                x = stop; break
            if (side > 0 and b[2] >= T) or (side < 0 and b[3] <= T):
                x = T; break
        R.append(((x - e) * side - (0.0002 * e + slip_pts)) / risk); Y.append(int(dd[:4]))
    return R, Y


def stocks_in_play(dirp, top=10, stopm="atr"):
    """5-minute stock bars -> per-day candidates with relative volume of the first 15 minutes."""
    by_day = {}
    for fn in sorted(os.listdir(dirp)):
        if not fn.startswith("stk_"):
            continue
        D = days(os.path.join(dirp, fn)); vol_hist, tr_hist, prev_c = [], [], None
        for dd, bars in D:
            if len(bars) < 60:
                prev_c = bars[-1][4] if bars else prev_c; continue
            fst = [b for b in bars if b[0] < "09:30"]; rest = [b for b in bars if "09:30" <= b[0] <= "15:20"]
            v15 = sum(b[5] for b in fst)
            H, L_, C = max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4]
            tr = max(H - L_, abs(H - prev_c), abs(L_ - prev_c)) if prev_c else H - L_
            if len(vol_hist) >= 14 and len(tr_hist) >= 14 and fst and rest and v15 > 0:
                rv = v15 / (sum(vol_hist[-14:]) / 14); atr = sum(tr_hist[-14:]) / 14
                by_day.setdefault(dd, []).append((rv, fn[4:-7], fst, rest, atr))
            vol_hist.append(v15); tr_hist.append(tr); prev_c = C
    R, Y = [], []
    for dd in sorted(by_day):
        C_ = sorted([x for x in by_day[dd] if x[0] >= 1.0], key=lambda x: -x[0])[:top]
        for rv, sym, fst, rest, atr in C_:
            o, c = fst[0][1], fst[-1][4]; hi, lo = max(b[2] for b in fst), min(b[3] for b in fst)
            if c == o or hi <= lo:
                continue
            side = 1 if c > o else -1; lvl = hi if side > 0 else lo; ent = None
            for i, b in enumerate(rest):
                if (side > 0 and b[2] >= lvl) or (side < 0 and b[3] <= lvl):
                    ent = (i, max(b[1], lvl) if side > 0 else min(b[1], lvl)); break
            if not ent:
                continue
            i, e = ent
            stop = e - side * 0.1 * atr if stopm == "atr" else (lo if side > 0 else hi)
            risk = abs(e - stop)
            if risk <= 0:
                continue
            x = rest[-1][4]
            for b in rest[i:]:
                if (side > 0 and b[3] <= stop) or (side < 0 and b[2] >= stop):
                    x = stop; break
            cost = e * 0.0015                                  # intraday cash: ~0.05% charges + 0.05% slippage a side
            R.append(((x - e) * side - cost) / risk); Y.append(int(dd[:4]))
    return R, Y



# ------------------------------------------------------------------ intraday base breakout (11 Nov 2026)
VERSION = 2
BASE = {5: dict(n=8, w=0.006), 15: dict(n=6, w=0.010)}   # tight base: the last n bars within w of price
VOLX, TGT, COST = 2.0, 2.0, 0.0015                        # breakout bar volume >= 2x the base's average; 2R target; 0.15% round trip


def _agg(bars, k):
    if k == 1:
        return bars
    out = []
    for i in range(0, len(bars), k):
        g = bars[i:i + k]
        out.append((g[0][0], g[0][1], max(b[2] for b in g), min(b[3] for b in g), g[-1][4], sum(b[5] for b in g)))
    return out


def _sim(B, j, side, e, stop, tgt):
    """Enter at B[j] open (e); stop first if both are touched in one bar; exit 15:15 close otherwise."""
    risk = abs(e - stop); t = e + side * tgt * risk if tgt else None; x = B[-1][4]
    for b in B[j:]:
        if (side > 0 and b[3] <= stop) or (side < 0 and b[2] >= stop):
            x = min(b[1], stop) if side > 0 else max(b[1], stop); break
        if t is not None and ((side > 0 and b[2] >= t) or (side < 0 and b[3] <= t)):
            x = max(b[1], t) if side > 0 else min(b[1], t); break
        if b[0] >= "15:15":
            x = b[4]; break
    return ((x - e) * side - e * COST) / risk


def intraday_base(dirp, rnd=None):
    """Tight intraday base (5- or 15-minute bars, from 09:45) broken by a bar that CLOSES beyond it on 2x volume -> enter at the
    next bar's open, stop = the other side of the base, exit 2R or 15:15 (and an exit-at-15:15-only version). First signal per stock,
    side and day. Filters: trend = yesterday's daily close above (long) / below (short) its daily EMA 21; in play = first-15-minute
    volume >= 2x its 14-day average. Control: the same trades at a random bar of the same day (same side, same stop distance)."""
    acc = {}
    rr = random.Random(11)
    def put(k, r, y):
        a = acc.setdefault(k, ([], [])); a[0].append(r); a[1].append(y)
    for fn in sorted(os.listdir(dirp)):
        if not fn.startswith("stk_"):
            continue
        D = days(os.path.join(dirp, fn)); ema = None; prev_c = None; v15h = []
        for dd, bars in D:
            if len(bars) < 60:
                continue
            y = int(dd[:4]); v15 = sum(b[5] for b in bars if b[0] < "09:30")
            trend = 0 if ema is None or prev_c is None else (1 if prev_c > ema else -1)
            inplay = len(v15h) >= 14 and v15 > 0 and v15 >= 2 * sum(v15h[-14:]) / 14
            for tf, cfg in BASE.items():
                B = _agg(bars, tf // 5); n, w = cfg["n"], cfg["w"]; done = set()
                elig = [j for j in range(1, len(B)) if "09:45" <= B[j - 1][0] <= "14:30"]
                for i in range(n, len(B) - 1):
                    if B[i][0] < "09:45" or B[i][0] > "14:30":
                        continue
                    base = B[i - n:i]; bh = max(b[2] for b in base); bl = min(b[3] for b in base); c0 = base[-1][4]
                    if (bh - bl) / c0 > w:
                        continue
                    va = sum(b[5] for b in base) / n
                    if va <= 0 or B[i][5] < VOLX * va:
                        continue
                    side = 1 if B[i][4] > bh else -1 if B[i][4] < bl else 0
                    if not side or side in done:
                        continue
                    e = B[i + 1][1]; stop = bl if side > 0 else bh
                    if (e - stop) * side <= 0.002 * e:
                        continue
                    done.add(side); sd = 'long' if side > 0 else 'short'
                    fl = ['all'] + (['trend'] if trend == side else []) + (['inplay'] if inplay else []) + (['trend_inplay'] if trend == side and inplay else [])
                    j0 = rr.choice(elig) if elig else i + 1; e0 = B[j0][1]; d = abs(e - stop)
                    for ex, tg in (('2R', TGT), ('eod', None)):
                        r = _sim(B, i + 1, side, e, stop, tg)
                        rc = _sim(B, j0, side, e0, e0 - side * d, tg) if d > 0 else None
                        for f in fl:
                            put(f"base{tf}_{sd}_{f}_{ex}", r, y)
                            if rc is not None:
                                put(f"base{tf}_{sd}_{f}_{ex}_random", rc, y)
            c = bars[-1][4]; prev_c = c; ema = c if ema is None else ema + (c - ema) * 2 / 22; v15h.append(v15)
    return {k: _stats(*v) for k, v in sorted(acc.items())}

def analyse(dirp):
    out = dict(generated=_ist().isoformat(timespec="minutes"), version=VERSION, index={}, stocks={})
    for name, slip in (("NIFTY", 1.0), ("BANKNIFTY", 3.0)):
        D = days(os.path.join(dirp, f"idx_{name}.csv.gz"))
        if not D:
            continue
        r = dict(first_day=D[0][0], last_day=D[-1][0], days=len(D))
        for mins in (5, 15, 30):
            for tgt in (None, 1.0, 2.0):
                k = f"orb{mins}_{'eod' if tgt is None else str(int(tgt)) + 'R'}"
                r[k] = _stats(*index_orb(D, mins, tgt, slip))
                r[k + "_random"] = _stats(*index_orb(D, mins, tgt, slip, rnd=random.Random(7)))
        r["first5_10R"] = _stats(*first_candle(D, slip))
        B = agg5(D)
        for stopm in ("candle", "sma"):
            for exitm in ("cross", "eod"):
                k = f"sma20x200_{stopm}_{exitm}"
                r[k] = _stats(*sma_cross(B, slip, stopm, exitm))
                r[k + "_random"] = _stats(*sma_cross(B, slip, stopm, exitm, rnd=random.Random(7)))
        for mins in (5, 15, 30):
            for mode in ("reverse", "second"):
                for tgt in (None, 2.0):
                    k = f"sweep_{mode}{mins}_{'eod' if tgt is None else '2R'}"
                    r[k] = _stats(*sweep_orb(D, mins, mode, tgt, slip))
                    r[k + "_random"] = _stats(*sweep_orb(D, mins, mode, tgt, slip, rnd=random.Random(7)))
        out["index"][name] = r
    for top in (10, 20):
        for stopm in ("atr", "range"):
            out["stocks"][f"top{top}_{stopm}"] = _stats(*stocks_in_play(dirp, top, stopm))
    out["base"] = intraday_base(dirp)
    return out
