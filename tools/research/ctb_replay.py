"""Trial run (29 Nov 2026): the server's CoinDCX BTC/ETH Top Bottom bot (tools/live_server/crypto_tb.py) replayed minute by minute over
the last DAYS days of REAL CoinDCX futures 1-minute candles, exactly as it runs live (clock stepped every 10 minutes), starting flat.
Compared with the backtest engine on CoinDCX daily candles (run_live, entry-day stop "intraday" and "stop"). Prints R| lines."""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); T0 = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(T0, "live_server")); sys.path.insert(0, T0)
import crypto_tb as ct  # noqa: E402
import topbottom_backtest as tbb  # noqa: E402

DAYS = int(os.environ.get("DAYS", "60"))
real = ct.DCX("/nonexistent")
NOW = int(time.time()); DAY0 = (NOW // 86400 - DAYS) * 86400


class Fake:
    def __init__(self):
        self.d, self.m = {}, {}

    def load(self, pair):
        self.d[pair] = real.candles(pair, "1D", NOW - 700 * 86400, NOW)
        rows = []
        for t in range(DAY0, NOW, 86400):
            for k in range(3):
                try:
                    rows += real.candles(pair, "1", t, min(t + 86400 - 60, NOW)); break
                except Exception:  # noqa: BLE001
                    time.sleep(2)
        self.m[pair] = sorted(set(rows))
        print(f"R| {pair}: {len(self.d[pair])} daily, {len(self.m[pair])} minute candles from {datetime.fromtimestamp(DAY0, timezone.utc):%d %b}", flush=True)

    def candles(self, pair, res, t0, t1):
        if res == "1D":       # as at the clock: completed days only plus today's running candle start
            return [r for r in self.d[pair] if t0 <= r[0] <= t1]
        import bisect
        L = self.m[pair]; i = bisect.bisect_left(L, (int(t0),)); out = []
        while i < len(L) and L[i][0] <= t1:
            out.append(L[i]); i += 1
        return out

    def usdtinr(self):
        return 90.0

    def has_keys(self):
        return False


F = Fake()
for c, p in ct.PAIRS.items():
    F.load(p)
clock = {"t": DAY0 + 30}
ct.time.time = lambda: clock["t"]
ct.utcnow = lambda: datetime.fromtimestamp(clock["t"], timezone.utc)
job = ct.CryptoTB(tempfile.mkdtemp(), dcx=F)
while clock["t"] < NOW - 120:
    clock["t"] = min(clock["t"] + 600, NOW - 120); job.run_once()
    if job.last_error:
        print("R| error", job.last_error, flush=True); break
st = job.status()
start = datetime.fromtimestamp(DAY0, timezone.utc).strftime("%Y-%m-%d")
for coin, C in st["coins"].items():
    print(f"R| ===== {coin} (CoinDCX {ct.PAIRS[coin]}), replay {start} -> now, last {C['price']}", flush=True)
    D = F.d[ct.PAIRS[coin]]
    df = pd.DataFrame([r[1:] for r in D], columns=["Open", "High", "Low", "Close"],
                      index=pd.to_datetime([datetime.fromtimestamp(r[0], timezone.utc).replace(tzinfo=None) for r in D]))
    df = df[df.index < pd.Timestamp(datetime.now(timezone.utc).date())]
    for nm in ("both", "buy"):
        b = C["books"][nm]
        print(f"R| BOT {nm}: {b['n']} closed, {b['wins']} won, {b['ret_pct']:+.2f}% after 0.15% cost/trade"
              + (f"; open {b['pos']['side']} from {b['pos']['entry']} ({b['pos']['entry_day']}) {b['pos']['open_pct']:+.2f}%" if b['pos'] else "; flat"), flush=True)
        for t in reversed(b["trades"]):
            print(f"R|   {t['entry_day']} {t['side']:4} {t['entry']:>10.2f} -> {t['exit_day']} {t['exit']:>10.2f} {t['why_out']:<24} {t['pct']:+.2f}%", flush=True)
        for fill in ("intraday", "stop"):
            p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=nm == "buy", day_sl_pct=1, max_sl_pct=2, be_pct=2, gap_pct=1,
                           day_sl_fill=fill, start_flat_on=start)
            t = tbb.run_live(df, p); t = t[pd.to_datetime(t.EntryDate) >= pd.Timestamp(start)]; z = t[~t.Open]
            eq = 1.0
            for r in z.itertuples():
                eq *= 1 + r.Pct / 100 - 0.0015
            print(f"R| BACKTEST {nm} entry-day stop '{fill}': {len(z)} closed, {(z.Pct > 0.15).sum()} won, {(eq - 1) * 100:+.2f}%", flush=True)
print("R| notes:", flush=True)
for n in st["notes"][-25:]:
    print("R|  ", n, flush=True)
