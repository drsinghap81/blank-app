"""News clues: government / regulator actions that can move a whole industry (22 Nov 2026, Amritpal, after the PSU-bank look-back
found the 21 Oct "FDI cap in PSU banks to 49%" report a week before the rally: "add all authentic news clues, especially similar
types as for PSU").

Sources (checked from GitHub Actions 22 Nov 2026):
  official  RBI press releases + notifications (rbi.org.in RSS); government outlets in Google News (PIB, DD News, News On AIR)
  reports   Google News RSS, India edition, ONLY from named financial / national outlets (OUTLETS) - shown as "Report"
Event types searched (TYPES): FDI / foreign-ownership caps, Cabinet approvals and outlays, PLI, anti-dumping / safeguard / customs
duty, export bans / curbs, minimum import price, bank mergers, privatisation / stake sales, GST rate changes, MSP / FRP,
Defence Acquisition Council approvals, ethanol blending, RBI rule changes, plus "government plans / considering" reports.
Each item is matched to NSE basic industries by keywords (IND_KEYS). Direction is only marked where the words say it
(denies / no plan / rollback / ban = negative). Nothing here is a tested signal - it tells you a story exists.
Writes data/scan/news_clues.json (last 60 days, de-duplicated)."""
import email.utils
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import requests

OUT = "data/scan/news_clues.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
OFFICIAL = {"PIB", "Press Information Bureau", "DD News", "News On AIR", "All India Radio", "Reserve Bank of India", "RBI", "SEBI", "PIB India"}
OUTLETS = OFFICIAL | {"Business Standard", "The Economic Times", "Economic Times", "Mint", "Livemint", "Reuters", "Moneycontrol", "Moneycontrol.com",
                      "Business Today", "NDTV Profit", "CNBC TV18", "CNBCTV18", "CNBC-TV18", "The Financial Express", "Financial Express",
                      "The Hindu BusinessLine", "BusinessLine", "The Hindu", "Hindustan Times", "The Times of India", "Bloomberg", "Bloomberg.com",
                      "ETBFSI.com", "ETEnergyWorld.com", "ETAuto.com", "ET Infra", "ETManufacturing.in", "Fortune India", "Zee Business", "Upstox"}
TYPES = {
    "FDI / foreign cap": ['"FDI limit"', '"FDI cap"', '"foreign investment limit"', '"foreign ownership" India'],
    "Cabinet approval": ['"Cabinet approves"', '"Union Cabinet" approves'],
    "PLI / incentive": ['"PLI scheme"', '"production linked incentive"'],
    "Duty / trade": ['"anti-dumping duty"', '"safeguard duty"', '"customs duty" cut', '"import duty" India', '"minimum import price"', '"export ban" India', '"export duty" India'],
    "Merger / sale": ['"bank merger" India', '"PSU merger"', '"stake sale" government', 'privatisation PSU', '"offer for sale" government'],
    "Tax / GST": ['"GST Council"', '"GST rate" cut'],
    "Prices / support": ['MSP hike', 'FRP sugarcane', '"ethanol blending"', '"ethanol price"'],
    "Defence": ['"Defence Acquisition Council"', '"DAC approves"'],
    "Plans / reports": ['"government plans" India sector', '"government considering" India', '"draft cabinet note"', '"inter-ministerial"'],
}
# keyword (regex, lower case) -> NSE basic industries
IND_KEYS = [
    (r"public sector bank|psu bank|\bpsbs?\b|state-run bank|state run bank|government bank", ["Public Sector Bank"]),
    (r"private bank|private sector bank", ["Private Sector Bank"]),
    (r"\bnbfc|non-banking financ", ["Non Banking Financial Company (NBFC)"]),
    (r"microfinance", ["Microfinance Institutions"]),
    (r"housing finance", ["Housing Finance Company"]),
    (r"\binsurance\b|\binsurers?\b", ["Life Insurance", "General Insurance"]),
    (r"\bpharma|\bapis?\b|bulk drug|drug intermediate", ["Pharmaceuticals"]),
    (r"medical device", ["Medical Equipment & Supplies"]),
    (r"\bsteel\b", ["Iron & Steel", "Iron & Steel Products"]),
    (r"aluminium|aluminum", ["Aluminium"]),
    (r"copper|zinc", ["Aluminium Copper & Zinc Products", "Diversified Metals"]),
    (r"\bcoal\b", ["Coal"]),
    (r"\bmining\b|\bminerals?\b", ["Industrial Minerals", "Diversified Metals"]),
    (r"solar|renewable|green energy|wind energy", ["Power Generation", "Other Electrical Equipment"]),
    (r"transmission|power grid|electricity grid", ["Heavy Electrical Equipment", "Cables - Electricals", "Integrated Power Utilities"]),
    (r"power sector|thermal power|discom", ["Power Generation", "Integrated Power Utilities"]),
    (r"airport|\budan\b|aviation", ["Airport & Airport services", "Airline"]),
    (r"\brailways?\b|\brail\b|vande bharat|\bwagons?\b", ["Railway Wagons", "Civil Construction"]),
    (r"defence|defense|\bdac\b", ["Aerospace & Defense", "Ship Building & Allied Services", "Explosives"]),
    (r"shipbuild|\bshipping\b|\bports?\b(?! duty)|\bmaritime\b", ["Ship Building & Allied Services", "Shipping", "Port & Port services"]),
    (r"\broads?\b|\bhighways?\b|\bnhai\b", ["Civil Construction", "Road Assets - Toll Annuity Hybrid-Annuity"]),
    (r"cement", ["Cement & Cement Products"]),
    (r"fertili[sz]er|urea|\bdap\b", ["Fertilizers"]),
    (r"pesticide|agrochemical", ["Pesticides & Agrochemicals"]),
    (r"sugar|sugarcane|ethanol", ["Sugar", "Breweries & Distilleries"]),
    (r"\brice\b|\bwheat\b|\bpulses\b|\bonion|\bspices?\b|agri export", ["Other Agricultural Products"]),
    (r"edible oil|palm oil|soybean oil|mustard oil", ["Edible Oil"]),
    (r"food processing|processed food", ["Packaged Foods", "Other Food Products"]),
    (r"\bdairy\b|\bmilk\b", ["Dairy Products"]),
    (r"textile|apparel|garment|cotton|yarn", ["Other Textile Products", "Garments & Apparels"]),
    (r"electronics|semiconductor|\bchips?\b", ["Computers Hardware & Equipments", "Consumer Electronics", "Industrial Products"]),
    (r"\bmobile phones?|smartphone|\btelecom", ["Telecom - Cellular & Fixed line services", "Telecom - Equipment & Accessories"]),
    (r"automobile|\bauto\b|electric vehicle|\bevs?\b|two-wheeler|\bcars?\b", ["Passenger Cars & Utility Vehicles", "2/3 Wheelers", "Auto Components & Equipments"]),
    (r"tyre", ["Tyres & Rubber Products"]),
    (r"oil and gas|\bcrude\b|petroleum|\brefiner|\blpg\b|\bcng\b", ["Oil Exploration & Production", "Refineries & Marketing", "LPG/CNG/PNG/LNG Supplier"]),
    (r"chemical", ["Specialty Chemicals", "Commodity Chemicals"]),
    (r"real estate|housing scheme|affordable housing", ["Residential Commercial Projects"]),
    (r"\btourism\b|\bhotels?\b", ["Hotels & Resorts", "Tour Travel Related Services"]),
    (r"capital market|stock exchange|\bbrokers?\b|\bbroking\b", ["Exchange and Data Platform", "Stockbroking & Allied", "Depositories Clearing Houses and Other Intermediaries"]),
    (r"tobacco|cigarette", ["Cigarettes & Tobacco Products"]),
    (r"liquor|alcohol", ["Breweries & Distilleries"]),
    (r"\bgold\b|jewel", ["Gems Jewellery And Watches"]),
    (r"water supply|jal jeevan", ["Water Supply & Management"]),
    (r"public distribution|\bpds\b", ["Other Agricultural Products"]),
]
NEG = re.compile(r"\bdenies|no plan|no proposal|rolls? back|scrap|withdraw|\bban\b|curb|hike[sd]? duty on export|windfall", re.I)


def fetch(url):
    for k in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.content.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print("retry", url[:80], e)
        time.sleep(3 * (k + 1))
    return ""


def items(xml):
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        g = lambda k: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(f"<{k}[^>]*>(.*?)</{k}>", it, re.S) or [None, ""])[1])).strip()  # noqa: E731
        yield dict(title=g("title"), link=g("link"), date=g("pubDate"), source=re.sub(r"<[^>]+>", "", g("source")))


def when(s):
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def classify(t):
    tl = t.lower(); inds = []
    for rx, L in IND_KEYS:
        if re.search(rx, tl):
            inds += [x for x in L if x not in inds]
    return inds


def main():
    try:
        prev = json.load(open(OUT))
    except Exception:  # noqa: BLE001
        prev = {}
    have = {x["key"]: x for x in prev.get("items", [])}
    new = 0
    for typ, qs in TYPES.items():
        for q in qs:
            u = f"https://news.google.com/rss/search?q={quote_plus(q + f" when:{os.environ.get('BACK', '3')}d")}&hl=en-IN&gl=IN&ceid=IN:en"
            for it in items(fetch(u)):
                src = it["source"]; title = re.sub(r"\s+-\s+[^-]+$", "", it["title"]).strip()
                if src not in OUTLETS or not title:
                    continue
                inds = classify(title)
                if not inds:
                    continue
                key = re.sub(r"[^a-z0-9]+", "", title.lower())[:90]
                if key in have:
                    continue
                d = when(it["date"])
                have[key] = dict(key=key, date=d.strftime("%Y-%m-%d"), title=title, url=it["link"], source=src, official=src in OFFICIAL, type=typ,
                                 industries=inds, neg=bool(NEG.search(title)))
                new += 1
            time.sleep(1)
    for feed, typ in (("https://www.rbi.org.in/pressreleases_rss.xml", "RBI"), ("https://www.rbi.org.in/notifications_rss.xml", "RBI")):
        for it in items(fetch(feed)):
            title = it["title"]; inds = classify(title)
            if not inds or re.search(r"penalty|auction|treasury bill|securities|sanctions list|cancel", title, re.I):
                continue
            key = re.sub(r"[^a-z0-9]+", "", title.lower())[:90]
            if key in have:
                continue
            have[key] = dict(key=key, date=when(it["date"]).strftime("%Y-%m-%d") if it["date"] else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                             title=title, url=it["link"], source="Reserve Bank of India", official=True, type=typ, industries=inds, neg=bool(NEG.search(title)))
            new += 1
    cut = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    L = sorted([x for x in have.values() if x["date"] >= cut], key=lambda x: x["date"], reverse=True)
    by = {}
    for x in L:
        for i in x["industries"]:
            by.setdefault(i, []).append(x["key"])
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), method=__doc__, items=L, by_industry=by)
    os.makedirs("data/scan", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=0)
    print("news clues", len(L), "new", new, "industries", len(by))
    for x in L[:25]:
        print(x["date"], "|", x["source"], "|", x["type"], "|", x["title"][:110], "|", x["industries"][:3], "| NEG" if x["neg"] else "")


if __name__ == "__main__":
    main()
