"""Research (12 Nov 2026): AI / tech ETFs vs the app's momentum entry rule (above a rising 30-week SMA, monthly new high),
recent returns, distance from high, worst fall, and 3-year correlation with US momentum (MTUM, same index as IUMO).
Writes data/research/ai_etf_check.json."""
import json, os
import numpy as np, pandas as pd, yfinance as yf

E = {"AIQ": "Global X AI & Technology", "BOTZ": "Global X Robotics & AI", "ARTY": "iShares Future AI & Tech", "IRBO": "iShares Robotics & AI",
     "CHAT": "Roundhill Generative AI", "THNQ": "ROBO Global AI", "SMH": "VanEck Semiconductors", "SOXX": "iShares Semiconductors",
     "IGV": "iShares Software", "QQQ": "Nasdaq 100", "SPMO": "Invesco S&P 500 Momentum", "MTUM": "iShares USA Momentum (IUMO's index)", "VOO": "S&P 500"}
px = yf.download(list(E), period="10y", auto_adjust=True, progress=False)["Close"].dropna(how="all")
W = px.resample("W-FRI").last(); Mo = px.resample("ME").last()
out = []
for k, nm in E.items():
    if k not in px or px[k].dropna().empty:
        continue
    s = px[k].dropna(); w = W[k].dropna(); m = Mo[k].dropna()
    sma = w.rolling(30).mean(); last = float(s.iloc[-1])
    rising = bool(sma.iloc[-1] > sma.iloc[-5]) if len(sma.dropna()) > 5 else None
    hi = float(s.max()); r = lambda n: round((last / float(s.iloc[-n - 1]) - 1) * 100, 1) if len(s) > n else None  # noqa: E731
    eq = s / s.cummax() - 1
    mret = m.pct_change().dropna(); corr = None
    if "MTUM" in Mo:
        a = Mo[[k, "MTUM"]].pct_change().dropna().iloc[-36:]
        corr = round(float(a[k].corr(a["MTUM"])), 2) if len(a) > 12 and k != "MTUM" else None
    prev_hi = float(m.iloc[:-1].max()) if len(m) > 1 else None
    out.append(dict(ticker=k, name=nm, last=round(last, 2), from_high=round((last / hi - 1) * 100, 1), above_sma30=bool(last > sma.iloc[-1]) if pd.notna(sma.iloc[-1]) else None,
                    sma30_rising=rising, pct_vs_sma30=round((last / float(sma.iloc[-1]) - 1) * 100, 1) if pd.notna(sma.iloc[-1]) else None,
                    month_new_high=bool(prev_hi and float(m.iloc[-1]) > prev_hi), r1m=r(21), r3m=r(63), r6m=r(126), r1y=r(252), r3y=r(756),
                    maxdd=round(float(eq.min()) * 100, 1), since=str(s.index[0].date()), corr_mtum_3y=corr,
                    cagr=round(((last / float(s.iloc[0])) ** (365.25 / (s.index[-1] - s.index[0]).days) - 1) * 100, 1)))
os.makedirs("data/research", exist_ok=True)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"), asof=str(px.index[-1].date()), rows=out), open("data/research/ai_etf_check.json", "w"), indent=1)
for x in out: print(x)
