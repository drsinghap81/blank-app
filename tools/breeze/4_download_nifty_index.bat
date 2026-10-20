@echo off
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" 2>nul
python fetch_intraday.py --symbol NIFTY --index-history --from 2016-01-01
pause
