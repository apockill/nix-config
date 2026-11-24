"""Cron gate for board-keeper (see ./default.nix): a stable snapshot of open work.

Prints the open kanban cards, the lab lock and queue, the open pull requests and the running agent
jobs, plus the current two-hour slot while anything is open, so Hermes's monitor mode wakes the
agent at most every two hours, and at once when the snapshot changes. Prints `IDLE` when nothing is
open. Any source it can't read is named (`unreadable: ...`), never skipped silently.
"""

import os
import subprocess
import time

BIN = "/etc/profiles/per-user/hermes/bin"
HOME = "/var/lib/hermes"
ENV = {**os.environ, "PATH": f"{BIN}:/run/current-system/sw/bin:{os.environ.get('PATH', '')}"}


def run(*args: str, cwd: str = HOME) -> str | None:
    try:
        r = subprocess.run(list(args), cwd=cwd, env=ENV, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


out: list[str] = []
unreadable: list[str] = []

board = run("hermes", "kanban", "list", cwd=f"{HOME}/workspace")
if board is None:
    unreadable.append("kanban")
else:
    cards = sorted(
        " ".join(line.split())
        for line in board.splitlines()
        if " t_" in f" {line}" and not any(s in line for s in (" done ", " archived "))
    )
    out += ["## cards"] + cards

lab = run(f"{HOME}/workspace/bin/lab-stretch", "status")
if lab is None:
    unreadable.append("lab-stretch")
else:
    out += ["## lab"] + [line[:160] for line in lab.splitlines()]

prs: list[str] = []
for repo in ("apockill/ai-box-apps", "apockill/nix-config"):
    got = run("gh", "pr", "list", "--repo", repo, "--state", "open", "--json",
              "number,title,reviewDecision", "-q",
              '.[]|"\\(.number) \\(.reviewDecision) \\(.title[0:70])"')
    if got is None:
        unreadable.append(f"prs {repo}")
    else:
        prs += [f"{repo.split('/')[1]}#{line}" for line in got.splitlines()]
out += ["## pull requests"] + sorted(prs)

jobs = run("agent", "list")
if jobs is None:
    unreadable.append("agent jobs")
else:
    running = sorted({ln.split()[0] for ln in jobs.splitlines()
                      if "running" in ln.lower() and ln.split()})
    out += ["## running jobs"] + running

if unreadable:
    out.append("unreadable: " + ", ".join(unreadable))
opened = any(line.startswith("## cards") for line in out) and len(out) > 1
if not opened and not prs:
    print("IDLE")
else:
    print(f"SLOT {time.strftime('%Y-%m-%d')} {int(time.strftime('%H')) // 2}")
    print("\n".join(out))
