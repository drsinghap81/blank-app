"""Speculator positioning in gold, silver, copper, crude oil and natural gas (22 Nov 2026, Amritpal: "worth adding ... speculative
long short ... in chips").

CFTC Commitments of Traders, disaggregated futures-only (publicreporting.cftc.gov, weekly: Tuesday positions, out Friday).
Managed money = hedge funds / CTAs. long share = long / (long + short); net = (long - short) / open interest; rank = where the net
sits in the past 3 years (0 = most bearish). States: very bearish (bottom 10%), crowded long (top 10%), covering (net up >= 5% of OI
in 3 weeks from the bottom 10%). Tested 2006-26 on gold / silver (tools/research/metals_cot.py): none of these states beat an
ordinary week over the next 4-26 weeks - shown as context only. Writes data/scan/cot.json."""
import json
from datetime import datetime, timezone

import pandas as pd
import requests

API = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
M = {"GC=F": ("088691", "Gold"), "SI=F": ("084691", "Silver"), "HG=F": ("085692", "Copper"), "CL=F": ("067651", "Crude oil (WTI)"),
     "NG=F": ("023651", "Natural gas")}


def main():
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), method=__doc__, rows={})
    for key, (code, nm) in M.items():
        try:
            r = requests.get(API, params={"cftc_contract_market_code": code, "$limit": 400, "$order": "report_date_as_yyyy_mm_dd DESC"}, timeout=60)
            d = pd.DataFrame(r.json()); d["date"] = pd.to_datetime(d.report_date_as_yyyy_mm_dd); d = d.set_index("date").sort_index()
            L, S, OI = (pd.to_numeric(d[k], errors="coerce") for k in ("m_money_positions_long_all", "m_money_positions_short_all", "open_interest_all"))
            net = (L - S) / OI * 100; ls = L / (L + S) * 100
            w = net.tail(157); rank = float((w.iloc[:-1] < w.iloc[-1]).mean())
            chg3 = float(net.iloc[-1] - net.iloc[-4]); low_before = float(net.tail(157).iloc[:-3].rank(pct=True).iloc[-1]) if len(net) > 160 else None
            prev_rank = float((w.iloc[:-4] < net.iloc[-4]).mean())
            state = "covering" if prev_rank <= 0.10 and chg3 >= 5 else "very bearish" if rank <= 0.10 else "crowded long" if rank >= 0.90 else "neutral"
            out["rows"][key] = dict(name=nm, date=str(net.index[-1].date()), long_share=round(float(ls.iloc[-1]), 1), net_pct=round(float(net.iloc[-1]), 1),
                                    rank3y=round(rank * 100), chg3=round(chg3, 1), state=state,
                                    hist=[[str(t.date()), round(float(v), 1)] for t, v in net.tail(26).items()])
            print(key, out["rows"][key]["date"], state, out["rows"][key]["long_share"], out["rows"][key]["net_pct"], out["rows"][key]["rank3y"])
        except Exception as e:  # noqa: BLE001
            print("cot failed", key, e)
    if out["rows"]:
        json.dump(out, open("data/scan/cot.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
