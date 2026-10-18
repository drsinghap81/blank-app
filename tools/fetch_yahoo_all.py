import os, yfinance as yf, pandas as pd
os.makedirs("yahoo", exist_ok=True)
syms = "RELIANCE HDFCBANK ICICIBANK BHARTIARTL TCS SBIN BAJFINANCE LT INFY KOTAKBANK HINDUNILVR SUNPHARMA ADANIPORTS AXISBANK TITAN HCLTECH ADANIENT M&M MARUTI ITC ULTRACEMCO ETERNAL NTPC JSWSTEEL BAJAJ-AUTO APOLLOHOSP ASIANPAINT BAJAJFINSV BEL CIPLA COALINDIA DRREDDY EICHERMOT GRASIM HDFCLIFE HINDALCO INDIGO JIOFIN MAXHEALTH NESTLEIND ONGC POWERGRID SBILIFE SHRIRAMFIN TATACONSUM TMPV TATASTEEL TECHM TRENT WIPRO RELCAPITAL RELINFRA MANAPPURAM TATAMOTORS".split()
for s in syms:
    try:
        d = yf.download(s + ".NS", start="2006-01-01", auto_adjust=False, progress=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        if len(d): d[["Close"]].round(4).to_csv(f"yahoo/{s.replace('&','_')}.csv"); print(s, len(d))
        else: print(s, "empty")
    except Exception as e: print(s, "fail", e)
