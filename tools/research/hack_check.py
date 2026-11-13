"""Research (14 Nov 2026): Betashares HACK (ASX cybersecurity) vs the app's trend rule, peers, and overlap with Nasdaq.
Rule backtest: hold only while weekly close > rising 30-week SMA (checked weekly), else cash. Writes data/research/hack_check.json."""
import json, os
import pandas as pd, yfinance as yf

E = {"HACK.AX": "Betashares Global Cybersecurity", "NDQ.AX": "Betashares Nasdaq 100", "IVV.AX": "iShares S&P 500 (AUD)",
     "A200.AX": "Betashares ASX 200", "SEMI.AX": "Global X Semiconductor", "CIBR": "First Trust Cybersecurity (USD)", "BUG": "Global X Cybersecurity (USD)"}
px = yf.download(list(E), period="max", auto_adjust=True, progress=False)["Close"].dropna(how="all")
W = px.resample("W-FRI").last(); out = []
def stats(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1), round(float((eq / eq.cummax() - 1).min()) * 100, 1)
for k, nm in E.items():
    if k not in W or W[k].dropna().empty:
        continue
    w = W[k].dropna(); s = px[k].dropna(); last = float(s.iloc[-1]); sma = w.rolling(30).mean()
    on = ((w > sma) & (sma > sma.shift(4))).shift(1).fillna(False)
    rr = w.pct_change().fillna(0); bh = (1 + rr).cumprod(); rule = (1 + rr.where(on, 0)).cumprod()
    r = lambda n: round((last / float(s.iloc[-n - 1]) - 1) * 100, 1) if len(s) > n else None  # noqa: E731
    yr = {str(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in w.groupby(w.index.year) if len(g) > 10}
    c = W[[k, "NDQ.AX"]].pct_change().dropna().iloc[-156:] if "NDQ.AX" in W else None
    out.append(dict(ticker=k, name=nm, since=str(s.index[0].date()), last=round(last, 2), from_high=round((last / float(s.max()) - 1) * 100, 1),
                    above_sma30=bool(w.iloc[-1] > sma.iloc[-1]), sma30_rising=bool(sma.iloc[-1] > sma.iloc[-5]),
                    r3m=r(63), r6m=r(126), r1y=r(252), r3y=r(756), r5y=r(1260),
                    bh_cagr_dd=stats(bh), rule_cagr_dd=stats(rule), rule_time_in=round(float(on.mean()) * 100),
                    corr_ndq_3y=round(float(c[k].corr(c["NDQ.AX"])), 2) if c is not None and k != "NDQ.AX" else None, years=yr))
os.makedirs("data/research", exist_ok=True)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"), asof=str(px.index[-1].date()), rows=out), open("data/research/hack_check.json", "w"), indent=1)
for x in out: print(x)
