"""Probe 2 (22 Nov 2026): PIB English feeds, Google News RSS (named outlets), NSE announcements shape."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
S = requests.Session(); S.headers.update(UA)
v = S.get("https://pib.gov.in/ViewRss.aspx", timeout=30).text
links = sorted(set(re.findall(r'href="([^"]*Rss[^"]*)"', v, re.I)))
print("R| pib rss links", len(links)); [print("R|  ", l) for l in links[:60]]
for u in ["https://pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
          "https://news.google.com/rss/search?q=%22FDI%22+%22public+sector+banks%22+when:30d&hl=en-IN&gl=IN&ceid=IN:en",
          "https://news.google.com/rss/search?q=cabinet+approves+scheme+when:7d&hl=en-IN&gl=IN&ceid=IN:en"]:
    r = S.get(u, timeout=30); t = r.content.decode("utf-8", "replace")
    its = re.findall(r"<item>(.*?)</item>", t, re.S)
    print("R|", u, r.status_code, "items", len(its))
    for it in its[:6]:
        g = lambda k: (re.search(f"<{k}[^>]*>(.*?)</{k}>", it, re.S) or [None, ""])[1]  # noqa: E731
        print("R|   ", re.sub(r"<!\[CDATA\[|\]\]>", "", g("title")).strip()[:150], "|", g("pubDate"), "|", re.sub(r"<[^>]+>", "", g("source"))[:40])
import json
a = S.get("https://www.nseindia.com", timeout=20)
r = S.get("https://www.nseindia.com/api/corporate-announcements?index=equities", timeout=30).json()
print("R| nse keys", list(r[0].keys())); [print("R|   ", x.get("symbol"), "|", x.get("desc"), "|", (x.get("attchmntText") or "")[:140]) for x in r[:12]]
