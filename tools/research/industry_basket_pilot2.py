"""pilot of industry_basket_intraday.py on a few industries"""
import os, runpy
os.environ["LIMIT"] = "40"
runpy.run_path("tools/research/industry_basket_intraday.py", run_name="__main__")
