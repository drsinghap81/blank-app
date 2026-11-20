"""NSE bhavcopy as the source of truth for recent Indian prices (20 Nov 2026, Amritpal: "Always use bhavcopy").

Yahoo's daily history for NSE stocks can lag or miss sessions (19 Nov 2026 was missing for ~70% of NSE stocks). After
`install()`, every yfinance download of '.NS' tickers (daily bars) has its last N sessions checked against NSE's own CM
bhavcopy (UDiFF, nsearchives.nseindia.com):
  - a session Yahoo is missing -> filled from the bhavcopy (open, high, low, close, volume)
  - a session whose close differs from the bhavcopy by > 0.1% -> replaced by the bhavcopy values
  - unless the two differ by more than 20% (a split / bonus Yahoo has adjusted for) -> Yahoo is kept
'Adj Close' (when present) is scaled by the previous session's adjustment factor. Indices (^NSEI ...) are not in the CM
bhavcopy and are left alone. Bhavcopies are cached per run in /tmp. Usage: `import nse_bhav; nse_bhav.install()`."""
import io
import os
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

N_DAYS = int(os.environ.get("BHAV_DAYS", "10"))
CACHE = "/tmp/nse_bhav"
_mem = {}
STATS = dict(filled=0, replaced=0, skipped_ca=0, sessions=0)


def bhav(d):
    """CM bhavcopy for date d as a DataFrame indexed by symbol (EQ / BE / BZ / SM / ST series), or None (holiday / not out yet)."""
    ymd = d.strftime("%Y%m%d")
    if ymd in _mem:
        return _mem[ymd]
    os.makedirs(CACHE, exist_ok=True); p = os.path.join(CACHE, ymd + ".pkl")
    if os.path.exists(p):
        _mem[ymd] = pd.read_pickle(p); return _mem[ymd]
    out = None
    import requests
    for host in ("nsearchives.nseindia.com", "archives.nseindia.com"):
        try:
            r = requests.get(f"https://{host}/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip", timeout=40,
                             headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"})
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); b = pd.read_csv(z.open(z.namelist()[0]))
                b = b[b["SctySrs"].isin(["EQ", "BE", "BZ", "SM", "ST"])].drop_duplicates("TckrSymb").set_index("TckrSymb")
                out = pd.DataFrame({"Open": b["OpnPric"], "High": b["HghPric"], "Low": b["LwPric"], "Close": b["ClsPric"],
                                    "Volume": b["TtlTradgVol"]}).astype(float)
                break
            if r.status_code == 404:
                break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    _mem[ymd] = out
    if out is not None:
        out.to_pickle(p)
    return out


def sessions(n=N_DAYS):
    """the last n weekdays up to yesterday (IST) plus today after 18:30 IST, with a bhavcopy -> {Timestamp: DataFrame}"""
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    d = now.date() if (now.hour, now.minute) >= (18, 30) else now.date() - timedelta(days=1)
    out = {}; k = 0
    while len(out) < n and k < n * 2 + 6:
        if d.weekday() < 5:
            b = bhav(d)
            if b is not None:
                out[pd.Timestamp(d)] = b
        d -= timedelta(days=1); k += 1
    STATS["sessions"] = len(out)
    return out


def _patch_one(x, sym, S):
    """x: DataFrame for one ticker with Open/High/Low/Close/(Adj Close)/Volume columns, date index -> patched copy"""
    tz = getattr(x.index, "tz", None)
    recent = {pd.Timestamp(i).date(): i for i in x.index[-40:]}
    for D, b in S.items():
        if sym not in b.index:
            continue
        row = b.loc[sym]; bc = float(row["Close"])
        if not np.isfinite(bc) or bc <= 0:
            continue
        key = D.tz_localize(tz) if tz is not None else D
        if D.date() in recent:
            key = recent[D.date()]
            yc = x.at[key, "Close"] if "Close" in x.columns else np.nan
            if pd.notna(yc) and yc > 0:
                ratio = bc / float(yc)
                if abs(ratio - 1) <= 0.001:
                    continue
                if not (0.8 < ratio < 1.25):
                    STATS["skipped_ca"] += 1; continue
                STATS["replaced"] += 1
            else:
                STATS["filled"] += 1
        else:
            STATS["filled"] += 1
        prev = x[x.index < key]
        adjf = 1.0
        if "Adj Close" in x.columns and len(prev) and pd.notna(prev["Close"].iloc[-1]) and prev["Close"].iloc[-1]:
            adjf = float(prev["Adj Close"].iloc[-1] / prev["Close"].iloc[-1])
        for c in ("Open", "High", "Low", "Close", "Volume"):
            if c in x.columns:
                x.loc[key, c] = float(row[c])
        if "Adj Close" in x.columns:
            x.loc[key, "Adj Close"] = bc * adjf
    return x.sort_index()


def patch(df, tickers):
    """patch a yfinance download result (any shape) for its .NS tickers"""
    if df is None or not len(getattr(df, "index", [])):
        return df
    tks = [tickers] if isinstance(tickers, str) else list(tickers or [])
    ns = [t for t in tks if isinstance(t, str) and t.upper().endswith(".NS")]
    if not ns:
        return df
    S = sessions()
    if not S:
        return df
    fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    if isinstance(df.columns, pd.MultiIndex):
        lv = 0 if set(df.columns.get_level_values(0)) & fields else 1      # level holding the field names
        parts = {}
        for t in df.columns.get_level_values(1 - lv).unique():
            sub = df.xs(t, axis=1, level=1 - lv).copy()
            if isinstance(t, str) and t.upper().endswith(".NS"):
                sub = _patch_one(sub, t[:-3].upper(), S)
            parts[t] = sub
        idx = sorted(set().union(*[set(p.index) for p in parts.values()]))
        cols = []; data = {}
        for t, p in parts.items():
            p = p.reindex(idx)
            for f in p.columns:
                k = (f, t) if lv == 0 else (t, f)
                data[k] = p[f]; cols.append(k)
        out = pd.DataFrame(data, index=pd.Index(idx, name=df.index.name))
        out.columns = pd.MultiIndex.from_tuples(cols, names=df.columns.names)
        return out
    if len(ns) == 1 and len(tks) == 1:
        return _patch_one(df.copy(), ns[0][:-3].upper(), S)
    return df


def install():
    """wrap yfinance.download (daily interval only) so .NS results are bhavcopy-checked"""
    import yfinance as yf
    if getattr(yf.download, "_bhav", False):
        return
    orig = yf.download

    def dl(tickers=None, *a, **k):
        d = orig(tickers, *a, **k)
        if str(k.get("interval", "1d")) != "1d":
            return d
        try:
            return patch(d, tickers.split() if isinstance(tickers, str) and " " in tickers else tickers)
        except Exception as e:  # noqa: BLE001
            print("nse_bhav patch skipped:", str(e)[:120], flush=True)
            return d
    dl._bhav = True
    yf.download = dl
