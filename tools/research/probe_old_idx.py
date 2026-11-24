"""probe: BSE Sensex 1991-2000 from bse-1991-2000.blogspot.com (text pages)"""
import re
import html
import requests
U = {"User-Agent": "Mozilla/5.0"}
base = "https://bse-1991-2000.blogspot.com/"
r = requests.get(base + "p/bse-sensex-historical-prices-in-year_1204.html", headers=U, timeout=30)
links = sorted(set(u.replace("http://", "https://") for u in re.findall(r'https?://bse-1991-2000\.blogspot\.com/p/[^"\'#]+\.html', r.text)))
for u in links:
    t = requests.get(u, headers=U, timeout=30).text
    m = re.search(r"<h3[^>]*post-title[^>]*>(.*?)</h3>", t, re.S); title = re.sub("<[^>]+>", "", m.group(1)).strip() if m else "?"
    b = re.search(r"post-body[^>]*>(.*?)<div class=['\"]post-footer", t, re.S); body = b.group(1) if b else t
    txt = html.unescape(re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body)); txt = re.sub(r"<[^>]+>", " ", txt)
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n") if re.search(r"\d", l)]
    print(f"R| PAGE {title} | {u} | lines {len(lines)}", flush=True)
    for l in lines:
        print("R| L " + l[:160], flush=True)
