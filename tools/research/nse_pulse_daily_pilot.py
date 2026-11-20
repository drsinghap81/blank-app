"""pilot of nse_pulse_daily.py on 10 industries (writes the file too; the full run overwrites it)"""
import os, runpy
os.environ["LIMIT"] = "40"
runpy.run_path("tools/research/nse_pulse_daily.py", run_name="__main__")
