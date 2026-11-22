"""Relative rotation of the official sector benchmarks for the US and Australia (20 Nov 2026, Amritpal: "Yes" to matching India).
  US  : the 11 SPDR Select Sector ETFs vs the S&P 500
  ASX : the S&P/ASX 200 sector indices vs the ASX 200
Same formulas and output shape as tools/sector_rrg.py (weekly 8 weeks / daily 10 sessions). Yahoo daily closes.
Usage: python tools/world_sector_rrg.py US|ASX [--dry]  -> data/scan/us|asx/sector_rrg.json"""
import json
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools")
from sector_rrg import view, write_hist  # noqa: E402

CFG = {
    "US": dict(bench=("^GSPC", "S&P 500"), out="data/scan/us/sector_rrg.json", names={
        "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy", "XLI": "Industrials", "XLY": "Cons Discretionary",
        "XLP": "Cons Staples", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication"}),
    "ASX": dict(bench=("^AXJO", "ASX 200"), out="data/scan/asx/sector_rrg.json", names={
        "^AXEJ": "Energy", "^AXMJ": "Materials", "^AXNJ": "Industrials", "^AXDJ": "Cons Discretionary", "^AXSJ": "Cons Staples",
        "^AXHJ": "Health Care", "^AXFJ": "Financials", "^AXIJ": "Info Tech", "^AXTJ": "Communication", "^AXUJ": "Utilities", "^AXPJ": "A-REITs"}),
    # 21 Nov 2026 (Amritpal: "also commodities, coins rotation charts"): commodities vs a broad commodity ETF (Invesco DB Commodity, DBC);
    # coins vs Bitcoin (does each coin beat holding BTC?). Same formulas; Yahoo daily closes (coins trade 7 days, weeks end Friday).
    "COMM": dict(bench=("DBC", "commodity basket (DBC)"), out="data/scan/comm_rrg.json", names={
        "GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "HG=F": "Copper", "ALI=F": "Aluminium", "CL=F": "Crude oil", "BZ=F": "Brent",
        "NG=F": "Natural gas", "ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soybeans", "KC=F": "Coffee", "CC=F": "Cocoa", "SB=F": "Sugar",
        "CT=F": "Cotton", "LE=F": "Live cattle"}),
    "CRYPTO": dict(bench=("BTC-USD", "Bitcoin"), out="data/scan/crypto_rrg.json", names={
        "ETH-USD": "Ether", "SOL-USD": "Solana", "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano", "DOGE-USD": "Dogecoin",
        "TRX-USD": "Tron", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink", "DOT-USD": "Polkadot", "LTC-USD": "Litecoin",
        "BCH-USD": "Bitcoin Cash", "XLM-USD": "Stellar", "SHIB-USD": "Shiba Inu", "HBAR-USD": "Hedera", "NEAR-USD": "NEAR",
        "ATOM-USD": "Cosmos", "XMR-USD": "Monero", "ETC-USD": "Ethereum Classic"}),
    # 21 Nov 2026 (Amritpal: "coins look improving / leading but they are all falling - is it because BTC is also falling?"):
    # the same coins plus Bitcoin against US dollars (absolute trend: RS = price itself)
    "CRYPTOUSD": dict(bench=("USD", "US$ (absolute)"), out="data/scan/cryptousd_rrg.json", names={
        "BTC-USD": "Bitcoin", "ETH-USD": "Ether", "SOL-USD": "Solana", "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano",
        "DOGE-USD": "Dogecoin", "TRX-USD": "Tron", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink", "DOT-USD": "Polkadot",
        "LTC-USD": "Litecoin", "BCH-USD": "Bitcoin Cash", "XLM-USD": "Stellar", "SHIB-USD": "Shiba Inu", "HBAR-USD": "Hedera",
        "NEAR-USD": "NEAR", "ATOM-USD": "Cosmos", "XMR-USD": "Monero", "ETC-USD": "Ethereum Classic"}),
    # 21 Nov 2026 (Amritpal: "a world markets chart comparing all markets and other asset classes with a benchmark"): US-dollar ETFs
    # (one currency, so the comparison is fair) vs MSCI All-Country World (ACWI = the global stock market); WORLDUSD = same set in US$
    "WORLD": dict(bench=("ACWI", "MSCI All-Country World (ACWI)"), out="data/scan/world_rrg.json", names={
        "SPY": "US S&P 500", "QQQ": "US Nasdaq 100", "IWM": "US small caps", "VGK": "Europe", "EWU": "UK", "EWG": "Germany", "EWJ": "Japan",
        "MCHI": "China", "EWH": "Hong Kong", "INDA": "India", "EWA": "Australia", "EWY": "Korea", "EWT": "Taiwan", "EWZ": "Brazil",
        "EWC": "Canada", "EEM": "Emerging mkts", "GLD": "Gold", "SLV": "Silver", "DBC": "Commodities", "USO": "Crude oil",
        "TLT": "US long bonds", "AGG": "US bonds (all)", "EMB": "EM bonds", "UUP": "US dollar", "VNQ": "US real estate", "BTC-USD": "Bitcoin"}),
}
# 21 Nov 2026 (Amritpal: "take authentic"): the 11 official GICS sectors (the MSCI / S&P sector standard) for the whole world, via the
# iShares Global sector ETFs (S&P Global 1200 sector indices), vs MSCI ACWI. AI infrastructure sits across Info Tech (chips, cloud),
# Utilities (power) and Industrials (grid, electrical equipment) rather than being one dot.
CFG["WSECT"] = dict(bench=("ACWI", "MSCI All-Country World (ACWI)"), out="data/scan/wsect_rrg.json", names={
    "IXN": "Info Tech", "IXG": "Financials", "IXJ": "Health Care", "IXC": "Energy", "EXI": "Industrials", "MXI": "Materials",
    "JXI": "Utilities", "KXI": "Cons Staples", "RXI": "Cons Discretionary", "IXP": "Communication", "REET": "Real Estate"})
# 22 Nov 2026 (Amritpal: "have we plotted industries and themes?"): US themes = the main theme ETFs vs the S&P 500
CFG["USTHEME"] = dict(bench=("^GSPC", "S&P 500"), out="data/scan/us/theme_rrg.json", names={
    "SMH": "Semiconductors", "IGV": "Software", "CIBR": "Cybersecurity", "SKYY": "Cloud", "BOTZ": "Robotics & AI", "XBI": "Biotech",
    "IHI": "Medical devices", "ITB": "Homebuilders", "KRE": "Regional banks", "IAI": "Brokers", "KIE": "Insurance", "XRT": "Retail",
    "PEJ": "Leisure", "JETS": "Airlines", "IYT": "Transports", "PAVE": "Infrastructure", "ITA": "Aerospace & defence", "XME": "Metals & mining",
    "XOP": "Oil & gas E&P", "TAN": "Solar", "ICLN": "Clean energy", "URA": "Uranium", "LIT": "Lithium & battery", "GDX": "Gold miners"})
# 22 Nov 2026 (Amritpal: "add currency pairs to all systems"): currencies on the rotation map - each currency's value in US$ (absolute
# trend, like coins in US$) and in rupees (what 1 unit costs in Rs, for India).
CFG["FX"] = dict(bench=("USD", "US$ (absolute)"), out="data/scan/fx_rrg.json", names={
    "EURUSD=X": "Euro", "GBPUSD=X": "Pound", "JPYUSD=X": "Yen", "AUDUSD=X": "Australian $", "NZDUSD=X": "NZ $", "CADUSD=X": "Canadian $",
    "CHFUSD=X": "Swiss franc", "CNYUSD=X": "Yuan", "INRUSD=X": "Rupee", "SGDUSD=X": "Singapore $", "KRWUSD=X": "Won", "BRLUSD=X": "Real",
    "MXNUSD=X": "Mexican peso", "ZARUSD=X": "Rand", "TRYUSD=X": "Lira"})
CFG["FXINR"] = dict(bench=("INR", "Rupee (absolute)"), out="data/scan/fxinr_rrg.json", names={
    "USDINR=X": "US dollar", "EURINR=X": "Euro", "GBPINR=X": "Pound", "JPYINR=X": "Yen", "AUDINR=X": "Australian $", "SGDINR=X": "Singapore $",
    "AEDINR=X": "UAE dirham", "CNYINR=X": "Yuan", "CHFINR=X": "Swiss franc", "CADINR=X": "Canadian $", "NZDINR=X": "NZ $"})
CFG["WORLDUSD"] = dict(bench=("USD", "US$ (absolute)"), out="data/scan/worldusd_rrg.json", names={"ACWI": "World stocks (ACWI)", **CFG["WORLD"]["names"]})


def main(mk, dry=False):
    cf = CFG[mk]; b, bname = cf["bench"]
    d = yf.download(list(cf["names"]) + ([] if b in ("USD", "INR") else [b]), period="2y", interval="1d", progress=False, auto_adjust=True, group_by="column", threads=True)["Close"]
    d = d.dropna(how="all").ffill()
    bench = pd.Series(1.0, index=d.index) if b in ("USD", "INR") else d.pop(b); C = d[[k for k in cf["names"] if k in d.columns and d[k].notna().sum() > 120]]
    print(mk, "got", list(C.columns), "last", C.index[-1].date(), flush=True)
    W = C.resample("W-FRI").last(); BW = bench.resample("W-FRI").last()
    if W.index[-1] > C.index[-1]:
        W.index = list(W.index[:-1]) + [C.index[-1]]; BW.index = W.index
    out = dict(asof=str(C.index[-1].date()), bench=bname, weekly=view(W, BW, 10, 1, 3, 8, cf["names"]), daily=view(C, bench, 50, 10, 5, 10, cf["names"]),
               method=__doc__)
    for v in ("weekly", "daily"):
        print(mk, v, {q: [k for k, r in out[v].items() if r["now"] == q] for q in ("Leading", "Improving", "Weakening", "Lagging")}, flush=True)
    if mk == "USTHEME":   # 22 Nov 2026: each theme's stocks (us_meta theme column = the ETF), liquid ones the scan tracks
        try:
            import os as _os
            liq = set(json.load(open("data/scan/us/stock_weekly.json"))["s"]) if _os.path.exists("data/scan/us/stock_weekly.json") else set()
            M = pd.read_csv("data/universe/us_meta.csv")
            out["members"] = {cf["names"][e]: [dict(symbol=r.symbol, name=str(r.name)[:60]) for r in M[(M.theme == e) & (M.symbol.isin(liq) if liq else True)].itertuples()][:60]
                              for e in cf["names"]}
            out["etf"] = {v: k for k, v in cf["names"].items()}
        except Exception as e:  # noqa: BLE001
            print("theme members", e)
    if not dry:
        json.dump(out, open(cf["out"], "w"), separators=(",", ":"))
        write_hist(cf["out"].replace(".json", "_hist.json"), C, bench, W, BW, cf["names"])


if __name__ == "__main__":
    for m in [a for a in sys.argv[1:] if not a.startswith("--")] or ["US", "ASX"]:
        try:
            main(m, "--dry" in sys.argv)
        except Exception as e:  # noqa: BLE001
            print("FAILED", m, e)
