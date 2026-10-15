"""Cron monitor source for the backups. Output is stable (no timestamps), so
the cron model runs only when the set of problems changes."""

import os
import subprocess
import time
from pathlib import Path

STATUS = Path(os.environ.get("BACKUP_STATUS_DIR", "/var/lib/backup-status"))
# Backups run daily; allow a missed night plus the randomized delay.
BACKUP_MAX_AGE = 36 * 60 * 60  # 36 hours
# The restore drill runs weekly; allow one missed run plus slack.
DRILL_MAX_AGE = 8 * 24 * 60 * 60  # 8 days
UNITS = ("restic-backups-gdrive.service", "restic-restore-drill.service")


def age_of(name: str) -> float | None:
    try:
        return time.time() - int((STATUS / name).read_text().strip())
    except (OSError, ValueError):
        return None


def main() -> None:
    problems = []
    for unit in UNITS:
        state = subprocess.run(
            ["systemctl", "is-failed", unit], capture_output=True, text=True
        ).stdout.strip()
        if state == "failed":
            problems.append(f"PROBLEM: the last run of {unit} failed.")
    backup = age_of("last-backup")
    if backup is None or backup > BACKUP_MAX_AGE:
        problems.append("PROBLEM: no successful backup in the last 36 hours.")
    drill = age_of("last-drill")
    if drill is None or drill > DRILL_MAX_AGE:
        problems.append("PROBLEM: no successful restore drill in the last 8 days.")
    print("\n".join(problems) or "OK: backups and restore drills are current.")


if __name__ == "__main__":
    main()
