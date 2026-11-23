"""Bank Nifty today's low / close (Yahoo) - quick check against the Top Bottom stop."""
import yfinance as yf
for t in ("^NSEBANK",):
    x = yf.download(t, period="3d", interval="5m", progress=False, auto_adjust=True)
    x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
    x.index = x.index.tz_convert("Asia/Kolkata"); z = x[x.index.date == x.index[-1].date()]
    i = z.Low.idxmin()
    print(f"R| {t} {z.index[-1].date()} open {z.Open.iloc[0]:.0f} high {z.High.max():.0f} low {z.Low.min():.0f} at {i:%H:%M} close {z.Close.iloc[-1]:.0f}")
