# Intraday option history from ICICI Direct Breeze

1. Create an app: log in at https://api.icicidirect.com/apiuser/home → "Register an App".
   Redirect URL: `http://127.0.0.1`. Note the **API Key** and **Secret Key**.
2. In this folder: copy `.env.example` to `.env`, paste both keys. (`.env` is git-ignored.)
3. `pip install -r requirements.txt`
4. Test: `python fetch_intraday.py --probe` — it prints a login link; log in, copy the
   `apisession=...` value from the address bar, paste it. The session token is valid for the day.
5. Download: `python fetch_intraday.py --symbol NIFTY --from 2024-01-01`
   It stops near Breeze's ~5000 calls/day and resumes next run. Output goes to `out/`.
6. Zip the `out` folder and upload it to Claude.
