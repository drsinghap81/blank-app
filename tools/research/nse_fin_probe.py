"""Probe (14 Nov 2026): what NSE's financial-results endpoints return from a GitHub runner, to design a point-in-time
quarterly EPS / sales / profit history for the Minervini fundamentals test. Saves raw samples to data/research/nse_fin_probe/."""
import json, os, time
import requests
OUT = "data/research/nse_fin_probe"; os.makedirs(OUT, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
for u in ("https://www.nseindia.com/", "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"):
    try: S.get(u, timeout=20)
    except Exception as e: print("warm", e)
rep = {}
L = json.load(open(f"{OUT}/TCS_list.json")); old = [x for x in L if x["format"] == "Old" and x["consolidated"] == "Consolidated"][:3]
for k, x in enumerate(old):
    for name, prm in [("data", dict(index="equities", params=x["params"], seq_id=x["seqNumber"], industry=x.get("industry") or "-",
                                   frOldNewFlag=x.get("oldNewFlag") or "O", ind=x.get("reInd") or "N", format=x["format"]))]:
        try:
            r = S.get("https://www.nseindia.com/api/corporates-financial-results-data", params=prm, timeout=30)
            rep[f"old_{k}_{name}"] = dict(status=r.status_code, n=len(r.content), period=x["toDate"], bcast=x["broadCastDate"])
            open(f"{OUT}/TCS_old_{k}.json", "w").write(r.text[:200000])
        except Exception as e:
            rep[f"old_{k}"] = dict(error=str(e)[:200])
        time.sleep(1.5)
import collections
rep["new_format_from"] = min((x["toDate"] for x in L if x["format"] == "New"), key=lambda d: d[-4:] + d[3:6])
for sym in ():
    for name, url, params in [
        ("list", "https://www.nseindia.com/api/corporates-financial-results", dict(index="equities", symbol=sym, period="Quarterly")),
        ("cmp", "https://www.nseindia.com/api/results-comparision", dict(symbol=sym)),
    ]:
        try:
            r = S.get(url, params=params, timeout=30); rep[f"{sym}_{name}"] = dict(status=r.status_code, n=len(r.content))
            open(f"{OUT}/{sym}_{name}.json", "w").write(r.text[:400000])
            if name == "list" and r.status_code == 200:
                L = r.json(); rep[f"{sym}_list"]["rows"] = len(L)
                if L:
                    rep[f"{sym}_list"]["keys"] = list(L[0].keys()); rep[f"{sym}_list"]["first"] = L[0]; rep[f"{sym}_list"]["last"] = L[-1]
                    xb = [x for x in L if str(x.get("xbrl", "")).startswith("http")]
                    rep[f"{sym}_list"]["with_xbrl"] = len(xb)
                    if xb and sym == "TCS":
                        for k, x in enumerate([xb[0], xb[len(xb) // 2], xb[-1]]):
                            rx = S.get(x["xbrl"], timeout=60); open(f"{OUT}/TCS_xbrl_{k}.xml", "w").write(rx.text[:600000])
                            rep[f"TCS_xbrl_{k}"] = dict(status=rx.status_code, n=len(rx.content), url=x["xbrl"], period=x.get("toDate"))
        except Exception as e:
            rep[f"{sym}_{name}"] = dict(error=str(e)[:200])
        time.sleep(1.5)
json.dump(rep, open(f"{OUT}/report.json", "w"), indent=1, default=str); print(json.dumps(rep, indent=1, default=str)[:6000])
