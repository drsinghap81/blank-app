"""Pilot: commodity and coin rotation (tools/world_sector_rrg.py COMM / CRYPTO), dry run - prints quadrants, writes nothing."""
import sys

sys.path.insert(0, "tools")
import world_sector_rrg as W  # noqa: E402

for m in ("COMM", "CRYPTO"):
    W.main(m, dry=True)
