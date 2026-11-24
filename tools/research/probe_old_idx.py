"""probe sources for 1990s Indian index history"""
import io
import requests
import pandas as pd
U = {"User-Agent": "Mozilla/5.0"}
for s in ("^snx", "^bse", "^sensex", "^nsei", "^nifty", "^cnx"):
    try:
        r = requests.get(f"https://stooq.com/q/d/l/?s={s}&i=w", headers=U, timeout=30)
        t = r.text[:200].replace("\n", " ")
        print("R| stooq", s, r.status_code, t, flush=True)
        if r.ok and "Date" in r.text[:50]:
            d = pd.read_csv(io.StringIO(r.text)); d["Date"] = pd.to_datetime(d["Date"]); print("R| stooq", s, "from", d.Date.min(), "rows", len(d), flush=True)
            x = d[(d.Date >= "1993-06-01") & (d.Date <= "1997-12-31")]
            for _, z in x.iterrows():
                print(f"R| OLD {s} {z.Date.date()} {z.Close}", flush=True)
            break
    except Exception as e:  # noqa: BLE001
        print("R| stooq fail", s, e, flush=True)
