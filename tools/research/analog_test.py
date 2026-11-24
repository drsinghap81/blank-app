"""Do price patterns repeat? Analog test on the Indian index (25 Nov 2026, Amritpal: "do patterns repeat with time cycles" -> "yes").
Library: Sensex daily closes 1995-1997 (bse-1991-2000.blogspot.com, fetched at run time, not stored) + Sensex from Yahoo (1997-07 on),
and separately Nifty 50 from Yahoo (2007 on). For every test date t (every 5 sessions from 2010), the last L sessions (L = 60, 120)
are turned into a shape (log price path, demeaned, scaled by its own volatility). The 10 most similar past shapes are found among
windows that ENDED at least H sessions before t (their outcome was already known - no look-ahead), at least 20 sessions apart.
Forecast = average of what those analogs did over the next H sessions (H = 20, 60). Scored against what actually happened:
direction hit rate vs the base rate, correlation forecast/actual, and a rule 'long when the analogs say up, else cash' vs buy & hold
(same test dates, non-overlapping H blocks). Also: today's 10 closest analogs and what followed them. Newest-first windows."""
import html
import re

import numpy as np
import pandas as pd
import requests
import yfinance as yf

U = {"User-Agent": "Mozilla/5.0"}


def old_sensex():
    base = "https://bse-1991-2000.blogspot.com/p/"
    pages = ["bse-sensex-historical-prices-in-year_1204.html", "bse-sensex-historical-prices-in-year_2455.html", "bse-sensex-historical-prices-in-year_7768.html"]
    rows = []
    for p in pages:
        t = requests.get(base + p, headers=U, timeout=30).text
        b = re.search(r"post-body[^>]*>(.*?)<div class=['\"]post-footer", t, re.S); body = b.group(1) if b else t
        txt = html.unescape(re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body)); txt = re.sub(r"<[^>]+>", " ", txt)
        d = None
        for l in (re.sub(r"\s+", " ", x).strip() for x in txt.split("\n")):
            if re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", l):
                d = pd.to_datetime(l, format="%d-%b-%Y"); continue
            if d is not None and re.match(r"^[\d,]+\.?\d*$", l):
                rows.append((d, float(l.replace(",", "")))); d = None
    s = pd.Series(dict(rows)).sort_index(); return s[~s.index.duplicated()]


def yh(t, start):
    d = yf.download(t, start=start, progress=False, auto_adjust=True)["Close"].squeeze().dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None); return d


def shape(lp):
    r = np.diff(lp); sd = r.std() or 1e-9
    z = (lp - lp.mean()) / (sd * np.sqrt(len(lp))); return z


def run(name, s, L, H, K=10, start="2010-01-01"):
    lp = np.log(s.to_numpy(float)); D = s.index; n = len(lp)
    S = np.full((n, L), np.nan)
    for i in range(L - 1, n):
        S[i] = shape(lp[i - L + 1:i + 1])
    fwd = np.full(n, np.nan); fwd[:n - H] = lp[H:] - lp[:n - H]
    tests = [i for i in range(L, n - H) if D[i] >= pd.Timestamp(start)][::5]
    out = []
    for i in tests:
        cand = np.arange(L - 1, i - H)                         # windows whose H-day outcome was known at t
        if len(cand) < 50:
            continue
        dist = np.sqrt(((S[cand] - S[i]) ** 2).sum(axis=1)); order = cand[np.argsort(dist)]
        pick = []
        for j in order:
            if all(abs(j - q) >= 20 for q in pick):
                pick.append(j)
            if len(pick) == K:
                break
        f = np.nanmean(fwd[pick]); out.append((D[i], f, fwd[i], np.mean(fwd[pick] > 0)))
    R = pd.DataFrame(out, columns=["d", "fc", "act", "agree"]).set_index("d")
    end = R.index.max()
    def score(T):
        if len(T) < 20:
            return f"n {len(T)}"
        hit = ((T.fc > 0) == (T.act > 0)).mean(); base = max((T.act > 0).mean(), 1 - (T.act > 0).mean())
        up_when_up = T[T.fc > 0].act.mean(); up_when_dn = T[T.fc <= 0].act.mean()
        strong = T[(T.agree >= 0.8) | (T.agree <= 0.2)]; hs = ((strong.fc > 0) == (strong.act > 0)).mean() if len(strong) else np.nan
        blk = T.iloc[::max(1, H // 5)]; strat = np.exp(np.where(blk.fc > 0, blk.act, 0).sum()) - 1; bh = np.exp(blk.act.sum()) - 1
        return (f"n {len(T):4d} | direction hit {hit * 100:4.1f}% (always-the-majority {base * 100:4.1f}%) | corr {T.fc.corr(T.act):+.2f} | "
                f"next {H}d when analogs say UP {up_when_up * 100:+.2f}% vs DOWN {up_when_dn * 100:+.2f}% | 80%+ agree: hit {hs * 100:.0f}% (n {len(strong)}) | "
                f"long-when-up {strat * 100:+.0f}% vs buy&hold {bh * 100:+.0f}%")
    for lab, T in [("all", R), ("last 3y", R[R.index > end - pd.DateOffset(years=3)]), ("last 5y", R[R.index > end - pd.DateOffset(years=5)]),
                   ("2010-17", R[R.index < "2018-01-01"]), ("2018-26", R[R.index >= "2018-01-01"])]:
        print(f"R| {name} L{L} H{H} {lab:8s} | {score(T)}", flush=True)
    return R


def today(name, s, L, H, K=10):
    lp = np.log(s.to_numpy(float)); D = s.index; n = len(lp); cur = shape(lp[-L:])
    rows = []
    for i in range(L - 1, n - H):
        rows.append((i, np.sqrt(((shape(lp[i - L + 1:i + 1]) - cur) ** 2).sum())))
    rows.sort(key=lambda z: z[1]); pick = []
    for i, d in rows:
        if all(abs(i - q) >= 20 for q, _ in pick):
            pick.append((i, d))
        if len(pick) == K:
            break
    print(f"R| TODAY {name} L{L}: 10 closest past windows and the next {H} sessions:", flush=True)
    for i, d in pick:
        print(f"R|   ended {D[i].date()} (dist {d:.2f}) -> next {H}d {(np.exp(lp[i + H] - lp[i]) - 1) * 100:+.1f}%", flush=True)
    f = [np.exp(lp[i + H] - lp[i]) - 1 for i, _ in pick]
    print(f"R|   average {np.mean(f) * 100:+.1f}%, {sum(x > 0 for x in f)} of 10 up", flush=True)


def main():
    try:
        o = old_sensex(); print("R| old sensex", o.index.min().date(), o.index.max().date(), len(o), flush=True)
    except Exception as e:  # noqa: BLE001
        o = pd.Series(dtype=float); print("R| old sensex failed", e, flush=True)
    sx = yh("^BSESN", "1997-07-01"); nf = yh("^NSEI", "2007-09-01")
    sens = pd.concat([o[o.index < sx.index.min()], sx]).sort_index()
    print("R| sensex library", sens.index.min().date(), "->", sens.index.max().date(), len(sens), "| nifty", nf.index.min().date(), len(nf), flush=True)
    for L in (60, 120):
        for H in (20, 60):
            run("SENSEX", sens, L, H); run("NIFTY ", nf, L, H)
    for L in (60, 120):
        today("SENSEX", sens, L, 60); today("NIFTY", nf, L, 60)


if __name__ == "__main__":
    main()
