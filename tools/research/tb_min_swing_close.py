"""tb_min_swing.py re-run with HONEST entry-day stops (28 Nov 2026): exit at the close when the close is beyond the 1% level
(the engine had booked it at the level). Swings 0 / 0.3 / 0.5 / 1 / 2 / 3%."""
import os
import sys
os.environ["FILL"] = "close"; os.environ["SWINGS"] = "0,0.3,0.5,1,2,3"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tb_min_swing  # noqa: E402
tb_min_swing.main()
