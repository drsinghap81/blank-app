"""Runner: Pulse rotation with the 'Friday closed red -> skip the basket' rule (23 Nov 2026). See pulse_system.py REDLIGHT."""
import os
import runpy
os.environ["REDLIGHT"] = "1"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_system.py"), run_name="__main__")
