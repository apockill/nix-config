"""Cron gate for desk-idle (see ./default.nix): is anything on the desk awake?

Prints `ASLEEP` when the arm's motors, the desk light and the projector are all off, so the agent
never runs. Otherwise prints `AWAKE <hour> <what is on>`: the hour changes the output each tick,
so Hermes's monitor mode runs the agent every hour while something stays on.
"""

import json
import os
import subprocess
import time

BIN = "/etc/profiles/per-user/hermes/bin"
ENV = {**os.environ, "PATH": f"{BIN}:/run/current-system/sw/bin:{os.environ.get('PATH', '')}"}


def box_json(*args: str):
    try:
        r = subprocess.run([f"{BIN}/box", *args, "--json"], cwd="/var/lib/hermes/sites", env=ENV,
                           capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


state = box_json("lab-arm", "state")
switches = box_json("lab-matter", "switches")
on = []
if state is None or switches is None:
    on.append("unreadable")  # can't tell: let the agent look
else:
    if state.get("state", {}).get("power") == 1:
        on.append("arm-motors")
    on += [s.get("name", "?").replace(" ", "-") for s in switches if s.get("state", {}).get("on")]
print(f"AWAKE {time.strftime('%Y-%m-%dT%H')} {' '.join(on)}" if on else "ASLEEP")
