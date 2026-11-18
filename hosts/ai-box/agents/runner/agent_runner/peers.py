"""Who calls the API: from outside the runner, or from inside one of its sessions.

The socket is its user's only (0600), and every session's processes run as that user, so the
socket can't tell a session's processes from Hermes. The runner tells them apart by the caller's
process (the socket's SO_PEERCRED pid, server.py):
  - a descendant of a session's agent process is that session;
  - a process that left that tree but still has a session's marker (AGENT_RUNNER_SESSION and
    AGENT_RUNNER_OF, which every agent gets) is from inside a session the runner can't name;
  - in the service, a process in the service's own cgroup is too: every agent and everything it
    starts stays there (a cgroup can't be left without privileges), even with no marker left.
A request from inside a session is refused unless the session was started with allow_runner, so a
fenced session (a Sculpt builder) can't start an unfenced one or answer another's requests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import RunnerError

SESSION_VAR = "AGENT_RUNNER_SESSION"
RUNNER_VAR = "AGENT_RUNNER_OF"


@dataclass(frozen=True)
class Caller:
    """A caller: outside every session, or inside one (`session`: its name, if known)."""

    pid: int
    inside: bool = False
    session: str | None = None
    how: str = ""


def marker(session: str, runner: str) -> dict[str, str]:
    """The variables every agent of this runner gets: its session, and the runner (its socket)."""
    return {SESSION_VAR: session, RUNNER_VAR: runner}


@dataclass(frozen=True)
class Peers:
    # The runner, named by its socket (the marker's AGENT_RUNNER_OF).
    runner: str
    # Whether the service has a cgroup of its own (systemd's), so that being in it means being
    # one of its agents' processes. Not in the tests, where the runner shares pytest's.
    own_cgroup: bool = False
    proc: Path = Path("/proc")

    def identify(self, pid: int, agents: Mapping[int, str], me: int) -> Caller:
        """The caller with process `pid`; `agents` maps each session's agent process to the
        session, `me` is the runner's own pid."""
        for ancestor in self.ancestry(pid):
            if ancestor in agents:
                return Caller(pid, True, agents[ancestor], "its agent's process tree")
            if ancestor == me:
                break
        env = self.environ(pid)
        if env.get(RUNNER_VAR) == self.runner and SESSION_VAR in env:
            return Caller(pid, True, None, f"{SESSION_VAR}={env[SESSION_VAR]}")
        if self.own_cgroup and pid != me:
            mine, theirs = self.cgroup(me), self.cgroup(pid)
            if mine is not None and mine == theirs:
                return Caller(pid, True, None, f"the runner's cgroup {mine}")
        return Caller(pid)

    def ancestry(self, pid: int) -> list[int]:
        """The process and its parents, up to (not including) pid 1; [] if it's gone."""
        chain: list[int] = []
        while pid > 1 and pid not in chain:
            chain.append(pid)
            try:
                stat = (self.proc / str(pid) / "stat").read_text()
            except OSError:
                break
            # pid (comm) state ppid ...: comm may hold spaces and parentheses.
            pid = int(stat[stat.rindex(")") + 2 :].split()[1])
        return chain

    def environ(self, pid: int) -> dict[str, str]:
        try:
            raw = (self.proc / str(pid) / "environ").read_bytes()
        except OSError:
            return {}
        pairs = (item.split(b"=", 1) for item in raw.split(b"\0") if b"=" in item)
        return {
            k.decode(errors="replace"): v.decode(errors="replace") for k, v in pairs
        }

    def cgroup(self, pid: int) -> str | None:
        """The process's cgroup (v2's unified hierarchy)."""
        try:
            lines = (self.proc / str(pid) / "cgroup").read_text().splitlines()
        except OSError:
            return None
        return next((line[3:] for line in lines if line.startswith("0::")), None)


def admit(caller: Caller, allowed: Mapping[str, bool]) -> None:
    """RunnerError 403 unless the caller is outside every session, or inside one that may use the
    runner (`allowed`: each session's allow_runner)."""
    if not caller.inside:
        return
    if caller.session is None:
        raise RunnerError(
            f"refused: process {caller.pid} is inside an agent session ({caller.how}) and the"
            " runner can't tell which, so it may not use the runner",
            403,
        )
    if not allowed.get(caller.session, False):
        raise RunnerError(
            f"refused: process {caller.pid} is inside session {caller.session}, which may not"
            " use the runner (start it with allow_runner to let it)",
            403,
        )
