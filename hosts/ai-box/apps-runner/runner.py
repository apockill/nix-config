"""Supervisor, healer and uptime recorder for the apps in /var/lib/hermes/sites.

Every app directory with an executable start.sh is launched and kept running.
Each app is health-checked by an HTTP request over its app.sock. The process
being alive isn't enough: a socket file can be deleted while its server keeps
running. Unhealthy apps are restarted with backoff and a cap. Once an app hits
the cap, the runner gives up on it and marks it failed, so a broken app can
never become a restart loop.

Everything is recorded in $STATE_DIRECTORY for the portal status page and the
cron monitor:
  events.jsonl  append-only: status changes and actions (the uptime history)
  status.json   current snapshot plus a heartbeat (rewritten every loop)

To restart an app on purpose (e.g. after a code change), touch
<app>/.runner.restart; this doesn't count against the healing cap. Never start
a second copy of an app by hand: when it exits it deletes the shared app.sock.
To re-arm a failed app, delete <app>/.runner.failed or commit a change to it.
"""

import json
import os
import signal
import socket
import subprocess
import time
from collections import deque

SITES = os.environ.get("SITES_DIR", "/var/lib/hermes/sites")
STATE = os.environ.get("STATE_DIRECTORY", "/var/lib/apps-health")
EVENTS = os.path.join(STATE, "events.jsonl")
STATUS = os.path.join(STATE, "status.json")

# Timings (env overrides exist for testing with a fake sites dir).
_T = float(os.environ.get("RUNNER_TIME_SCALE", "1"))
LOOP_S = 10 * _T            # supervision tick
CHECK_EVERY_S = 30 * _T     # health-check interval per app
GRACE_S = 180 * _T          # time after launch before checks count (nix develop is slow)
FAILS_TO_HEAL = 3           # consecutive failed checks before a restart (~90 s)
MAX_RESTARTS = 3            # restarts allowed per window before giving up
WINDOW_S = 3600 * _T
BACKOFF_S = [10 * _T, 60 * _T, 300 * _T]  # delay before restart n (crash or heal)
LOG_TAIL = 15


def now() -> float:
    return time.time()


def log(msg: str) -> None:
    print(f"[apps-runner] {msg}", flush=True)


def record(app: str, kind: str, **fields) -> None:
    event = {"ts": round(now(), 1), "app": app, "event": kind, **fields}
    with open(EVENTS, "a") as f:
        f.write(json.dumps(event) + "\n")
    log(f"{app}: {kind} {fields.get('reason', '')}".rstrip())


def tail(path: str, n: int = LOG_TAIL) -> list:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 16384))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return [l[:300] for l in lines[-n:]]
    except OSError:
        return []


def http_check(sock_path: str) -> tuple:
    """(ok, reason). Up = the server answers GET / with a status below 500."""
    if not os.path.exists(sock_path):
        return False, "app.sock missing"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(sock_path)
        s.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
        head = s.recv(64).decode("latin-1", "replace")
        parts = head.split(" ", 2)
        if len(parts) < 2 or not parts[1].isdigit():
            return False, "bad HTTP response"
        code = int(parts[1])
        return (code < 500), f"HTTP {code}"
    except OSError as e:
        return False, f"socket error: {e.strerror or e}"
    finally:
        s.close()


def git_rev(app: str) -> str:
    try:
        out = subprocess.run(["git", "-C", SITES, "log", "-1", "--format=%H", "--", app],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class App:
    def __init__(self, name: str):
        self.name = name
        self.dir = os.path.join(SITES, name)
        self.proc = None
        self.started = 0.0
        self.status = "starting"
        self.since = now()
        self.reason = ""
        self.fails = 0
        self.last_check = 0.0
        self.restarts = deque()
        self.next_launch = 0.0
        self.failed_rev = None

    # -- bookkeeping ---------------------------------------------------
    def set_status(self, status: str, reason: str = "", **extra) -> None:
        if status == self.status and not extra:
            return
        prev, self.status, self.since, self.reason = self.status, status, now(), reason
        record(self.name, "status", status=status, prev=prev, reason=reason, **extra)

    def recent_restarts(self) -> int:
        while self.restarts and now() - self.restarts[0] > WINDOW_S:
            self.restarts.popleft()
        return len(self.restarts)

    @property
    def failed_marker(self) -> str:
        return os.path.join(self.dir, ".runner.failed")

    # -- process control -----------------------------------------------
    def launch(self, why: str) -> None:
        logf = open(os.path.join(self.dir, "app.log"), "w")
        self.proc = subprocess.Popen(["./start.sh"], cwd=self.dir, stdout=logf,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        logf.close()
        with open(os.path.join(self.dir, ".runner.pid"), "w") as f:
            f.write(str(self.proc.pid))
        self.started, self.fails, self.last_check = now(), 0, 0.0
        record(self.name, "launch", reason=why, pid=self.proc.pid)
        self.set_status("starting", why)

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def schedule_restart(self, why: str) -> None:
        """Count a restart; give up past the cap, else relaunch after a backoff."""
        n = self.recent_restarts()
        logtail = tail(os.path.join(self.dir, "app.log"))
        if n >= MAX_RESTARTS:
            self.stop()
            self.failed_rev = git_rev(self.name)
            with open(self.failed_marker, "w") as f:
                f.write(f"{why}\n")
            self.set_status("failed", why, restarts=n, log=logtail)
            return
        self.restarts.append(now())
        self.next_launch = now() + BACKOFF_S[min(n, len(BACKOFF_S) - 1)]
        record(self.name, "heal", reason=why, attempt=n + 1, log=logtail)
        self.stop()
        self.set_status("down", why)
        self.proc = None

    # -- one supervision tick --------------------------------------------
    def tick(self) -> None:
        if self.status == "failed":
            rearm = not os.path.exists(self.failed_marker)
            if not rearm and git_rev(self.name) != self.failed_rev:
                rearm = True
                os.remove(self.failed_marker)
            if not rearm:
                return
            self.restarts.clear()
            record(self.name, "rearm", reason="failed marker cleared or app changed")
            self.launch("re-armed")
            return

        if self.proc is None:
            if now() >= self.next_launch:
                self.launch("restart" if self.restarts else "start")
            return

        restart_req = os.path.join(self.dir, ".runner.restart")
        if os.path.exists(restart_req):
            os.remove(restart_req)
            record(self.name, "restart", reason="requested (.runner.restart)")
            self.stop()
            self.launch("requested restart")
            return

        code = self.proc.poll()
        if code is not None:
            self.schedule_restart(f"process exited with code {code}")
            return

        if now() - self.started < GRACE_S and self.status == "starting":
            ok, why = http_check(os.path.join(self.dir, "app.sock"))
            if ok:
                self.set_status("up", why)
            return

        if now() - self.last_check < CHECK_EVERY_S:
            return
        self.last_check = now()
        ok, why = http_check(os.path.join(self.dir, "app.sock"))
        if ok:
            self.fails = 0
            self.set_status("up", why)
            return
        self.fails += 1
        if self.status == "up":
            self.set_status("degraded", why)
        if self.fails >= FAILS_TO_HEAL:
            self.schedule_restart(f"health check failed {self.fails}x: {why}")


def discover() -> list:
    names = []
    for name in sorted(os.listdir(SITES)):
        if name.startswith((".", "_")) or name == "default":
            continue
        if os.access(os.path.join(SITES, name, "start.sh"), os.X_OK):
            names.append(name)
    return names


def write_status(apps: dict, runner_started: float) -> None:
    snap = {
        "heartbeat": round(now(), 1),
        "runner_started": runner_started,
        "apps": {
            a.name: {"status": a.status, "since": round(a.since, 1), "reason": a.reason,
                     "restarts_1h": a.recent_restarts(),
                     "pid": a.proc.pid if a.proc and a.proc.poll() is None else None}
            for a in apps.values()
        },
    }
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.replace(tmp, STATUS)


def main() -> None:
    os.makedirs(STATE, exist_ok=True)
    prev_heartbeat = None
    try:
        with open(STATUS) as f:
            prev_heartbeat = json.load(f).get("heartbeat")
    except (OSError, ValueError):
        pass
    started = round(now(), 1)
    record("_runner", "runner_start", prev_heartbeat=prev_heartbeat)

    apps = {}
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    while not stopping:
        present = discover()
        for name in present:
            if name not in apps:
                apps[name] = App(name)
                if os.path.exists(apps[name].failed_marker):
                    # Survive runner restarts: a failed app stays failed.
                    apps[name].status = "failed"
                    apps[name].failed_rev = git_rev(name)
                    with open(apps[name].failed_marker) as f:
                        apps[name].reason = f.read().strip()
                    record(name, "status", status="failed", prev="unknown",
                           reason=apps[name].reason)
        for name in list(apps):
            if name not in present:
                apps[name].stop()
                record(name, "removed")
                del apps[name]
                continue
            try:
                apps[name].tick()
            except Exception as e:  # one bad app must never take down the runner
                log(f"{name}: tick error {e!r}")
        write_status(apps, started)
        time.sleep(LOOP_S)

    # Apps live in this service's cgroup; systemd stops them with us.
    record("_runner", "runner_stop")


if __name__ == "__main__":
    main()
