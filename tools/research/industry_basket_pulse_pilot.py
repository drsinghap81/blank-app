"""pilot of industry_basket_pulse.py on 10 industries, hourly only"""
import os, runpy
os.environ["LIMIT"] = "40"
runpy.run_path("tools/research/industry_basket_pulse.py", run_name="__main__")
