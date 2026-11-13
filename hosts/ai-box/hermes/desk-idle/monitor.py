"""Cron monitor source for desk-idle (see ./default.nix).

Decides from fixed rules whether Alex's desk is idle, so the cron model never weighs the rules
itself (the local model twice switched the projector off while the desk was in use). Prints one
VERDICT line, stable between ticks (no timestamps or counts), so Hermes runs the model only when
the verdict changes:

  VERDICT: ASLEEP               nothing is on
  VERDICT: IN_USE <reasons>     something is using the desk
  VERDICT: CHECK_PHOTO <image>  idle by every machine signal; the model checks the photo for a
                                person, then runs the SLEEP lines below it
"""

import glob
import json
import os
import subprocess
import time

BIN = "/etc/profiles/per-user/hermes/bin"
SITES = "/var/lib/hermes/sites"
HOME = "/var/lib/hermes"
PHOTO = f"{HOME}/.hermes/cache/desk-idle.jpg"
ENV = {**os.environ, "PATH": f"{BIN}:/run/current-system/sw/bin:{os.environ.get('PATH', '')}"}
QUIET_MIN = 60


def run(*args: str, timeout: int = 60) -> str | None:
    try:
        r = subprocess.run(args, cwd=SITES, env=ENV, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def box_json(*args: str):
    out = run(f"{BIN}/box", *args, "--json")
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def verdict(text: str) -> None:
    print(f"VERDICT: {text}")
    raise SystemExit(0)


state = box_json("lab-arm", "state")
switches = box_json("lab-matter", "switches")
if state is None or switches is None:
    verdict("IN_USE cannot read the arm or the switches")
motors = state.get("state", {}).get("power") == 1
by_name = {s.get("name"): s for s in switches}
light = bool(by_name.get("Desk light", {}).get("state", {}).get("on"))
proj = by_name.get("Projector", {})
proj_on = bool(proj.get("state", {}).get("on"))
if not (motors or light or proj_on):
    verdict("ASLEEP")

why = []
for inst in ("lab-motion", "lab-arm", "lab-calibration", "lab-scanner", "lab-world", "lab-projector"):
    h = box_json(inst, "health")
    if h is None:
        why.append(f"{inst}-unreachable")
        continue
    if sum(len(v or []) for v in (h.get("goals") or {}).values()) > 0:
        why.append(f"{inst}-running")
    if h.get("lease"):
        why.append(f"{inst}-leased")

events = (box_json("lab-arm", "events") or {}).get("events", [])
commands = [e for e in events if e.get("kind") == "command"]
if not commands or time.time() - commands[-1].get("t", 0) < QUIET_MIN * 60:
    why.append(f"arm-command-within-{QUIET_MIN}min")

jobs = run(f"{BIN}/cc", "list") or ""
for line in jobs.splitlines():
    name = line.split(" ", 1)[0]
    if " running since " not in line or name.startswith("resume-"):
        continue
    busy = "esc to interrupt" in (run(f"{BIN}/cc", "peek", name, "40") or "")
    try:
        sid = json.load(open(f"{HOME}/.claude/cc-jobs/{name}.json")).get("session_id", "")
    except (OSError, ValueError):
        sid = ""
    recent = sid and any(
        time.time() - os.path.getmtime(p) < QUIET_MIN * 60
        for p in glob.glob(f"{HOME}/.claude/projects/*/{sid}*", recursive=False)
        + glob.glob(f"{HOME}/.claude/projects/*/{sid}/**/*.jsonl", recursive=True)
    )
    if busy or recent:
        why.append(f"job-{name}-active")

if why:
    verdict("IN_USE " + " ".join(sorted(why)))

if run(f"{BIN}/box", "lab-cam-top", "snapshot", "-o", PHOTO) is None:
    verdict("IN_USE overhead snapshot failed")
print(f"VERDICT: CHECK_PHOTO {PHOTO}")
if motors:
    print(f"SLEEP: cd {SITES} && box lab-motion rest --json | jq -c '{{rest: .status, error}}' && box lab-arm release --json | jq -c '{{release: .status, error}}'")
if light:
    print(f"SLEEP: cd {SITES} && box lab-projector set-light --no-on --json | jq -c .")
if proj_on:
    print(f"SLEEP: cd {SITES} && box lab-matter switches off {proj.get('id')}")
