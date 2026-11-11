"""Stock universes for the trend scanner / backtests: NSE (India), US (NYSE + Nasdaq + NYSE American) and ASX.
Each function returns a DataFrame with columns symbol (display), ticker (Yahoo), name, board."""
import io
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

MARKETS = {
    "NSE": dict(label="India (NSE)", currency="₹", min_value=1e7, value_unit=1e7, value_label="₹ cr",
                cost=0.0025, slip=0.0015, benchmark="^NSEI", benchmark_name="Nifty 50", tz_close_utc="10:00"),
    "US": dict(label="United States", currency="$", min_value=2e6, value_unit=1e6, value_label="$ m",
               cost=0.0004, slip=0.0005, benchmark="SPY", benchmark_name="S&P 500 (SPY)", tz_close_utc="21:00"),
    "ASX": dict(label="Australia (ASX)", currency="A$", min_value=5e5, value_unit=1e6, value_label="A$ m",
                cost=0.0020, slip=0.0010, benchmark="^AXJO", benchmark_name="S&P/ASX 200", tz_close_utc="06:10"),
    # UK (11 Nov 2026): FTSE 350. Yahoo .L prices are in PENCE, so value thresholds are in pence (1e8 = GBP 1 m);
    # costs include 0.5% stamp duty on purchases.
    "UK": dict(label="United Kingdom (LSE)", currency="p", min_value=1e8, value_unit=1e8, value_label="£ m",
               cost=0.0060, slip=0.0010, benchmark="^FTSE", benchmark_name="FTSE 100", tz_close_utc="16:35"),
}


def _get(url, tries=3, **kw):
    for _ in range(tries):
        try:
            r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=40, **kw)
            if r.status_code == 200 and r.content:
                return r
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return None


def nse_symbols():
    rows = []
    for u, board in (("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "main"),
                     ("https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv", "SME")):
        r = _get(u, headers={"Referer": "https://www.nseindia.com/"})
        if r is None:
            continue
        d = pd.read_csv(io.BytesIO(r.content))
        d.columns = [c.strip().upper() for c in d.columns]
        col = lambda key: next(c for c in d.columns if key in c)  # noqa: E731
        sym = d[col("SYMBOL")].astype(str).str.strip()
        rows.append(pd.DataFrame({"symbol": sym, "ticker": sym + ".NS", "name": d[col("NAME")].astype(str).str.strip(),
                                  "board": board}))
    return pd.concat(rows).drop_duplicates("symbol")


def us_symbols():
    """Common stocks on Nasdaq, NYSE and NYSE American (no ETFs, test issues, warrants, units, rights, preferreds)."""
    out = []
    r = _get("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt")
    if r is not None:
        d = pd.read_csv(io.StringIO(r.text), sep="|")
        d = d[(d["ETF"] == "N") & (d["Test Issue"] == "N")]
        out.append(pd.DataFrame({"symbol": d["Symbol"], "name": d["Security Name"], "board": "Nasdaq"}))
    r = _get("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
    if r is not None:
        d = pd.read_csv(io.StringIO(r.text), sep="|")
        d = d[(d["ETF"] == "N") & (d["Test Issue"] == "N")]
        ex = d["Exchange"].map({"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe", "V": "IEX"}).fillna("Other")
        out.append(pd.DataFrame({"symbol": d["ACT Symbol"], "name": d["Security Name"], "board": ex}))
    d = pd.concat(out).dropna()
    d = d[~d.symbol.str.contains(r"[\$\^\.]|\s", regex=True) | d.symbol.str.match(r"^[A-Z]+\.[A-Z]$")]
    bad = r"(?i)warrant|\bunits?\b|\bright(s)?\b|preferred|depositary shares? representing|notes? due|debentures|% "
    d = d[~d.name.str.contains(bad, regex=True)]
    d["ticker"] = d.symbol.str.replace(".", "-", regex=False)
    d["name"] = d.name.str.replace(r"\s*-\s*(Class [A-Z] )?Common Stock.*$", "", regex=True).str.strip()
    return d.drop_duplicates("symbol")[["symbol", "ticker", "name", "board"]]


def asx_symbols():
    """All ASX-listed companies (ASX directory file; falls back to the older CSV)."""
    for url in ("https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file?access_token=83ff96335c2d45a094df02a206a39ff4",
                "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"):
        r = _get(url)
        if r is None:
            continue
        txt = r.text
        try:
            if "ASX code" in txt[:400] and "Company name" in txt[:400]:
                d = pd.read_csv(io.StringIO(txt), skiprows=next(i for i, l in enumerate(txt.splitlines()) if "ASX code" in l))
                code, name = "ASX code", "Company name"
            else:
                d = pd.read_csv(io.StringIO(txt))
                code = next(c for c in d.columns if "code" in c.lower())
                name = next(c for c in d.columns if "name" in c.lower())
            d = d[[code, name]].dropna()
            sym = d[code].astype(str).str.strip().str.upper()
            res = pd.DataFrame({"symbol": sym, "ticker": sym + ".AX", "name": d[name].astype(str).str.strip(), "board": "ASX"})
            res = res[res.symbol.str.match(r"^[A-Z0-9]{3,4}$")]
            if len(res) > 500:
                print("ASX list", len(res), "from", url.split("?")[0])
                return res.drop_duplicates("symbol")
        except Exception as e:  # noqa: BLE001
            print("ASX parse failed", url.split("?")[0], e)
    r = _get("https://en.wikipedia.org/wiki/S%26P/ASX_200")
    if r is not None:
        for t in pd.read_html(io.StringIO(r.text)):
            cols = [str(c).lower() for c in t.columns]
            if any("code" in c for c in cols):
                code = t.columns[[i for i, c in enumerate(cols) if "code" in c][0]]
                name = t.columns[[i for i, c in enumerate(cols) if "company" in c or "name" in c][0]]
                sym = t[code].astype(str).str.strip().str.upper()
                print("ASX fallback: S&P/ASX 200 from Wikipedia", len(t))
                return pd.DataFrame({"symbol": sym, "ticker": sym + ".AX", "name": t[name].astype(str), "board": "ASX 200"})
    raise RuntimeError("no ASX company list available")


def uk_constituents():
    """FTSE 100 + FTSE 250 from Wikipedia: symbol (Yahoo form without .L, e.g. BT-A), ticker (.L), name, sector (ICB), index."""
    out = []
    for url, ix in (("https://en.wikipedia.org/wiki/FTSE_100_Index", "FTSE 100"), ("https://en.wikipedia.org/wiki/FTSE_250_Index", "FTSE 250")):
        r = _get(url)
        if r is None:
            continue
        for t in pd.read_html(io.StringIO(r.text)):
            cols = {str(c).lower(): c for c in t.columns}
            tk = next((cols[c] for c in cols if "ticker" in c or "epic" in c), None)
            nm = next((cols[c] for c in cols if "company" in c), None)
            if tk is None or nm is None or len(t) < 50:
                continue
            sc = next((cols[c] for c in cols if "sector" in c or "industry" in c), None)
            sym = t[tk].astype(str).str.strip().str.upper().str.rstrip(".").str.replace(".", "-", regex=False)
            out.append(pd.DataFrame({"symbol": sym, "name": t[nm].astype(str).str.strip(), "sector": t[sc].astype(str).str.strip() if sc is not None else None, "index": ix}))
            break
    if not out:
        raise RuntimeError("no UK constituent list available")
    d = pd.concat(out).drop_duplicates("symbol")
    d = d[d.symbol.str.match(r"^[A-Z0-9][A-Z0-9-]{0,5}$")]
    d["ticker"] = d.symbol + ".L"
    print("UK list", len(d))
    return d


def uk_symbols():
    d = uk_constituents()
    return pd.DataFrame({"symbol": d.symbol, "ticker": d.ticker, "name": d.name, "board": d["index"]})


def symbols(market):
    return {"NSE": nse_symbols, "US": us_symbols, "ASX": asx_symbols, "UK": uk_symbols}[market]()
