"""probe: last daily bars Yahoo returns for a few NSE / LSE stocks (20 Nov 2026)"""
import sys
import yfinance as yf
sys.path.insert(0, "tools")
from session import drop_partial
for tk, m in (("RELIANCE.NS", "NSE"), ("SBIN.NS", "NSE"), ("HSBA.L", "UK"), ("AAPL", "US")):
    d = yf.download(tk, period="10d", interval="1d", progress=False, auto_adjust=True)
    print("R|", tk, [str(x.date()) for x in d.index[-4:]], "after drop_partial", [str(x.date()) for x in drop_partial(d, m).index[-3:]])
d = yf.download(["RELIANCE.NS", "SBIN.NS", "TCS.NS"], period="10d", interval="1d", progress=False, auto_adjust=True, group_by="column")
print("R| multi", [str(x) for x in d.index[-4:]], d["Close"].tail(3).round(1).to_dict("list"))
