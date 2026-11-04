"""Constituents of every NSE thematic index -> data/universe/themes.csv (Symbol, Theme) and data/universe/themes/*.csv.
Finds each index page from niftyindices.com's thematic list, then its 'Index Constituent' CSV; falls back to guessed file
names on niftyindices.com and nsearchives. Log: data/universe/themes/_log.txt."""
import io
import os
import re
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sector_state import THEMATIC  # noqa: E402

OUT = "data/universe/themes"
os.makedirs(OUT, exist_ok=True)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Accept": "text/html,application/xhtml+xml,text/csv,*/*", "Referer": "https://www.niftyindices.com/"})
BASE = "https://www.niftyindices.com"
log = []


def get(url, timeout=30):
    for _ in range(2):
        try:
            r = s.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception as e:  # noqa: BLE001
            log.append(f"err {url} {e}")
        time.sleep(1)
    return None


def csv_ok(r):
    if r is None or b"Symbol" not in r.content[:400]:
        return None
    try:
        d = pd.read_csv(io.BytesIO(r.content)); d.columns = [c.strip() for c in d.columns]
        return d if "Symbol" in d.columns and len(d) else None
    except Exception:  # noqa: BLE001
        return None


def slug(name):
    n = name.replace("NIFTY", "").replace("&", "").replace("-", " ").replace("(", "").replace(")", "").replace(":", "").replace("%", "")
    return re.sub(r"\s+", "", n).lower()


def main():
    # 1) index pages linked from the thematic list
    pages = {}
    r = get(f"{BASE}/indices/equity/thematic-indices")
    if r is not None:
        for href, text in re.findall(r'href="(/indices/equity/thematic-indices/[^"#?]+)"[^>]*>\s*([^<]+?)\s*<', r.text):
            pages[text.strip().upper()] = BASE + href
    log.append(f"index pages found: {len(pages)}")
    rows = []
    for name in THEMATIC:
        d, src = None, None
        page = next((u for t, u in pages.items() if t.replace("NIFTY", "").strip() == name.replace("NIFTY", "").strip()), None)
        if page:
            p = get(page)
            if p is not None:
                for link in re.findall(r'href="([^"]*IndexConstituent/[^"]+\.csv)"', p.text, flags=re.I):
                    u = link if link.startswith("http") else BASE + link
                    d = csv_ok(get(u))
                    if d is not None:
                        src = u; break
        if d is None:
            sg = slug(name)
            for fn in (f"ind_nifty{sg}list.csv", f"ind_nifty{sg}_list.csv", f"ind_{sg}list.csv", f"ind_{sg}_list.csv"):
                for u in (f"{BASE}/IndexConstituent/{fn}", f"https://nsearchives.nseindia.com/content/indices/{fn}"):
                    d = csv_ok(get(u))
                    if d is not None:
                        src = u; break
                if d is not None:
                    break
        if d is None:
            log.append(f"MISSING {name}")
            continue
        d.to_csv(f"{OUT}/{slug(name)}.csv", index=False)
        rows += [dict(Symbol=str(x).strip(), Theme=name) for x in d.Symbol]
        log.append(f"ok {name}: {len(d)} from {src}")
        time.sleep(0.5)
    T = pd.DataFrame(rows)
    if len(T):
        T.to_csv("data/universe/themes.csv", index=False)
    open(f"{OUT}/_log.txt", "w").write("\n".join(log))
    print("\n".join(log[-60:]))
    print("themes with constituents:", T.Theme.nunique() if len(T) else 0, "rows", len(T))


if __name__ == "__main__":
    main()
