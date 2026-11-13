"""Point-in-time quarterly results history from NSE (14 Nov 2026), for the Minervini fundamentals test.
For each symbol: NSE's list of quarterly filings (with the broadcast time = when the market knew), then per quarter the
numbers from NSE's results-data endpoint (EPS, sales, net profit); XBRL fallback for filings where that has no numbers.
One statement per quarter: consolidated if the company files it for most quarters, else standalone. Quarters ending 2014+.
Usage: python tools/fetch_nse_results.py SHARD NSHARDS [MAX_MINUTES]   -> data/fundq/shard_<SHARD>.json (resumable)."""
import json, os, re, sys, time
from datetime import datetime
import requests

SHARD, NSH = int(sys.argv[1]), int(sys.argv[2]); MAXMIN = float(sys.argv[3]) if len(sys.argv) > 3 else 320
OUT = f"data/fundq/shard_{SHARD}.json"; T0 = time.time()
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})


def warm():
    for u in ("https://www.nseindia.com/", "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"):
        try:
            S.get(u, timeout=20)
        except Exception:  # noqa: BLE001
            pass


def get(url, params=None, js=True):
    for k in range(4):
        try:
            r = S.get(url, params=params, timeout=40)
            if r.status_code == 200:
                return r.json() if js else r.text
            if r.status_code in (401, 403, 429):
                warm(); time.sleep(5 + 10 * k); continue
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            time.sleep(3 + 5 * k)
    return None


def f(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if x == x else None
    except (TypeError, ValueError):
        return None


EPS_K = ("re_basic_eps_for_cont_dic_opr", "re_bsc_eps_bfr_exi", "re_basic_eps", "re_bsc_eps_aft_exi")
SALES_K = ("re_net_sale", "re_rev_frm_opr", "re_total_inc", "re_gro_inc", "re_int_earned", "re_tot_int_earned")
NP_K = ("re_net_profit", "re_proloss_ord_act", "re_con_pro_loss", "re_pro_loss_aft_tax")


def pick(d, keys):
    for k in keys:
        v = f(d.get(k))
        if v is not None and (v != 0 or k == keys[-1]):
            return v
    return None


def xbrl(url):
    t = get(url, js=False)
    if not t:
        return None
    def tag(names):
        for n in names:
            m = re.search(rf'<in-bse-fin:{n} contextRef="OneD"[^>]*>([^<]+)<', t)
            if m and f(m.group(1)) is not None:
                return f(m.group(1))
        return None
    eps = tag(["BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
               "BasicEarningsPerShareAfterExtraordinaryItems", "BasicEarningsPerShareBeforeExtraordinaryItems"])
    sales = tag(["RevenueFromOperations", "InterestEarned", "Income", "TotalIncome"])
    npf = tag(["ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod"])
    if sales is not None:
        sales /= 1e5                         # XBRL in rupees -> lakhs, the unit of the results-data endpoint
    if npf is not None:
        npf /= 1e5
    return dict(eps=eps, sales=sales, np=npf, src="xbrl")


def dt(s, fmt):
    try:
        return datetime.strptime(s, fmt).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def one(sym):
    L = get("https://www.nseindia.com/api/corporates-financial-results", dict(index="equities", symbol=sym, period="Quarterly"))
    if not L:
        return dict(err="no filings list")
    L = [x for x in L if x.get("cumulative") == "Non-cumulative" and (dt(x.get("toDate", ""), "%d-%b-%Y") or "") >= "2014-01-01"]
    if not L:
        return dict(err="no quarters since 2014")
    cons = sum(x.get("consolidated") == "Consolidated" for x in L); per = {}
    for x in L:
        per.setdefault(x["toDate"], []).append(x)
    use_c = cons >= 0.7 * len(per)
    Q = []
    for end, xs in per.items():
        xs = [x for x in xs if (x.get("consolidated") == "Consolidated") == use_c] or xs
        x = sorted(xs, key=lambda x: x.get("broadCastDate") or "")[0]          # first filing of that quarter
        d = get("https://www.nseindia.com/api/corporates-financial-results-data",
                dict(index="equities", params=x["params"], seq_id=x["seqNumber"], industry=x.get("industry") or "-",
                     frOldNewFlag=x.get("oldNewFlag") or ("N" if x.get("format") == "New" else "O"), ind=x.get("reInd") or "N", format=x.get("format") or "Old"))
        rd = (d or {}).get("resultsData2") or (d or {}).get("resultsData") or {}
        if isinstance(rd, list):
            rd = rd[0] if rd else {}
        r = dict(eps=pick(rd, EPS_K), sales=pick(rd, SALES_K), np=pick(rd, NP_K), src="data")
        if (r["eps"] is None or r["sales"] is None) and str(x.get("xbrl", "")).startswith("http") and not x["xbrl"].endswith("/-"):
            r = xbrl(x["xbrl"]) or r
        bc = x.get("broadCastDate") or x.get("filingDate") or ""
        Q.append(dict(end=dt(end, "%d-%b-%Y"), known=dt(bc[:11], "%d-%b-%Y") or dt(bc[:11], "%d-%b-%y"), cons=(x.get("consolidated") == "Consolidated"),
                      bank=x.get("bank") == "Y", **r))
        time.sleep(0.6)
    Q.sort(key=lambda q: q["end"] or "")
    return dict(q=Q, cons=use_c)


syms = [s for s in open("data/fundq/symbols.txt").read().split() if s]
mine = [s for i, s in enumerate(syms) if i % NSH == SHARD]
R = json.load(open(OUT)) if os.path.exists(OUT) else {}
warm(); n0 = len(R)
for k, s in enumerate(mine):
    if s in R:
        continue
    if (time.time() - T0) / 60 > MAXMIN:
        print("time budget reached"); break
    try:
        R[s] = one(s)
    except Exception as e:  # noqa: BLE001
        R[s] = dict(err=str(e)[:120])
    if k % 25 == 0:
        json.dump(R, open(OUT, "w"), separators=(",", ":")); print(k, len(mine), s, len((R[s] or {}).get("q", [])), flush=True)
json.dump(R, open(OUT, "w"), separators=(",", ":"))
ok = [v for v in R.values() if v.get("q")]
print(f"shard {SHARD}: {len(R)}/{len(mine)} done ({len(R) - n0} this run); {len(ok)} with quarters; "
      f"eps filled {sum(1 for v in ok for q in v['q'] if q.get('eps') is not None)}/{sum(len(v['q']) for v in ok)}")
