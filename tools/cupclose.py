"""Weekly and daily cup-close check shared by index_mclose.py and asset_scan.py (15 Nov 2026), same rules as ath_scan.py:
rim = highest high of the last 104 weeks / 250 days (signal bar excluded), at least 26 weeks / 20 days old, cup depth (lowest close
since the rim) at least 20% / 15%; kept when the room to the next older peak above the close is at least the cup depth, or none
is above (all-time high). Watch lists only."""
import numpy as np, pandas as pd

WK_MIN, WK_DEP, DY_MIN, DY_DEP, WK_K, DY_K = 26, -0.20, 20, -0.15, 104, 250


def cupclose(hh, cc, K, B, D):
    n_ = len(hh)
    if n_ < B + 3:
        return None
    lo = max(0, n_ - 1 - K); win = hh[lo:n_ - 1]
    if not np.isfinite(win).any():
        return None
    a_ = lo + int(np.nanargmax(win)); rim = float(hh[a_]); age = n_ - 1 - a_
    if not (cc[-1] > rim and age >= B):
        return None
    seg = cc[a_ + 1:n_ - 1]; dep = float(np.nanmin(seg) / rim - 1) if len(seg) else 0.0
    if dep > D:
        return None
    res = None; c_ = float(cc[-1]); above = np.flatnonzero(hh[:a_] > c_)
    if len(above):
        j = int(above[-1]); lo_, hi_ = max(0, j - B), min(a_, j + B + 1)
        res = float(np.nanmax(hh[lo_:hi_]))
    room = (res / cc[-1] - 1) if res else None
    if room is not None and room < -dep:
        return None
    return a_, rim, age, dep, res, room


def _row(kind, period, c, h, rim, rim_date, age, dep, res, room, long_cup):
    return dict(kind=kind, period=period, close_p=c, high_p=h, old_ath=rim, ath_date=rim_date, base=int(age), depth=round(dep, 4),
                above_pct=round((c / rim - 1) * 100, 2), resistance=res, room_pct=None if room is None else round(room * 100, 2),
                ath=res is None, long_cup=bool(long_cup))


IX_WK_DEP, IX_DY_DEP = -0.10, -0.08   # indices rarely fall 20%: shallower cups for index lists (watch only, not tested)


def wd_closes(x, wk_dep=WK_DEP, dy_dep=DY_DEP):
    """x: daily DataFrame with High and Close (DatetimeIndex). Returns (week_row or None, day_row or None)."""
    x = x[["High", "Close"]].copy(); x["High"] = x.High.where(x.High.notna(), x.Close); x = x.dropna()
    last = x.index[-1].normalize()
    W = pd.DataFrame({"h": x.High.resample("W-FRI").max(), "c": x.Close.resample("W-FRI").last()}).dropna()
    if len(W) and W.index[-1].normalize() > last:          # week not finished yet
        W = W.iloc[:-1]
    wk = dy = None
    r = cupclose(W.h.to_numpy(float), W.c.to_numpy(float), WK_K, WK_MIN, wk_dep) if len(W) else None
    if r:
        a_, rim, age, dep, res, room = r
        wk = _row("W", str(W.index[-1].date()), float(W.c.iloc[-1]), float(W.h.iloc[-1]), rim, str(W.index[a_].date()), age, dep, res, room, age >= 52 and dep <= -0.30)
    r = cupclose(x.High.to_numpy(float), x.Close.to_numpy(float), DY_K, DY_MIN, dy_dep)
    if r:
        a_, rim, age, dep, res, room = r
        dy = _row("D", str(x.index[-1].date()), float(x.Close.iloc[-1]), float(x.High.iloc[-1]), rim, str(x.index[a_].date()), age, dep, res, room, age >= 120 and dep <= -0.30)
    return wk, dy


def cupclose_short(ll, cc, K, B, D):
    """Reverse cup (15 Nov 2026): the close is BELOW the lowest low of the last K bars (signal bar excluded), that low is at least
    B bars old, and price rallied at least D (e.g. 0.20) above it in between. Room: the next older trough below the close is at
    least the rally height away (None = all-time low). Returns (a, rim, age, rally, support, room) or None. Watch only: shorting
    these on F&O stocks lost money in the 2016-26 test."""
    n_ = len(ll)
    if n_ < B + 3:
        return None
    lo = max(0, n_ - 1 - K); win = ll[lo:n_ - 1]
    if not np.isfinite(win).any():
        return None
    a_ = lo + int(np.nanargmin(win)); rim = float(ll[a_]); age = n_ - 1 - a_
    if not (cc[-1] < rim and age >= B):
        return None
    seg = cc[a_ + 1:n_ - 1]; rally = float(np.nanmax(seg) / rim - 1) if len(seg) else 0.0
    if rally < D:
        return None
    sup = None; c_ = float(cc[-1]); below = np.flatnonzero(ll[:a_] < c_)
    if len(below):
        j = int(below[-1]); lo_, hi_ = max(0, j - B), min(a_, j + B + 1)
        sup = float(np.nanmin(ll[lo_:hi_]))
    room = (1 - sup / c_) if sup else None
    return a_, rim, age, rally, sup, room   # room is shown, not required (support breaks rarely have room to an older low)


SH_WK_K, SH_WK_MIN, SH_WK_UP, SH_DY_K, SH_DY_MIN, SH_DY_UP = 52, 8, 0.10, 120, 10, 0.08   # support break (15 Nov 2026, Amritpal's gold chart)


def wd_short(x, wk_dep=SH_WK_UP, dy_dep=SH_DY_UP):
    """Support break (reverse cup): the week / day CLOSES below the lowest low of the last 52 weeks / 120 days (at least 8 weeks /
    10 days old) after a rally of 10% / 8%+ off it, under a falling 30-week SMA. Watch only.
    Weekly / daily reverse-cup closes for a daily OHLC frame (Low, Close). Only when the last completed week is below a falling
    30-week SMA. Returns (week_row or None, day_row or None)."""
    x = (x[["Low", "Close"]] if "Low" in x else x[["Close"]].assign(Low=x.Close)).copy(); x["Low"] = x.Low.where(x.Low.notna(), x.Close); x = x.dropna()
    last = x.index[-1].normalize()
    W = pd.DataFrame({"l": x.Low.resample("W-FRI").min(), "c": x.Close.resample("W-FRI").last()}).dropna()
    if len(W) and W.index[-1].normalize() > last:
        W = W.iloc[:-1]
    if len(W) < 40:
        return None, None
    sma = W.c.rolling(30).mean()
    if not (W.c.iloc[-1] < sma.iloc[-1] < sma.iloc[-5]):
        return None, None
    out = []
    for kind, L, C, T, K, B, D, lc in (("WS", W.l, W.c, W.index, SH_WK_K, SH_WK_MIN, wk_dep, 26), ("DS", x.Low, x.Close, x.index, SH_DY_K, SH_DY_MIN, dy_dep, 60)):
        r = cupclose_short(L.to_numpy(float), C.to_numpy(float), K, B, D)
        if not r:
            out.append(None); continue
        a_, rim, age, rally, sup, room = r
        out.append(dict(kind=kind, period=str(T[-1].date()), close_p=float(C.iloc[-1]), low_p=float(L.iloc[-1]), old_low=rim, low_date=str(T[a_].date()),
                        base=int(age), rally=round(rally, 4), below_pct=round((1 - float(C.iloc[-1]) / rim) * 100, 2), support=sup,
                        room_pct=None if room is None else round(room * 100, 2), atl=sup is None, long_cup=bool(age >= lc and rally >= 0.20)))
    return out[0], out[1]
