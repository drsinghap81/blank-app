"""Symbol -> NSE industry classification (macro / sector / industry / basicIndustry) for NSE equities.
Source: NSE quote API (industryInfo); fallback Yahoo 'industry'. Output data/universe/nse_industry.csv.
Usage: python tools/fetch_industry.py [LIMIT]"""
import csv, io, os, sys, time
import requests

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})


def warm():
    for u in ("https://www.nseindia.com/", "https://www.nseindia.com/market-data/live-equity-market"):
        try:
            S.get(u, timeout=20)
        except Exception:  # noqa: BLE001
            pass


def symbols():
    r = S.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=30)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return [x["SYMBOL"].strip() for x in rows if x.get(" SERIES", x.get("SERIES", "")).strip() in ("EQ", "BE")]


def nse(sym):
    for k in range(3):
        try:
            r = S.get("https://www.nseindia.com/api/quote-equity", params={"symbol": sym}, timeout=20)
            if r.status_code == 200:
                ii = r.json().get("industryInfo") or {}
                if ii:
                    return [ii.get("macro", ""), ii.get("sector", ""), ii.get("industry", ""), ii.get("basicIndustry", "")]
                return None
            if r.status_code in (401, 403):
                warm(); time.sleep(2 + k * 3)
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def yahoo(sym):
    import yfinance as yf
    for k in range(3):
        try:
            i = yf.Ticker(sym + ".NS").info or {}
            if i.get("industry"):
                return ["", i.get("sector", ""), i.get("industry", ""), i.get("industry", "")]
            return None
        except Exception:  # noqa: BLE001
            time.sleep(2 + 2 * k)
    return None


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    warm(); syms = symbols(); print("symbols", len(syms), flush=True)
    if lim:
        syms = syms[:lim]
    os.makedirs("data/universe", exist_ok=True)
    out = open("data/universe/nse_industry.csv", "w", newline=""); w = csv.writer(out); w.writerow(["symbol", "macro", "sector", "industry", "basic_industry", "src"])
    ok = miss = 0
    use_nse = any(nse(s) for s in syms[:5])          # NSE blocks cloud IPs -> Yahoo industry instead
    print("source", "nse" if use_nse else "yahoo", flush=True)
    import concurrent.futures as cf
    f = nse if use_nse else yahoo
    with cf.ThreadPoolExecutor(1 if use_nse else 6) as ex:
        for i, (s, v) in enumerate(zip(syms, ex.map(f, syms))):
            if v:
                w.writerow([s, *v, "nse" if use_nse else "yahoo"]); ok += 1
            else:
                miss += 1
            if i % 200 == 0:
                print(i, "ok", ok, "miss", miss, flush=True); out.flush()
    out.close(); print("done ok", ok, "miss", miss)


if __name__ == "__main__":
    main()
