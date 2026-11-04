"""Sector / theme layer for the US and ASX top-down view (the NSE version lives in sector_state.py).

US  : sector = SPDR sector ETF from the stock's Nasdaq-screener sector; theme = industry ETF matched from its industry text.
      RS benchmark for sectors/themes = S&P 500 (^GSPC); market for the 3-month test = S&P 500.
ASX : sector = S&P/ASX 200 GICS sector index from the stock's GICS industry group (ASX company directory);
      RS benchmark = S&P/ASX 200 (^AXJO). Themes: none with a reliable stock map (ASX lists one group per company).
Stock meta (sector, industry, listing year/date) -> data/universe/<mkt>_meta.csv via fetch_meta(market)."""
import io
import re
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}

US_SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy", "XLI": "Industrials",
              "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials",
              "XLRE": "Real Estate", "XLC": "Communication Services"}
US_SECTOR_OF = {"Technology": "XLK", "Finance": "XLF", "Health Care": "XLV", "Energy": "XLE", "Industrials": "XLI",
                "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Utilities": "XLU", "Basic Materials": "XLB",
                "Real Estate": "XLRE", "Telecommunications": "XLC"}
# industry text (Nasdaq screener) -> theme ETF; first match wins
US_THEMES = [
    (r"semiconductor", "SMH", "Semiconductors"),
    (r"software|edp services|computer (communications|peripheral)|computer manufacturing", "IGV", "Software & IT"),
    (r"biotech|biological products", "XBI", "Biotech"),
    (r"major pharma|pharmaceutical", "PPH", "Pharma"),
    (r"medical|dental|ophthalmic|hospital|health care", "IHI", "Medical devices & care"),
    (r"major banks", "KBE", "Banks"),
    (r"banks|savings institutions", "KRE", "Regional banks"),
    (r"investment bankers|brokers|investment managers|finance: consumer|finance companies|finance/investors", "IAI", "Brokers & asset managers"),
    (r"insurance|property-casualty", "KIE", "Insurance"),
    (r"aerospace|military|ordnance", "ITA", "Aerospace & defence"),
    (r"oilfield|oil & gas production|integrated oil|oil refining|natural gas distribution|coal", "XOP", "Oil & gas"),
    (r"precious metals|gold", "GDX", "Gold miners"),
    (r"metal mining|steel|aluminum|non-ferrous|mining", "XME", "Metals & mining"),
    (r"homebuilding|building products|building materials|construction", "ITB", "Homebuilders & construction"),
    (r"airlines", "JETS", "Airlines"),
    (r"trucking|railroads|marine transportation|air freight|transportation services", "IYT", "Transport"),
    (r"restaurants|hotels|casinos|recreational|leisure|movies|services-misc. amusement", "PEJ", "Leisure"),
    (r"retail|department|clothing|apparel|shoe|catalog|specialty stores|consumer specialties", "XRT", "Retail"),
    (r"industrial machinery|electrical products|engineering|pollution control|metal fabrications|electric utilities", "PAVE", "Infrastructure"),
]
US_BROAD = {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow", "RSP": "S&P 500 EW", "MDY": "MidCap 400", "^RUT": "Russell 2000"}

ASX_SECTORS = {"^AXFJ": "Financials", "^AXMJ": "Materials", "^AXEJ": "Energy", "^AXIJ": "Info Tech", "^AXHJ": "Health Care",
               "^AXNJ": "Industrials", "^AXDJ": "Consumer Discretionary", "^AXSJ": "Consumer Staples", "^AXPJ": "A-REIT",
               "^AXTJ": "Communication Services", "^AXUJ": "Utilities"}
ASX_GROUP = [  # GICS industry group text -> sector index
    (r"bank|financial|insurance", "^AXFJ"), (r"material", "^AXMJ"), (r"energy", "^AXEJ"),
    (r"software|technology hardware|semiconductor", "^AXIJ"), (r"health|pharma|biotech", "^AXHJ"),
    (r"capital goods|commercial|transportation", "^AXNJ"),
    (r"automobile|durables|consumer services|retailing|discretionary", "^AXDJ"),
    (r"food|beverage|household|staples", "^AXSJ"), (r"real estate|reit", "^AXPJ"),
    (r"telecom|media", "^AXTJ"), (r"utilit", "^AXUJ")]
ASX_THEMES = [("^AXGD", "Gold (All Ords)"), ("^AXMM", "Metals & mining")]  # context only (no stock map)
ASX_BROAD = {"^ATLI": "ASX 20", "^AXJO": "ASX 200", "^AXKO": "ASX 300", "^AORD": "All Ords", "^AXSO": "Small Ords"}

CFG = {"US": dict(bench="^GSPC", market="^GSPC", sectors=US_SECTORS, themes={t: n for _, t, n in US_THEMES}, broad=US_BROAD),
       "ASX": dict(bench="^AXJO", market="^AXJO", sectors=ASX_SECTORS, themes=dict(ASX_THEMES), broad=ASX_BROAD)}


def index_tickers(market):
    c = CFG[market]
    return list(dict.fromkeys(list(c["broad"]) + list(c["sectors"]) + list(c["themes"])))


def us_theme(industry):
    s = str(industry or "").lower()
    for pat, etf, _ in US_THEMES:
        if re.search(pat, s):
            return etf
    return None


def asx_sector(group):
    s = str(group or "").lower()
    for pat, ix in ASX_GROUP:
        if re.search(pat, s):
            return ix
    return None


def _get(url, tries=3):
    for _ in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200 and r.content:
                return r
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    return None


def fetch_meta(market):
    """DataFrame symbol, name, sector, industry, sector_index, theme, listed (date or year)."""
    if market == "US":
        r = _get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true")
        rows = (r.json().get("data") or {}).get("rows") or [] if r is not None else []
        d = pd.DataFrame(rows)
        if not len(d):
            raise RuntimeError("nasdaq screener empty")
        d["symbol"] = d.symbol.astype(str).str.strip().str.replace("/", ".", regex=False)
        d["sector_index"] = d.sector.map(US_SECTOR_OF)
        d["theme"] = d.industry.map(us_theme)
        d["listed"] = d.get("ipoyear")
        return d[["symbol", "name", "sector", "industry", "sector_index", "theme", "listed"]]
    if market == "ASX":
        r = _get("https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file?access_token=83ff96335c2d45a094df02a206a39ff4")
        if r is None:
            raise RuntimeError("ASX directory unavailable")
        txt = r.text
        d = pd.read_csv(io.StringIO(txt), skiprows=next((i for i, ln in enumerate(txt.splitlines()) if "ASX code" in ln), 0))
        d.columns = [c.strip() for c in d.columns]
        col = lambda k: next((c for c in d.columns if k in c.lower()), None)  # noqa: E731
        out = pd.DataFrame({"symbol": d[col("code")].astype(str).str.strip().str.upper(), "name": d[col("name")].astype(str).str.strip(),
                            "industry": d[col("gics")] if col("gics") else None,
                            "listed": d[col("listing")] if col("listing") else None})
        out["sector_index"] = out.industry.map(asx_sector)
        out["sector"] = out.sector_index.map(ASX_SECTORS)
        out["theme"] = None
        return out[["symbol", "name", "sector", "industry", "sector_index", "theme", "listed"]]
    raise ValueError(market)
