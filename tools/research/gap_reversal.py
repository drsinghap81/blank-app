"""Gap reversal (28 Nov 2026, Amritpal sent a book page "The Gap Reversal": upside gap -> first-30-min opening range (OR) ->
short on a break of the OR low, stop above the OR high, target the full gap fill (prior close); mirror long on a gap down).
PILOT on Yahoo intraday (the only free history): Nifty 100 stocks (.NS)
  A) 5-minute bars, last ~60 days: OR = 09:15-09:45 (6 bars)
  B) 1-hour bars, last ~2 years: OR = the first hour (09:15-10:15) - a coarser stand-in
Entry: stop order 0.05% beyond the OR low (short) / high (long), any time after the OR until 14:30; skipped if the price
already filled the gap during the OR. Stop: OR high (short) / OR low (long). Exit: target (full gap fill, or 50% variant), stop,
else the 15:15 bar's close. Same bar hits stop and target -> stop. Cost 0.15% round trip (intraday charges + slippage).
Gap sizes 2% / 3% / 5%. Optional filter: OR closes below the open ("opening price rejected"). R = move / (stop distance)."""
import os

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); U = os.path.join(HERE, "..", "..", "data", "universe")
COST = 0.0015


def univ():
    out = []
    for f in ("nifty50.csv", "niftynext50.csv"):
        d = pd.read_csv(os.path.join(U, f)); col = next(c for c in d.columns if c.strip().lower() == "symbol")
        out += [s.strip() for s in d[col].astype(str) if s.strip() not in out]
    return out[:int(os.environ.get("LIMIT") or 0) or None]


def load(interval, period):
    S = univ(); D = {}
    for k in range(0, len(S), 25):
        chunk = [s + ".NS" for s in S[k:k + 25]]
        x = yf.download(chunk, period=period, interval=interval, group_by="ticker", progress=False, auto_adjust=False, threads=True)
        for t in chunk:
            try:
                y = x[t][["Open", "High", "Low", "Close"]].dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(y):
                y.index = pd.to_datetime(y.index).tz_convert("Asia/Kolkata").tz_localize(None); D[t[:-3]] = y
    return D


def run(D, or_bars, gap, side, tgt="full", rej=False):
    out = []
    for s, x in D.items():
        days = [g for _, g in x.groupby(x.index.date)]
        for p, g in zip(days, days[1:]):
            pc = float(p.Close.iloc[-1]); o = float(g.Open.iloc[0])
            gp = o / pc - 1
            if not ((side < 0 and gp >= gap) or (side > 0 and gp <= -gap)) or len(g) <= or_bars:
                continue
            orb = g.iloc[:or_bars]; orh, orl = float(orb.High.max()), float(orb.Low.min())
            if (side < 0 and orl <= pc) or (side > 0 and orh >= pc):
                continue                                         # gap already filled inside the OR
            if rej and ((side < 0 and orb.Close.iloc[-1] >= o) or (side > 0 and orb.Close.iloc[-1] <= o)):
                continue
            trig = orl * (1 - 0.0005) if side < 0 else orh * (1 + 0.0005); stop = orh if side < 0 else orl
            target = pc if tgt == "full" else (o + pc) / 2
            rest = g.iloc[or_bars:]; ent = None; res = None
            for t, b in rest.iterrows():
                if ent is None:
                    if t.hour * 60 + t.minute > 14 * 60 + 30:
                        break
                    if (side < 0 and b.Low <= trig) or (side > 0 and b.High >= trig):
                        ent = min(b.Open, trig) if side < 0 else max(b.Open, trig)
                        # same bar: stop first if it also reaches the stop
                        if (side < 0 and b.High >= stop) or (side > 0 and b.Low <= stop):
                            res = (stop, "stop"); break
                        if (side < 0 and b.Low <= target) or (side > 0 and b.High >= target):
                            res = (target, "target"); break
                    continue
                if (side < 0 and b.High >= stop) or (side > 0 and b.Low <= stop):
                    res = (max(b.Open, stop) if side < 0 else min(b.Open, stop), "stop"); break
                if (side < 0 and b.Low <= target) or (side > 0 and b.High >= target):
                    res = (target, "target"); break
                if t.hour * 60 + t.minute >= 15 * 60 + 15:
                    res = (float(b.Close), "close"); break
            if ent is None:
                continue
            if res is None:
                res = (float(rest.Close.iloc[-1]), "close")
            px, why = res; r = side * (px / ent - 1) - COST; risk = abs(stop / ent - 1)
            out.append(dict(sym=s, day=str(g.index[0].date()), gap=gp, ret=r, R=r / risk if risk else 0, why=why))
    return pd.DataFrame(out)


def rep(lab, t):
    if not len(t):
        print(f"R| {lab:46s} n 0", flush=True); return
    m = t.groupby("day").ret.mean()          # equal weight per day, to read as a portfolio
    print(f"R| {lab:46s} n {len(t):4d} days {len(m):3d} win {(t.ret > 0).mean() * 100:3.0f}% avg {t.ret.mean() * 100:+.2f}%"
          f" {t.R.mean():+.2f}R target {(t.why == 'target').mean() * 100:3.0f}% stop {(t.why == 'stop').mean() * 100:3.0f}% | per-day avg {m.mean() * 100:+.2f}%", flush=True)


def main():
    for lab, iv, per, orb in (("5-min, 60 days, OR 30 min", "5m", "60d", 6), ("1-hour, 2 years, OR 1 hour", "60m", "730d", 1)):
        D = load(iv, per); print(f"R| ===== {lab}: {len(D)} stocks", flush=True)
        for side, nm in ((-1, "SHORT gap-up"), (1, "LONG gap-down")):
            for gap in (0.02, 0.03, 0.05):
                for tgt in ("full", "half"):
                    rep(f"{nm} >={gap * 100:.0f}% target {tgt}", run(D, orb, gap, side, tgt))
                rep(f"{nm} >={gap * 100:.0f}% full + open rejected", run(D, orb, gap, side, "full", True))


if __name__ == "__main__":
    main()
