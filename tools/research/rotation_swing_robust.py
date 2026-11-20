"""robustness of the industry 21 EMA swing (C0) and C / D: next-day execution, double cost, 3 / 8 slots (20 Nov 2026)"""
import os
import runpy
for env in (dict(DELAY="1"), dict(DELAY="1", COST="0.004"), dict(DELAY="1", SLOTS="3"), dict(DELAY="1", SLOTS="8"), dict(DELAY="1", COST="0.004", SLOTS="3")):
    os.environ.update(dict(COST="0.002", SLOTS="5", DELAY="0", ONLY="C")); os.environ.update(env)
    runpy.run_path("tools/research/rotation_swing.py", run_name="__main__")
