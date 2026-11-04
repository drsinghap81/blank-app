"""Drop today's still-forming daily bar when a scan runs during NSE market hours, so signals use completed closes only."""
from datetime import datetime, timedelta, timezone

import pandas as pd


CLOSE_AT = {"NSE": ("Asia/Kolkata", (15, 45)), "US": ("America/New_York", (16, 15)), "ASX": ("Australia/Sydney", (16, 20))}


def drop_partial(df, market="NSE"):
    """Drop the last bar if it is today's and that market has not closed yet (local exchange time)."""
    from zoneinfo import ZoneInfo
    tz, hm = CLOSE_AT.get(market, CLOSE_AT["NSE"])
    now = datetime.now(timezone.utc).astimezone(ZoneInfo(tz))
    if now.weekday() < 5 and (now.hour, now.minute) < hm and len(df) and pd.Timestamp(df.index[-1]).date() == now.date():
        return df.iloc[:-1]
    return df
