"""FII come back after a selling streak -> buy the index (25 Nov 2026, Amritpal: "when large caps were performing why the system
didn't pick up - when FII come back from a selling streak to buy they put money in large cap" -> "Yes" to testing it at index level).
Data: NSDL daily FPI equity net (data/research/fii_daily.csv, 2015-26; the value for a date is used from the NEXT session on);
Nifty and Bank Nifty near-month futures closes (data/futures/*.csv; roll days use the new contract, so returns include ~carry -
the baseline uses the same series, so comparisons are fair).
Streak: 20-day FII net in the bottom 20% of the past 250 sessions (heavy selling) on any day in the last 30 sessions.
Return  : then the 5-day net turns positive (R5) / the 10-day net turns positive (R10) / 3 straight buying days (B3).
Entry next session's open after the FII value is usable. Exits: 9/21 (daily close EMA9 < EMA21 -> next open) | hold 20 | hold 60.
Also: 'return + index 9/21 already up'. Baselines: every day's 20/60-session forward return; plain index 9/21 (always on).
0.1% round trip. Newest first."""
import numpy as np
import pandas as pd

F = pd.read_csv("data/research/fii_daily.csv", index_col=0, parse_dates=True).iloc[:, 0].rename("net")


def idx(nm):
    x = pd.read_csv(f"data/futures/{nm}.csv", parse_dates=["Date"]).set_index("Date")
    return x[["Open", "High", "Low", "Close"]].astype(float)


def run(nm):
    X = idx(nm); X = X[X.index >= "2015-06-01"]
    f = F.reindex(X.index.union(F.index)).fillna(0).groupby(level=0).sum()
    f = f.shift(1).reindex(X.index).fillna(0)          # usable from the next session
    s20, s5, s10 = (f.rolling(n).sum() for n in (20, 5, 10))
    heavy = s20 <= s20.rolling(250, min_periods=120).quantile(0.2)
    recent = heavy.rolling(30).max().astype(bool)
    o, c = X.Open.to_numpy(), X.Close.to_numpy(); D = X.index; n = len(c)
    e9 = X.Close.ewm(span=9, adjust=False).mean().to_numpy(); e21 = X.Close.ewm(span=21, adjust=False).mean().to_numpy()
    buyday = (f > 0).astype(int)
    sig = {"R5  5-day net turns +": (recent & (s5 > 0) & (s5.shift(1) <= 0)),
           "R10 10-day net turns +": (recent & (s10 > 0) & (s10.shift(1) <= 0)),
           "B3  3 straight buying days": (recent & (buyday.rolling(3).sum() == 3) & (buyday.rolling(3).sum().shift(1) < 3))}
    sig.update({k + " + index 9/21 up": v & pd.Series(e9 > e21, index=D) for k, v in list(sig.items())})

    def exit921(j):
        for k in range(j, n - 1):
            if e9[k] < e21[k]:
                return k + 1
        return None
    print(f"R| ===== {nm} (futures closes 2015-26) =====", flush=True)
    fw20 = pd.Series(c).shift(-20) / pd.Series(c) - 1; fw60 = pd.Series(c).shift(-60) / pd.Series(c) - 1
    print(f"R| baseline any day: next 20 sessions {fw20.mean() * 100:+.2f}% (up {(fw20 > 0).mean() * 100:.0f}%) | next 60 {fw60.mean() * 100:+.2f}% (up {(fw60 > 0).mean() * 100:.0f}%)", flush=True)
    # plain 9/21 always on
    T = []; j = 21
    while j < n - 2:
        if e9[j] > e21[j] and e9[j - 1] <= e21[j - 1]:
            k = exit921(j + 1)
            if k is None:
                break
            T.append(o[k] / o[j + 1] - 1 - 0.001); j = k
        j += 1
    T = np.array(T); print(f"R| plain index 9/21: n {len(T)} avg {T.mean() * 100:+.2f}% win {(T > 0).mean() * 100:.0f}% sum {T.sum() * 100:+.0f}%", flush=True)
    for nmS, S in sig.items():
        S = S.fillna(False).to_numpy(); rows = []; last = -999
        for j in range(30, n - 2):
            if S[j] and j > last:
                e = j + 1; k = exit921(e)
                r921 = (o[k] / o[e] - 1 - 0.001) if k else np.nan
                r20 = c[min(e + 19, n - 1)] / o[e] - 1 - 0.001 if e + 19 < n else np.nan
                r60 = c[min(e + 59, n - 1)] / o[e] - 1 - 0.001 if e + 59 < n else np.nan
                rows.append(dict(d=D[e].date(), r921=r921, hold=(k - e) if k else None, r20=r20, r60=r60))
                last = (k if k else n)                 # one trade at a time (until the 9/21 exit)
        R = pd.DataFrame(rows)
        if R.empty:
            print(f"R| {nmS:40s} n 0", flush=True); continue
        q = lambda s: f"{s.mean() * 100:+.2f}% (win {(s > 0).mean() * 100:.0f}%)"  # noqa: E731
        print(f"R| {nmS:40s} n {len(R):2d} | 9/21 exit {q(R.r921.dropna())} hold {R.hold.median():.0f}d | 20 sessions {q(R.r20.dropna())} | 60 sessions {q(R.r60.dropna())}", flush=True)
        print("R|    newest first: " + " | ".join(f"{r.d} {r.r921 * 100:+.1f}%" if pd.notna(r.r921) else f"{r.d} open" for r in R.iloc[::-1].head(12).itertuples()), flush=True)


for nm in ("NIFTY", "BANKNIFTY"):
    run(nm)
