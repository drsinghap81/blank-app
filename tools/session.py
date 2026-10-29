"""Drop today's still-forming daily bar when a scan runs during NSE market hours, so signals use completed closes only."""
from datetime import datetime, timedelta, timezone

import pandas as pd


def drop_partial(df):
    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if now.weekday() < 5 and (now.hour, now.minute) < (15, 45) and len(df) and pd.Timestamp(df.index[-1]).date() == now.date():
        return df.iloc[:-1]
    return df
