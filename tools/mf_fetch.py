"""Mutual fund NAV history from AMFI (public data, via the free mfapi.in mirror of AMFI's historical NAVs).
Universe: open-ended EQUITY schemes + index funds/ETF-tracking index funds, DIRECT plan, GROWTH option only.
Writes data/mf/meta.csv (code, name, category, amc) and data/mf/nav.parquet (Date, code, nav)."""
import concurrent.futures as cf
import io
import os
import re
import sys
import time

import pandas as pd
import requests

OUT = "data/mf"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (trend-desk research)"


def universe():
    for url in ("https://portal.amfiindia.com/spages/NAVAll.txt", "https://www.amfiindia.com/spages/NAVAll.txt"):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 200 and "Scheme Code" in r.text:
                break
        except Exception as e:  # noqa: BLE001
            print("navall fail", url, e)
    rows, cat, amc = [], "", ""
    for ln in r.text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ";" not in ln:
            if "Schemes(" in ln or "Scheme(" in ln:
                cat = ln
            else:
                amc = ln
            continue
        p = ln.split(";")
        if len(p) < 6 or not p[0].isdigit():
            continue
        rows.append(dict(code=int(p[0]), name=p[3].strip(), category=cat, amc=amc))
    u = pd.DataFrame(rows)
    keep_cat = u.category.str.contains(r"Open Ended Schemes\((Equity Scheme|Other Scheme - Index Funds)", regex=True)
    n = u.name.str.lower()
    direct = n.str.contains("direct")
    growth = n.str.contains("growth") & ~n.str.contains(r"idcw|dividend|bonus|payout|reinvest", regex=True)
    u = u[keep_cat & direct & growth].copy()
    u["category"] = u.category.str.extract(r"\((.*)\)")[0].str.replace("Equity Scheme - ", "", regex=False).str.replace("Other Scheme - ", "", regex=False)
    return u.drop_duplicates("code")


def hist(code):
    for _ in range(3):
        try:
            r = S.get(f"https://api.mfapi.in/mf/{code}", timeout=40)
            if r.status_code == 200:
                d = r.json().get("data") or []
                if d:
                    x = pd.DataFrame(d)
                    x["Date"] = pd.to_datetime(x["date"], format="%d-%m-%Y")
                    x["nav"] = pd.to_numeric(x["nav"], errors="coerce")
                    x = x[x.nav > 0][["Date", "nav"]]
                    x["code"] = code
                    return x
                return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    u = universe()
    print("schemes", len(u), u.category.value_counts().to_dict(), flush=True)
    u.to_csv(f"{OUT}/meta.csv", index=False)
    frames = []
    with cf.ThreadPoolExecutor(8) as ex:
        for k, x in enumerate(ex.map(hist, u.code)):
            if x is not None:
                frames.append(x)
            if k % 200 == 0:
                print(k, len(frames), flush=True)
    nav = pd.concat(frames).sort_values(["code", "Date"])
    nav.to_parquet(f"{OUT}/nav.parquet", index=False)
    print("nav rows", len(nav), "funds", nav.code.nunique(), nav.Date.min(), nav.Date.max())


if __name__ == "__main__":
    main()
