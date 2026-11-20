"""pilot of rotation_bt.py on 10 industries"""
import os, runpy
os.environ["LIMIT"] = "40"
runpy.run_path("tools/research/rotation_bt.py", run_name="__main__")
