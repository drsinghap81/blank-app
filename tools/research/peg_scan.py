"""Check of a user-supplied 'Nifty 500 GARP + 50-DMA uptrend' screen (14 Nov 2026): the original code with its bugs fixed,
plus diagnostics on how much fundamental data Yahoo really has for NSE stocks. Writes data/research/peg_scan.json + .csv."""
import io, json, os, time
import pandas as pd, requests, yfinance as yf

def get_nifty500_tickers():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"      # original used the NSE home page
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.nseindia.com/"}, timeout=20)
        r.raise_for_status(); df = pd.read_csv(io.StringIO(r.text)); src = "NSE archive"
    except Exception as e:  # noqa: BLE001
        df = pd.read_csv("data/universe/nifty500.csv"); src = f"repo copy (NSE failed: {str(e)[:60]})"
    print("list from", src)
    return [f"{s.strip()}.NS" for s in df["Symbol"].dropna()], src

tickers, src = get_nifty500_tickers()
hist = yf.download(tickers, period="1y", interval="1d", auto_adjust=True, progress=False, threads=True)["Close"]
up, sma = [], {}
for t in tickers:
    if t not in hist.columns: continue
    s = hist[t].dropna()
    if len(s) < 60: continue
    c, m, m10 = s.iloc[-1], s.iloc[-50:].mean(), s.iloc[-60:-10].mean()
    if c > m and m > m10: up.append(t); sma[t] = (round(float(c), 2), round(float(m), 2))
print(len(tickers), "tickers,", hist.shape[1], "with prices,", len(up), "in a rising 50-DMA uptrend")
diag = dict(info_ok=0, info_fail=0, pegRatio=0, trailingPegRatio=0, earningsGrowth=0, trailingPE=0, peg_fallback_used=0, errors=[])
rows = []
for t in up:
    try:
        info = yf.Ticker(t).info; diag["info_ok"] += 1
    except Exception as e:  # noqa: BLE001
        diag["info_fail"] += 1; diag["errors"].append(f"{t}: {str(e)[:80]}"); time.sleep(1); continue
    for k in ("pegRatio", "trailingPegRatio", "earningsGrowth", "trailingPE"):
        if info.get(k) is not None: diag[k] += 1
    pe, g = info.get("trailingPE"), info.get("earningsGrowth")
    peg = info.get("pegRatio") or info.get("trailingPegRatio"); how = "Yahoo"
    if peg is None and pe and g and g > 0:
        peg = pe / (g * 100); how = "PE / last-quarter YoY EPS growth"; diag["peg_fallback_used"] += 1
    c, m = sma[t]
    rows.append({"Symbol": t[:-3], "Price": c, "50-DMA": m, "% above": round((c / m - 1) * 100, 2), "Trailing PE": pe,
                 "Earnings growth (qtr YoY)": g, "PEG": round(peg, 2) if peg else None, "PEG source": how if peg else None,
                 "Sector": info.get("sector")})
    time.sleep(0.3)
R = pd.DataFrame(rows); ok = R[(R.PEG > 0) & (R.PEG <= 2)].sort_values("PEG") if len(R) else R
os.makedirs("data/research", exist_ok=True); ok.to_csv("data/research/peg_scan.csv", index=False)
json.dump(dict(generated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"), list_source=src, tickers=len(tickers), uptrend=len(up),
               diag={k: v for k, v in diag.items() if k != "errors"}, errors=diag["errors"][:10], passed=len(ok),
               top=ok.head(25).to_dict("records")), open("data/research/peg_scan.json", "w"), indent=1, default=str)
print(json.dumps(diag | dict(errors=diag["errors"][:5]), default=str)); print(ok.head(25).to_string(index=False))
