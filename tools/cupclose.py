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
