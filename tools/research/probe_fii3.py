import io, requests, pandas as pd
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0"})
for f in ["FIIInvestSector_Nov152026.html", "FIIInvestSector_Mar152016.html"]:
    h = s.get("https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/" + f, timeout=40).text
    T = pd.read_html(io.StringIO(h)); big = max(T, key=lambda x: x.shape[0] * x.shape[1])
    print("R|", f, big.shape)
    for i in range(min(6, len(big))):
        print("R| row", i, [str(v)[:28] for v in big.iloc[i].tolist()[:40]])
    print("R| sectors col1", [str(v)[:40] for v in big.iloc[:, 1].tolist()])
    print("R| row 8 all", [str(v)[:14] for v in big.iloc[8].tolist()])
