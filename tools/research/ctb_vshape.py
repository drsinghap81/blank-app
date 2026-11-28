"""Crypto "proper V" on REAL minute data (29 Nov 2026, Amritpal: "Try V shape here"). Rules 1/2/2 (live). Variants: minimum turn SWING %
(a top counts only after the close fell that % below it), and the course V rule (move into the turn < VLEG % -> buffer + 0.5%).
The server bot (tools/live_server/crypto_tb.py) replayed minute by minute over the last DAYS days of CoinDCX futures 1-minute candles,
once per rule set (entry-day stop / max stop / breakeven %), starting flat. Cost 0.15% a round trip. Prints R| lines."""
import bisect
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__)); T0 = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(T0, "live_server")); sys.path.insert(0, T0)
import crypto_tb as ct  # noqa: E402

DAYS = int(os.environ.get("DAYS", "365"))
SETS = [(0, None), (0.3, None), (0.5, None), (1, None), (1.5, None), (2, None), (3, None), (0, 3), (0, 2), (0, 5), (0.3, 3), (1, 3)]
real = ct.DCX("/nonexistent")
NOW = int(time.time()); DAY0 = (NOW // 86400 - DAYS) * 86400
_rt, _now = time.time, ct.utcnow


class Fake:
    def __init__(self):
        self.d, self.m = {}, {}

    def load(self, pair):
        self.d[pair] = real.candles(pair, "1D", NOW - 900 * 86400, NOW)
        rows = []
        for t in range(DAY0, NOW, 86400):
            for k in range(4):
                try:
                    rows += real.candles(pair, "1", t, min(t + 86400 - 60, NOW)); break
                except Exception:  # noqa: BLE001
                    time.sleep(3)
        self.m[pair] = sorted(set(rows))
        days = sorted({r[0] // 86400 for r in self.m[pair]})
        print(f"R| {pair}: {len(self.m[pair])} minute candles, {len(days)} days with data, first {datetime.fromtimestamp(self.m[pair][0][0], timezone.utc):%Y-%m-%d}", flush=True)

    def candles(self, pair, res, t0, t1):
        if res == "1D":
            return [r for r in self.d[pair] if t0 <= r[0] <= t1]
        L = self.m[pair]; i = bisect.bisect_left(L, (int(t0),)); out = []
        while i < len(L) and L[i][0] <= t1:
            out.append(L[i]); i += 1
        return out

    def usdtinr(self):
        return 90.0

    def has_keys(self):
        return False


F = Fake()
for p in ct.PAIRS.values():
    F.load(p)
first = max(DAY0, max(F.m[p][0][0] for p in ct.PAIRS.values()) // 86400 * 86400)
mid = first + (NOW - first) // 2
print(f"R| replay from {datetime.fromtimestamp(first, timezone.utc):%Y-%m-%d}; halves split at {datetime.fromtimestamp(mid, timezone.utc):%Y-%m-%d}", flush=True)
print("R| rule = min turn % / V rule (move into the turn under X% -> +0.5% buffer).  ret = compounded, after 0.15% cost.  dd = worst fall of the book (closed trades)", flush=True)
for sw, vl in SETS:
    ct.SWING, ct.VLEG = sw, vl
    ds, ms, be = f"swing {sw}", f"V {vl if vl else '-'}", ""
    clock = {"t": first + 30}
    ct.time.time = lambda: clock["t"]
    ct.utcnow = lambda: datetime.fromtimestamp(clock["t"], timezone.utc)
    job = ct.CryptoTB(tempfile.mkdtemp(), dcx=F)
    while clock["t"] < NOW - 120:
        clock["t"] = min(clock["t"] + 3600, NOW - 120); job.run_once()
        if job.last_error:
            print("R| error", job.last_error, flush=True); break
    ct.time.time = _rt
    for coin in ct.PAIRS:
        for nm in ("both", "buy"):
            tr = job.st["books"][f"{coin}:{nm}"]["trades"]
            def comp(ts):
                e = 1.0; pk = 1.0; dd = 0.0
                for t in ts:
                    e *= 1 + t["pct"] / 100; pk = max(pk, e); dd = min(dd, e / pk - 1)
                return (e - 1) * 100, dd * 100
            midd = datetime.fromtimestamp(mid, timezone.utc).strftime("%Y-%m-%d")
            a, dd = comp(tr); h1, _ = comp([t for t in tr if t["entry_day"] < midd]); h2, _ = comp([t for t in tr if t["entry_day"] >= midd])
            nds = sum(1 for t in tr if t["why_out"] == "Entry-day SL")
            avgw = sum(t["pct"] for t in tr if t["pct"] > 0) / max(1, sum(1 for t in tr if t["pct"] > 0))
            avgl = sum(t["pct"] for t in tr if t["pct"] <= 0) / max(1, sum(1 for t in tr if t["pct"] <= 0))
            print(f"R| {ds:9} {ms:5} {coin} {nm:4}: ret {a:+7.1f}%  (1st half {h1:+6.1f}%, 2nd half {h2:+6.1f}%)  dd {dd:6.1f}%  trades {len(tr):3}  "
                  f"won {sum(1 for t in tr if t['pct'] > 0):3}  entry-day stops {nds:3}  avg win {avgw:+.2f}% avg loss {avgl:+.2f}%", flush=True)
