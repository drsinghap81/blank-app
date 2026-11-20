"""pilot of industry_5m_signal.py on 10 industries"""
import os, runpy
os.environ["LIMIT"] = "40"
runpy.run_path("tools/research/industry_5m_signal.py", run_name="__main__")
