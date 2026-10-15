"""Cron monitor source for the state audit. Output is stable (no timestamps),
so the cron model runs only when the set of unexplained paths changes."""

import os
import time

DIR = os.environ.get("STATE_AUDIT_DIR", "/var/lib/state-audit")
STALE_S = 3 * 3600

try:
    age = time.time() - os.path.getmtime(f"{DIR}/summary.txt")
    with open(f"{DIR}/summary.txt") as f:
        summary = f.read().strip()
except OSError:
    print("PROBLEM: no state-audit report yet (is state-audit.timer running?)")
    raise SystemExit(0)

if age > STALE_S:
    print("PROBLEM: the state-audit report is stale; the hourly audit isn't running.")
print(summary)
