"""Probe (22 Nov 2026): official news feeds reachable from GitHub Actions? PIB, RBI, SEBI, DGTR, CBIC, DGFT."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
U = ["https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
     "https://pib.gov.in/ViewRss.aspx", "https://pib.gov.in/allRel.aspx",
     "https://www.rbi.org.in/pressreleases_rss.xml", "https://www.rbi.org.in/notifications_rss.xml",
     "https://www.sebi.gov.in/sebirss.xml", "https://www.dgtr.gov.in/", "https://www.dgtr.gov.in/anti-dumping-cases",
     "https://www.cbic.gov.in/", "https://www.dgft.gov.in/CP/?opt=notification",
     "https://www.nseindia.com/api/corporate-announcements?index=equities", "https://pib.gov.in/PressReleseDetailm.aspx?PRID=2338349"]
S = requests.Session(); S.headers.update(UA)
for u in U:
    try:
        r = S.get(u, timeout=30)
        t = r.text
        items = re.findall(r"<item>.*?<title>(.*?)</title>.*?(?:<pubDate>(.*?)</pubDate>)?", t, re.S)[:4]
        print("R|", u, r.status_code, len(t), r.headers.get("content-type"), "items", len(re.findall(r"<item>", t)))
        for it in items:
            print("R|   ", [re.sub(r"<!\[CDATA\[|\]\]>", "", x).strip()[:140] for x in it])
        if not items:
            print("R|    head", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))[:300])
    except Exception as e:  # noqa: BLE001
        print("R|", u, "ERR", e)
