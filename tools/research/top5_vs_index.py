"""One-off (19 Nov 2026, Amritpal: are the Top 5 moving as much as their sector / theme / Nifty? opportunity cost check).
Yahoo daily + today's intraday for the stocks, Nifty and the sector indices on Yahoo; theme indices from NSE's archive
(data/scan/sector_hist.csv.gz, up to the last close)."""
import pandas as pd
import yfinance as yf

PICKS = {"KOTAKBANK": ("2026-11-17", "NIFTY_FIN_SERVICE.NS", ["NIFTY HOUSING", "NIFTY SERVICES SECTOR"]),
         "ETERNAL": ("2026-10-30", "^CNXCONSUM", ["NIFTY INDIA INTERNET", "NIFTY INDIA DIGITAL", "NIFTY INDIA NEW AGE CONSUMPTION"]),
         "MEESHO": ("2026-11-05", "^CNXCONSUM", ["NIFTY INDIA INTERNET", "NIFTY INDIA DIGITAL", "NIFTY IPO"]),
         "DRREDDY": ("2026-11-17", "^CNXPHARMA", ["NIFTY HEALTHCARE INDEX"]),
         "PRIMESECU": ("2026-11-17", "NIFTY_FIN_SERVICE.NS", ["NIFTY CAPITAL MARKETS"])}
H = pd.read_csv("data/scan/sector_hist.csv.gz"); H["Date"] = pd.to_datetime(H.Date)
P = H.pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index()


def yclose(t):
    d = yf.Ticker(t).history(period="3mo", interval="1d").Close
    d.index = d.index.tz_localize(None).normalize(); return d


def pct(s, since):
    s = s.dropna(); b = s[s.index < pd.Timestamp(since)]
    base = b.iloc[-1] if len(b) else s.iloc[0]
    return round((s.iloc[-1] / base - 1) * 100, 2), round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2), str(s.index[-1].date())


nif = yclose("^NSEI")
for sym, (since, sec, themes) in PICKS.items():
    st = yclose(sym + ".NS"); sx = yclose(sec)
    a, ta, da = pct(st, since); n, tn, _ = pct(nif, since); s, ts, _ = pct(sx, since)
    th = []
    for t in themes:
        if t in P:
            v = P[t].dropna(); b = v[v.index < pd.Timestamp(since)]
            if len(b):
                th.append(f"{t} {round((v.iloc[-1] / b.iloc[-1] - 1) * 100, 2)}% (to {v.index[-1].date()})")
    print(f"R| {sym} since {since} (signal): stock {a}% | sector {sec} {s}% | Nifty {n}% || today: stock {ta}% sector {ts}% Nifty {tn}% (last bar {da}) || themes: {'; '.join(th)}")
