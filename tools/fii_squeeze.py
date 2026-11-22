"""Nightly FII positioning + 'squeeze setup' context for the traffic light (21 Nov 2026, Amritpal: "Yes" to a context line).

FII long % = FII index-futures long / (long + short), NSE participant-wise OI (published each evening). Setup (tested 2016-26,
tools/research/squeeze_market.py): Nifty >= 5% below its 60-day high while FII long % <= 20 -> Nifty higher 60 sessions later in 83% of
20 cases (+5.5% vs +3.0% on any day; Covid 2020 the exception). Covering = FII long % up >= 5 points over 3 sessions from <= 20 with the
setup seen in the last 20 sessions (next 1-2 weeks about flat; +4.8% over 60 sessions, 86% up). Context only - not a trade signal.
Writes data/scan/fii.json: last 60 sessions of FII long %, Nifty distance from its 60-day high, and today's state."""
import io
import json
import time
from datetime import date, timedelta

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}


def one(d):
    for host in ("nsearchives.nseindia.com", "archives.nseindia.com"):
        try:
            r = requests.get(f"https://{host}/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv", headers=UA, timeout=20)
            if r.status_code == 200 and b"FII" in r.content:
                t = pd.read_csv(io.BytesIO(r.content), skiprows=1); t.columns = [str(c).strip() for c in t.columns]
                t = t.set_index(t.columns[0]); t.index = [str(i).strip() for i in t.index]
                a, b = float(t.loc["FII"]["Future Index Long"]), float(t.loc["FII"]["Future Index Short"])
                return round(a / (a + b) * 100, 1)
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def cash():
    """22 Nov 2026 (Amritpal: "worth adding FII buying ... in chips"): FII / DII cash-market net (Rs cr). History = NSDL FPI equity
    net (tools/research/fii_test.daily, data/research/fii_daily.csv, to 20 Nov 2026), then NSE's provisional FII / DII figure each
    evening (nseindia.com/api/fiidiiTradeReact). State from the 20-day FII sum ranked against the past year: heavy selling (bottom
    20%) / heavy buying (top 20%). Tested 2015-26 (claude/fii-flows-govt-focus-news-clues.md): after heavy selling Nifty did BETTER
    (+4.0% next 60 sessions vs +2.6% any day); as a buy filter FII buying cut every system's returns - context only."""
    try:
        prev = json.load(open("data/scan/fii.json")).get("cash") or {}
    except Exception:  # noqa: BLE001
        prev = {}
    H = {d: v for d, v in (prev.get("hist") or [])}; DII = {d: v for d, v in (prev.get("dii") or [])}
    if len(H) < 250:
        try:
            s0 = pd.read_csv("data/research/fii_daily.csv", index_col=0).iloc[:, 0]; s0.index = pd.to_datetime(s0.index); s0 = s0.sort_index()
            s0 = s0.shift(-1).dropna()           # an NSDL reporting date covers the previous session's trades
            for d, v in s0.items():
                H.setdefault(str(pd.Timestamp(d).date()), float(v))
        except Exception as e:  # noqa: BLE001
            print("no NSDL history", e)
    S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
    try:
        S.get("https://www.nseindia.com", timeout=20)
        for r in S.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=30).json():
            d = str(pd.Timestamp(r["date"]).date()); v = float(r["netValue"])
            if r["category"].startswith("FII"):
                H[d] = v
            elif r["category"] == "DII":
                DII[d] = v
    except Exception as e:  # noqa: BLE001
        print("NSE FII/DII failed", e)
    s = pd.Series(H).sort_index(); s.index = pd.to_datetime(s.index); s = s[~s.index.duplicated()].tail(400)
    f5, f20 = s.rolling(5).sum(), s.rolling(20).sum()
    rank = float((f20.iloc[-251:-1] < f20.iloc[-1]).mean()) if len(f20.dropna()) > 120 else None
    state = None if rank is None else "heavy selling" if rank < 0.2 else "heavy buying" if rank > 0.8 else "normal"
    dk = sorted(DII)[-20:]
    return dict(asof=str(s.index[-1].date()), day=round(float(s.iloc[-1]), 1), f5=round(float(f5.iloc[-1]), 0), f20=round(float(f20.iloc[-1]), 0),
                rank=None if rank is None else round(rank * 100), state=state, dii_day=DII.get(dk[-1]) if dk else None,
                dii20=round(sum(DII[k] for k in dk), 0) if len(dk) >= 15 else None,
                hist=[[str(t.date()), round(float(v), 1)] for t, v in s.tail(300).items()], dii=[[k, DII[k]] for k in dk])


def main():
    L = {}
    d = date.today() - timedelta(days=130)
    while d <= date.today():
        if d.weekday() < 5:
            v = one(d)
            if v is not None:
                L[str(d)] = v
            time.sleep(0.2)
        d += timedelta(1)
    ix = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
    n = ix[ix.INDEX == "NIFTY 50"].set_index("Date").Close.sort_index()
    dd = (n / n.rolling(60).max() - 1) * 100
    S = pd.Series(L); S.index = pd.to_datetime(S.index)
    D = pd.DataFrame({"fii": S, "dd": dd.reindex(S.index, method="ffill")}).dropna().tail(80)
    setup = (D.dd <= -5) & (D.fii <= 20)
    recent = setup.astype(float).rolling(20, min_periods=1).max().astype(bool)
    cover = recent & (D.fii - D.fii.shift(3) >= 5) & (D.fii.shift(3) <= 20)
    state = "setup" if bool(setup.iloc[-1]) else "covering" if bool(cover.tail(10).any()) else None
    out = dict(asof=str(D.index[-1].date()), fii_long=float(D.fii.iloc[-1]), nifty_dd=round(float(D.dd.iloc[-1]), 1), state=state,
               cover_on=[str(t.date()) for t in D.index[cover]][-5:], setup_days=int(setup.tail(20).sum()),
               hist=[[str(t.date()), float(r.fii), round(float(r.dd), 1)] for t, r in D.tail(60).iterrows()])
    try:
        out["cash"] = cash()
    except Exception as e:  # noqa: BLE001
        print("cash flows failed", e)
    json.dump(out, open("data/scan/fii.json", "w"), separators=(",", ":"))
    print("fii", out["asof"], out["fii_long"], out["nifty_dd"], state, out["cover_on"])


if __name__ == "__main__":
    main()
