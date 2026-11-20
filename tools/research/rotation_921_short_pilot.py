"""pilot of rotation_921_short.py (400 stocks, 1 seed)"""
import os, runpy
os.environ["PILOT"] = "1"
runpy.run_path("tools/research/rotation_921_short.py", run_name="__main__")
