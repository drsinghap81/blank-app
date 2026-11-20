"""probe 2: is 19 Nov missing per ticker, or only in batched downloads? (20 Nov 2026)"""
import sys
import yfinance as yf
sys.path.insert(0, "tools")
import group_pulse as G
for mkt in ("NSE", "UK"):
    cf = G.CFG[mkt]; u = G.universe(mkt); tk = [s + cf["suf"] for s in list(u.symbol)[:20]]
    one = {t: "2026-11-19" in [str(x.date()) for x in yf.download(t, period="10d", progress=False).index] for t in tk}
    for thr in (True, False):
        d = yf.download(tk, period="10d", progress=False, group_by="column", threads=thr)
        c = d["Close"]; row = c.loc[[i for i in c.index if str(i.date()) == "2026-11-19"]]
        print("R|", mkt, "threads", thr, "batched has 19 Nov:", int(row.notna().sum(axis=1).iloc[0]) if len(row) else 0, "of", len(tk), "| single:", sum(one.values()))
    h = yf.Ticker(tk[0]).history(period="10d"); print("R|", mkt, tk[0], "Ticker.history last", [str(x.date()) for x in h.index[-3:]])
