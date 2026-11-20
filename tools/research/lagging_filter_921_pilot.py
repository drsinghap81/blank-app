"""pilot of lagging_filter_921.py (400 stocks, 1 seed)"""
import os, runpy
os.environ["PILOT"] = "1"
runpy.run_path("tools/research/lagging_filter_921.py", run_name="__main__")
