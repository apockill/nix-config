"""Cron monitor source for the state audit, plus the errors of this boot's
root reset. Output is stable (no timestamps), so the cron model runs only
when the set of undeclared paths or reset errors changes."""

import os
import time
from itertools import takewhile
from pathlib import Path

SUMMARY = (
    Path(os.environ.get("STATE_AUDIT_DIR", "/var/lib/state-audit")) / "summary.txt"
)
# The audit runs hourly; a report older than 3 hours means it has stopped.
STALE_SECONDS = 3 * 60 * 60  # 3 hours
# Written once per boot by root-reset-report (root_reset_report.py).
ROOT_RESET_REPORT = Path("/var/lib/root-reset/report.txt")


def main() -> None:
    try:
        reset = ROOT_RESET_REPORT.read_text().splitlines()
    except OSError:
        reset = []
    # The report starts with its errors, each followed by indented paths.
    for line in takewhile(lambda line: line.startswith(("ERROR:", "  ")), reset):
        print(f"ROOT RESET {line}" if line.startswith("ERROR:") else line)
    try:
        age = time.time() - SUMMARY.stat().st_mtime
        summary = SUMMARY.read_text().strip()
    except OSError:
        print("PROBLEM: no state-audit report yet (is state-audit.timer running?)")
        return
    if age > STALE_SECONDS:
        print(
            "PROBLEM: the state-audit report is stale; the hourly audit isn't running."
        )
    print(summary)


if __name__ == "__main__":
    main()
