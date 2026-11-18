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
    # NSE ETFs: the same trades without futures or leverage (1 share = 1 unit; a 1% risk usually needs ~30-50% of the account per position)
    ("NIFTYBEES.NS", "NIFTYBEES (Nifty ETF)", "ETFs (no leverage)", "INR", ("NIFTYBEES shares", 1), "NSE:NIFTYBEES"),
    ("BANKBEES.NS", "BANKBEES (Bank Nifty ETF)", "ETFs (no leverage)", "INR", ("BANKBEES shares", 1), "NSE:BANKBEES"),
    ("GOLDBEES.NS", "GOLDBEES (gold ETF)", "ETFs (no leverage)", "INR", ("GOLDBEES shares", 1), "NSE:GOLDBEES"),
    ("SILVERBEES.NS", "SILVERBEES (silver ETF)", "ETFs (no leverage)", "INR", ("SILVERBEES shares", 1), "NSE:SILVERBEES"),
    # 19 Nov 2026 (Amritpal: "add the ETFs and commodities"): more NSE ETFs, US agri / energy / platinum, USD/INR.
    # NOT part of the 2010-26 Turtle test (those 14 markets); watch them as extra candidates.
    *[(f"{e}.NS", f"{e} ({nm})", "ETFs (no leverage)", "INR", (f"{e} shares", 1), f"NSE:{e}") for e, nm in (
        ("JUNIORBEES", "Nifty Next 50"), ("MID150BEES", "Midcap 150"), ("MOM100", "Midcap 100"), ("ITBEES", "IT"), ("PSUBNKBEES", "PSU banks"),
        ("PHARMABEES", "pharma"), ("AUTOBEES", "auto"), ("METALIETF", "metal"), ("CPSEETF", "CPSE"), ("INFRABEES", "infra"),
        ("CONSUMBEES", "consumption"), ("MON100", "Nasdaq 100"), ("MAFANG", "US FANG+"), ("HNGSNGBEES", "Hang Seng"))],
    ("NG=F", "Natural gas (Henry Hub)", "Energy", "USD", ("Micro Henry Hub MNG · 1,000 mmBtu", 1000), "NYMEX:MNG1!"),
    ("PL=F", "Platinum", "Metals", "USD", ("Platinum PL · 50 oz", 50), "NYMEX:PL1!"),
    ("ZW=F", "Wheat", "Agri", "USD", ("Mini wheat XW · 1,000 bu (price in cents)", 10), "CBOT_MINI:XW1!"),
    ("ZC=F", "Corn", "Agri", "USD", ("Mini corn XC · 1,000 bu (price in cents)", 10), "CBOT_MINI:XC1!"),
    ("ZS=F", "Soybeans", "Agri", "USD", ("Mini soybeans XK · 1,000 bu (price in cents)", 10), "CBOT_MINI:XK1!"),
    ("SB=F", "Sugar", "Agri", "USD", ("Sugar No. 11 SB · 112,000 lb (cents)", 1120), "ICEUS:SB1!"),
    ("KC=F", "Coffee", "Agri", "USD", ("Coffee KC · 37,500 lb (cents)", 375), "ICEUS:KC1!"),
    ("CT=F", "Cotton", "Agri", "USD", ("Cotton CT · 50,000 lb (cents)", 500), "ICEUS:CT1!"),
    ("INR=X", "USD/INR", "Currencies", "INR", ("USDINR futures (NSE) · $1,000", 1000), "NSE:USDINR1!"),
]
# MCX mini / micro contracts (16 Nov 2026). Yahoo has no MCX data: each series = the global contract x USD/INR x unit conversion,
# so levels are approximate (no import duty / local premium); the signal timing tracks MCX closely. Place orders on MCX's own chart.
# key, name, global ticker, conversion (USD price -> MCX quote unit, before USD/INR), lot multiplier (quote units per lot), TradingView
MCX_ROWS = [
    ("MCX:GOLDM", "Gold Mini (MCX)", "GC=F", 10 / 31.1035, 10, "GOLDM · 100 g, quoted per 10 g", "MCX:GOLDM1!"),
    ("MCX:GOLDGUINEA", "Gold Guinea (MCX)", "GC=F", 8 / 31.1035, 1, "GOLDGUINEA · 8 g", "MCX:GOLDGUINEA1!"),
    ("MCX:GOLDPETAL", "Gold Petal (MCX)", "GC=F", 1 / 31.1035, 1, "GOLDPETAL · 1 g", "MCX:GOLDPETAL1!"),
    ("MCX:SILVERM", "Silver Mini (MCX)", "SI=F", 32.1507, 5, "SILVERM · 5 kg, quoted per kg", "MCX:SILVERM1!"),
    ("MCX:SILVERMIC", "Silver Micro (MCX)", "SI=F", 32.1507, 1, "SILVERMIC · 1 kg", "MCX:SILVERMIC1!"),
    ("MCX:CRUDEOILM", "Crude Oil Mini (MCX)", "CL=F", 1, 10, "CRUDEOILM · 10 bbl", "MCX:CRUDEOILM1!"),
    ("MCX:NATGASMINI", "Natural Gas Mini (MCX)", "NG=F", 1, 250, "NATGASMINI · 250 mmBtu", "MCX:NATGASMINI1!"),
    ("MCX:ALUMINI", "Aluminium Mini (MCX)", "ALI=F", 1 / 1000, 1000, "ALUMINI · 1 tonne, quoted per kg", "MCX:ALUMINI1!"),
    ("MCX:COPPER", "Copper (MCX)", "HG=F", 2.20462, 2500, "COPPER · 2,500 kg, quoted per kg", "MCX:COPPER1!"),
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


MCX = {"GC=F": [("Gold Petal", 1 / 31.1035, 1), ("Gold Guinea", 8 / 31.1035, 1), ("Gold Mini", 10 / 31.1035, 10)],
       "SI=F": [("Silver Micro", 32.1507, 1), ("Silver Mini", 32.1507, 5)], "CL=F": [("Crude Oil Mini", 1, 10)], "HG=F": [("Copper", 2.20462, 2500)]}
NSE_LOT = {"^NSEI": 65, "^NSEBANK": 30}


def lots_text(r, usdinr):
    """Lots per Rs 10 lakh of account at 1% risk (scale to your own account; no account size is stored in the repo)."""
    N = r.get("entry_N") or r["N"]; risk = 1_000_000 * 0.01; out = []
    if r["key"].startswith("MCX:"):
        per = 2 * N * r["mult"]; return f"Per Rs 10 L at 1%: {int(risk // per)} lot(s) (risk Rs {per:,.0f}/lot)"
    for nm, conv, mult in MCX.get(r["key"], []):
        per = 2 * N * usdinr * conv * mult; out.append(f"{nm} {int(risk // per)} (risk Rs {per:,.0f}/lot)")
    if r["key"] in NSE_LOT:
        per = 2 * N * NSE_LOT[r["key"]]; out.append(f"{r['name']} futures {int(risk // per)} lot (risk Rs {per:,.0f}/lot)")
    if r.get("mult"):
        per = 2 * N * r["mult"]; out.append(f"{r['contract']}: risk ${per:,.0f} per contract")
    return ("Per Rs 10 L at 1%: " + "; ".join(out)) if out else ""


RAW = {}


def chart(x, n=130):
    z = x.tail(n); rd = lambda v: [float(f"{q:.6g}") for q in v]  # noqa: E731
    return dict(t=[str(i.date()) for i in z.index], o=rd(z.Open), h=rd(z.High), l=rd(z.Low), c=rd(z.Close))


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
        if len(x) < 120:            # 19 Nov 2026: Yahoo had only 19 days of MID150BEES - no reliable 20-day high or N
            print("too little history", t, len(x)); continue
        RAW[t] = x
        try:
            s = state(x)
        except Exception as e:  # noqa: BLE001
            print("fail", t, e); continue
        rows.append(dict(key=t, name=nm, group=g, cur=cur, contract=cname, mult=mult, tv=tv, **s, chart=chart(x))); time.sleep(0.3)
    fxs = {}
    for k in ("USDINR=X", "AUDUSD=X"):
        try:
            z = yf.download(k, period="2y", interval="1d", progress=False)
            if isinstance(z.columns, pd.MultiIndex):
                z.columns = z.columns.get_level_values(0)
            fxs[k] = z["Close"].dropna(); fx[k] = float(fxs[k].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
    for key, nm, src, conv, mult, cname, tv in MCX_ROWS:
        x = RAW.get(src)
        if x is None:
            try:
                x = yf.download(src, period="2y", interval="1d", auto_adjust=False, progress=False)
                if isinstance(x.columns, pd.MultiIndex):
                    x.columns = x.columns.get_level_values(0)
                x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]; RAW[src] = x
            except Exception as e:  # noqa: BLE001
                print("no data", src, e); continue
        if "USDINR=X" not in fxs or x is None or x.empty:
            continue
        k = fxs["USDINR=X"].reindex(x.index, method="ffill") * conv
        xi = x[["Open", "High", "Low", "Close"]].mul(k, axis=0).dropna()
        try:
            s = state(xi)
        except Exception as e:  # noqa: BLE001
            print("fail", key, e); continue
        rows.append(dict(key=key, name=nm, group="MCX (approx.)", cur="INR", contract=cname, mult=mult, tv=tv, approx=True, **s, chart=chart(xi)))
    os.makedirs("data/scan", exist_ok=True)

    def clean(v):              # 19 Nov 2026: a NaN made the file invalid JSON for the app (it fell back to days-old data)
        if isinstance(v, float) and not np.isfinite(v):
            return None
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        return v
    rows = clean(rows); fx = clean(fx)
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), fx=fx, rows=rows,
                   rules="Daily 20/10 long: buy-stop above the 20-day high; fixed stop entry - 2N; trailing stop 10-day low; exit at the first hit; no target. 1 unit, no adds."),
              open("data/scan/turtle.json", "w"), indent=0, allow_nan=False)
    news = [r for r in rows if (r["status"] == "in trade" and r.get("new")) or r["status"] == "exited today"]
    print(len(rows), "markets;", [(r["name"], r["status"]) for r in rows])
    if news:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from trend_scan import telegram
        lines = ["Turtle 20/10 (futures watch)"]
        for r in news:
            if r["status"] == "in trade":
                lines.append(f"BUY {r['name']}: broke the 20-day high, filled ~{r['entry']:.2f}. Fixed stop {r['fixed_stop']:.2f}, trailing stop {r['trail_stop']:.2f}.")
                lt = lots_text(r, fx.get("USDINR=X", 85))
                if lt:
                    lines.append("  " + lt + ". Exact lots for your account: app > Trading > Turtle.")
            else:
                z = r["trades"][-1]; lines.append(f"EXIT {r['name']}: stopped at ~{z['x']:.2f} ({z['R']:+.1f}R).")
        telegram("\n".join(lines))


if __name__ == "__main__":
    main()
