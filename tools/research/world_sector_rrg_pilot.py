"""pilot: world_sector_rrg.py dry run (no files written)"""
import sys, runpy
sys.argv = ["world_sector_rrg.py", "US", "ASX", "--dry"]
runpy.run_path("tools/world_sector_rrg.py", run_name="__main__")
