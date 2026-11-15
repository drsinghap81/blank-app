"""Turtle 20/10 daily, long only (16 Nov 2026; tested in research/turtle_port_bt.txt: 24%/yr, -27% max DD with coins at 1% risk, ~12%,
-33% without coins; ~2.5x average gross leverage). For each market: replay the rules over the last 2 years to know today's state.
  Buy: buy-stop above the highest high of the last 20 days.  N = ATR(20, Wilder).
  Fixed stop: entry - 2N (never moves).  Trailing stop: lowest low of the last 10 days.  Exit at the first one hit. No target.
Writes data/scan/turtle.json (state, levels, last trades) and sends a Telegram/WhatsApp note on scheduled runs when a market
breaks out (buy) or is stopped out (exit). Paper / watch: the app sizes it from your settings; orders are yours to place."""
import json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, yfinance as yf

MK = [  # ticker, name, group, currency, micro contract (name, multiplier) for sizing, TradingView symbol
    ("GC=F", "Gold", "Metals", "USD", ("Micro gold MGC", 10), "COMEX:MGC1!"),
    ("SI=F", "Silver", "Metals", "USD", ("Micro silver SIL", 1000), "COMEX:SIL1!"),
    ("HG=F", "Copper", "Metals", "USD", ("Micro copper MHG", 2500), "COMEX:MHG1!"),
    ("CL=F", "Crude oil", "Energy", "USD", ("Micro crude MCL", 100), "NYMEX:MCL1!"),
    ("^GSPC", "S&P 500", "Indices", "USD", ("Micro S&P MES", 5), "CME_MINI:MES1!"),
    ("^NDX", "Nasdaq 100", "Indices", "USD", ("Micro Nasdaq MNQ", 2), "CME_MINI:MNQ1!"),
    ("^NSEI", "Nifty 50", "Indices", "INR", ("Nifty futures (NSE)", None), "NSE:NIFTY1!"),
    ("^NSEBANK", "Bank Nifty", "Indices", "INR", ("Bank Nifty futures (NSE)", None), "NSE:BANKNIFTY1!"),
    ("BTC-USD", "Bitcoin", "Coins", "USD", ("Micro bitcoin MBT", 0.1), "CME:MBT1!"),
    ("ETH-USD", "Ether", "Coins", "USD", ("Micro ether MET", 0.1), "CME:MET1!"),
]


def state(x):
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); n = len(c); d = x.index
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    N = np.r_[np.nan, pd.Series(tr).ewm(alpha=1 / 20, adjust=False, min_periods=20).mean().to_numpy()]   # N[t] = ATR through bar t
    hh = pd.Series(h).shift(1).rolling(20).max().to_numpy(); ll = pd.Series(l).shift(1).rolling(10).min().to_numpy()
    pos = None; trades = []; t = 21
    while t < n:
        if pos is None:
            if np.isfinite(hh[t]) and h[t] > hh[t] and np.isfinite(N[t - 1]):
                e = max(o[t], hh[t]); pos = dict(i=t, e=e, N=N[t - 1], fix=e - 2 * N[t - 1])
                if l[t] <= pos["fix"]:
                    trades.append(dict(entry=str(d[t].date()), e=e, exit=str(d[t].date()), x=pos["fix"], R=-1.0)); pos = None
        else:
            st = max(pos["fix"], ll[t]) if np.isfinite(ll[t]) else pos["fix"]
            if l[t] <= st:
                xp = min(o[t], st); trades.append(dict(entry=str(d[pos["i"]].date()), e=pos["e"], exit=str(d[t].date()), x=xp, R=(xp - pos["e"]) / (2 * pos["N"])))
                pos = None
        t += 1
    last = n - 1
    trig = float(pd.Series(h).iloc[-20:].max()); trail = float(pd.Series(l).iloc[-10:].min()); Nn = float(N[last])
    out = dict(close=float(c[last]), date=str(d[last].date()), N=Nn, buy_stop=trig, dist_pct=round((trig / c[last] - 1) * 100, 2),
               trades=[{k: (round(v, 4) if isinstance(v, float) else v) for k, v in z.items()} for z in trades[-6:]])
    if pos:
        st = max(pos["fix"], trail)
        out.update(status="in trade", entry_date=str(d[pos["i"]].date()), entry=pos["e"], entry_N=pos["N"], fixed_stop=pos["fix"], trail_stop=trail,
                   stop=st, open_R=round((c[last] - pos["e"]) / (2 * pos["N"]), 2), open_pct=round((c[last] / pos["e"] - 1) * 100, 2),
                   new=pos["i"] == last)
    else:
        lastx = trades[-1] if trades else None
        out.update(status="exited today" if lastx and lastx["exit"] == str(d[last].date()) else "flat", fixed_stop_if_filled=trig - 2 * Nn)
    return out


def main():
    rows, fx = [], {}
    for t, nm, g, cur, (cname, mult), tv in MK:
        x = None
        for _ in range(3):
            try:
                x = yf.download(t, period="2y", interval="1d", auto_adjust=False, progress=False); break
            except Exception as e:  # noqa: BLE001
                print("retry", t, e); time.sleep(5)
        if x is None or x.empty:
            print("no data", t); continue
        if isinstance(x.columns, pd.MultiIndex):
            x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
        try:
            s = state(x)
        except Exception as e:  # noqa: BLE001
            print("fail", t, e); continue
        rows.append(dict(key=t, name=nm, group=g, cur=cur, contract=cname, mult=mult, tv=tv, **s)); time.sleep(0.3)
    for k in ("USDINR=X", "AUDUSD=X"):
        try:
            fx[k] = float(yf.download(k, period="5d", interval="1d", progress=False)["Close"].dropna().iloc[-1].squeeze())
        except Exception:  # noqa: BLE001
            pass
    os.makedirs("data/scan", exist_ok=True)
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), fx=fx, rows=rows,
                   rules="Daily 20/10 long: buy-stop above the 20-day high; fixed stop entry - 2N; trailing stop 10-day low; exit at the first hit; no target. 1 unit, no adds."),
              open("data/scan/turtle.json", "w"), indent=0)
    news = [r for r in rows if (r["status"] == "in trade" and r.get("new")) or r["status"] == "exited today"]
    print(len(rows), "markets;", [(r["name"], r["status"]) for r in rows])
    if news:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from trend_scan import telegram
        lines = ["Turtle 20/10 (futures watch)"]
        for r in news:
            if r["status"] == "in trade":
                lines.append(f"BUY {r['name']}: broke the 20-day high, filled ~{r['entry']:.2f}. Fixed stop {r['fixed_stop']:.2f}, trailing stop {r['trail_stop']:.2f}.")
            else:
                z = r["trades"][-1]; lines.append(f"EXIT {r['name']}: stopped at ~{z['x']:.2f} ({z['R']:+.1f}R).")
        telegram("\n".join(lines))


if __name__ == "__main__":
    main()
