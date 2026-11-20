"""Industry rotation swing trades (20 Nov 2026, Amritpal: "ride the wave in rotation with short-term swing trading - buy as a basket
and exit when it turns down"). NSE official basic industries (3+ liquid stocks, today's members), equal-weight daily index each,
vs Nifty 50. Signals on the daily close, trade at the NEXT close; 0.20% cost per round trip; at most 5 baskets at once (20% each,
the rest in cash); when more signals than free slots, the strongest daily RS-momentum first.
  A  WEEKLY LEADING       weekly quadrant turns Leading -> buy; leaves Leading -> sell (as the app)
  B  DAILY ROTATION       daily RS-ratio = 100 x RS / 50-day avg RS, momentum = 100 x ratio / ratio 5 days ago (3-day avg);
                          buy on the turn into Leading, sell on the turn to Weakening or Lagging
  C  21 EMA + ROTATION    close crosses above the 21 EMA, 9 EMA above 21 EMA, daily RS-ratio rising over 5 days -> buy;
                          close below the 21 EMA -> sell
  C0 21 EMA (control)     C without the rotation condition
  D  BREAKOUT + ROTATION  20-day closing high while the daily quadrant is Improving or Leading -> buy; close below the 10-day
                          low close -> sell
LIMIT env = pilot."""
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools/research")
import industry_basket_intraday as B  # noqa: E402

IND, SYMS = B.IND, B.SYMS
import os  # noqa: E402
COST, SLOTS, DELAY = float(os.environ.get("COST", "0.002")), int(os.environ.get("SLOTS", "5")), int(os.environ.get("DELAY", "0"))
ONLY = os.environ.get("ONLY", "")


def daily():
    out = {}
    for a in range(0, len(SYMS), 100):
        ch = [s + ".NS" for s in SYMS[a:a + 100]]
        for k in range(4):
            d = yf.download(ch, period="6y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=False)
            c = d["Close"] if len(d) else pd.DataFrame()
            got = [t for t in ch if t in c.columns and c[t].notna().sum() > 200]
            for t in got:
                out[t[:-3]] = c[t]
            if len(got) >= 0.9 * len(ch):
                break
            print("chunk", a, "got", len(got), "retry", k + 1, flush=True); time.sleep(30 * (k + 1))
        time.sleep(3)
    b = yf.download("^NSEI", period="6y", interval="1d", progress=False, auto_adjust=True)["Close"]
    return pd.DataFrame(out).sort_index(), (b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b)


C, nifty = daily()
nifty = nifty.reindex(C.index).ffill()
ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
I = pd.DataFrame({k: (1 + ret[[s for s in v if s in ret.columns]].mean(axis=1).fillna(0)).cumprod() for k, v in IND.items()})
R = I.pct_change().fillna(0)
RS = 100 * I.div(nifty, axis=0)
dr = 100 * RS / RS.rolling(50).mean(); dm = (100 * dr / dr.shift(5)).rolling(3).mean()
dq = pd.DataFrame(np.where(dr >= 100, np.where(dm >= 100, "L", "W"), np.where(dm >= 100, "I", "G")), index=I.index, columns=I.columns).where(dr.notna() & dm.notna())
W = I.resample("W-FRI").last(); NW = nifty.resample("W-FRI").last(); RSw = 100 * W.div(NW, axis=0)
wr = 100 * RSw / RSw.rolling(10).mean(); wm = (100 * wr / wr.shift(1)).rolling(3).mean()
wq = pd.DataFrame(np.where(wr >= 100, np.where(wm >= 100, "L", "W"), np.where(wm >= 100, "I", "G")), index=W.index, columns=W.columns).where(wr.notna() & wm.notna())
wqd = wq.reindex(I.index, method="ffill")            # weekly quadrant known from that Friday on (applied from the next day)
e9, e21 = I.ewm(span=9, adjust=False).mean(), I.ewm(span=21, adjust=False).mean()
hi20 = I.rolling(20).max(); lo10 = I.rolling(10).min()
start = dq.dropna(how="all").index[0] + pd.Timedelta(days=60)

SIG = {
    "A WEEKLY LEADING": ((wqd == "L") & (wqd.shift(1) != "L"), (wqd != "L") & (wqd.shift(1) == "L")),
    "B DAILY ROTATION": ((dq == "L") & (dq.shift(1) != "L"), dq.isin(["W", "G"]) & dq.shift(1).isin(["L", "I"])),
    "C 21 EMA + ROTATION": ((I > e21) & (I.shift(1) <= e21.shift(1)) & (e9 > e21) & (dr > dr.shift(5)), I < e21),
    "C0 21 EMA (control, no rotation)": ((I > e21) & (I.shift(1) <= e21.shift(1)) & (e9 > e21), I < e21),
    "D BREAKOUT + ROTATION": ((I >= hi20) & dq.isin(["I", "L"]), I < lo10.shift(1)),
}


def run(name, ent, ex):
    if DELAY:                        # act one day after the signal (buy / sell at the next close)
        ent, ex = ent.shift(DELAY).fillna(False).astype(bool), ex.shift(DELAY).fillna(False).astype(bool)
    days = I.index[I.index >= start]
    held = {}; trades = []; daily = []
    for t, d in enumerate(days[:-1]):
        nxt = days[t + 1]
        # exits on today's close signal
        for k in list(held):
            if bool(ex.at[d, k]):
                e_d, e_px = held.pop(k); trades.append((k, e_d, d, I.at[d, k] / e_px - 1 - COST, (d - e_d).days))
        # entries on today's close signal (trade at today's close), strongest momentum first
        cand = [k for k in I.columns if k not in held and bool(ent.at[d, k]) and pd.notna(I.at[d, k])]
        cand.sort(key=lambda k: -(dm.at[d, k] if pd.notna(dm.at[d, k]) else 0))
        for k in cand[:max(0, SLOTS - len(held))]:
            held[k] = (d, I.at[d, k])
        r = sum(R.at[nxt, k] for k in held) / SLOTS if held else 0.0
        daily.append((nxt, r, len(held)))
    s = pd.Series([x[1] for x in daily], index=[x[0] for x in daily])
    cost_days = pd.Series(0.0, index=s.index)
    for k, e_d, x_d, _, _ in trades:
        if x_d in cost_days.index:
            cost_days[x_d] += COST / SLOTS
    s = s - cost_days
    eq = (1 + s).cumprod(); yrs = (s.index[-1] - s.index[0]).days / 365.25
    T = pd.DataFrame(trades, columns=["ind", "in", "out", "ret", "days"])
    by = s.groupby(s.index.year).apply(lambda x: round(((1 + x).prod() - 1) * 100, 1)).to_dict()
    print(f"R| {name}: CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%, max drawdown {(eq / eq.cummax() - 1).min() * 100:.1f}%, "
          f"trades {len(T)}, avg {T.ret.mean() * 100:+.2f}%, win {np.mean(T.ret > 0) * 100:.0f}%, median hold {T.days.median():.0f} days, "
          f"avg slots used {np.mean([x[2] for x in daily]):.1f}/5, by year {by}", flush=True)


print("R| industries", I.shape[1], "from", start.date(), "to", I.index[-1].date(), flush=True)
for nm, (ent, ex) in SIG.items():
    if ONLY and not nm.startswith(ONLY):
        continue
    run(f"{nm} [cost {COST * 100:.1f}%, {SLOTS} slots, delay {DELAY}d]", ent.fillna(False), ex.fillna(False))
s = R.loc[start:].mean(axis=1); eq = (1 + s).cumprod(); yrs = (s.index[-1] - s.index[0]).days / 365.25
print(f"R| BENCHMARK all industries equal weight: CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%, max drawdown {(eq / eq.cummax() - 1).min() * 100:.1f}%")
s = nifty.loc[start:].pct_change().dropna(); eq = (1 + s).cumprod()
print(f"R| BENCHMARK Nifty 50: CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%, max drawdown {(eq / eq.cummax() - 1).min() * 100:.1f}%")
