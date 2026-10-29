"""Repair splits / bonuses / demergers that Yahoo has not adjusted: an overnight gap where today's open is below 62%
or above 160% of yesterday's close is treated as a corporate action (NSE daily price bands make real moves that large
very rare), and all earlier prices are scaled by open/previous-close so the series is continuous."""
import numpy as np
import pandas as pd


def fix_gaps(o, h, l, c, v=None, lo=0.62, hi=1.6):
    o, h, l, c = (s.astype(float).copy() for s in (o, h, l, c))
    v = None if v is None else v.astype(float).copy()
    pc = c.shift(1)
    r = (o / pc).to_numpy()
    idx = np.where((r < lo) | (r > hi))[0]
    for i in idx[::-1]:
        f = r[i]
        if not np.isfinite(f) or f <= 0:
            continue
        before = c.index[:i]
        for s in (o, h, l, c):
            s.loc[before] = s.loc[before] * f
        if v is not None:
            v.loc[before] = v.loc[before] / f
    return (o, h, l, c, v) if v is not None else (o, h, l, c)
