"""probe: other free sources for the latest US / UK / ASX daily closes, from GitHub Actions (20 Nov 2026)"""
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "*/*"}
tests = [
    ("stooq US", "https://stooq.com/q/d/l/?s=aapl.us&i=d"),
    ("stooq UK", "https://stooq.com/q/d/l/?s=hsba.uk&i=d"),
    ("stooq ASX", "https://stooq.com/q/d/l/?s=bhp.au&i=d"),
    ("stooq bulk day", "https://stooq.com/db/d/?d=20261119&t=d"),
    ("nasdaq hist", "https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2026-11-10&limit=10"),
    ("nasdaq screener (all US, last price)", "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5&download=true"),
    ("google finance", "https://www.google.com/finance/quote/HSBA:LON"),
    ("yahoo chart v8 UK", "https://query1.finance.yahoo.com/v8/finance/chart/HSBA.L?range=10d&interval=1d"),
    ("lse", "https://www.londonstockexchange.com/stock/HSBA/hsbc-holdings-plc/company-page"),
    ("asx", "https://www.asx.com.au/asx/1/share/BHP"),
    ("cboe/bats US daily", "https://www.cboe.com/us/equities/market_statistics/historical_market_volume/"),
]
for nm, u in tests:
    try:
        r = requests.get(u, headers=H, timeout=30)
        body = r.text[:300].replace("\n", " | ")
        print(f"R| {nm}: {r.status_code} {len(r.content)} bytes :: {body}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"R| {nm}: ERROR {e}", flush=True)
