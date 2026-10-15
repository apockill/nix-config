"""Find state on the root filesystem that isn't declared.

The root filesystem is wiped on every boot; only the paths declared in
aiBox.state.paths (hosts/ai-box/state/paths.nix) are kept. This walks the root
and reports everything not covered by a declaration: state a reboot deletes.

Other filesystems and subvolumes (/nix, /home, /proc, ...) are skipped; they
aren't part of the root and aren't wiped.

It also lists, as a low-key note, files inside `git` paths that aren't
committed. Those are disposable by design (the repo is the source of truth),
but it's worth seeing what accumulates there.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

# Most paths listed in the summary and the reboot-gate output, so a runaway
# directory can't flood Discord or the terminal.
MAX_LISTED = 200

# Symlinks pointing into these are recreated at boot or by NixOS activation
# (e.g. /etc/localtime -> /etc/zoneinfo/..., /var/run -> ../run), so they
# aren't state.
MANAGED_LINK_PREFIXES = (
    "/etc/static/",
    "/etc/zoneinfo/",
    "/proc/",
    "/run/",
    "../run",
)

# Links into the Nix store are recreated only in the system directories NixOS
# populates (/etc, /bin/sh, /usr/bin/env, the /lib stub loader). Anywhere else nothing recreates
# them: a hand-made ~/.local/bin/claude is state.
NIX_STORE_LINK_DIRS = {"etc", "bin", "usr", "lib", "lib64"}

# "ephemeral" paths bigger than this are flagged: anything this large is
# probably a cache or data that was wrongly marked disposable.
LARGE_EPHEMERAL_BYTES = 500 * 1000**2  # 500 MB

# Uncommitted files inside git repos that are never interesting: build output
# (by directory or link name) and runtime files (by suffix: app logs, the
# apps-runner's .runner.pid).
BUILD_ARTIFACTS = {"__pycache__", "node_modules", ".pytest_cache", "dist", "result"}
RUNTIME_SUFFIXES = (".log", ".pid")

# SQLite keeps recent writes in these files next to the database; a declared
# database covers them.
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")

OK_SUMMARY = "OK: all state on the root filesystem is declared"


class Backup(StrEnum):
    """How a declared path is backed up. Mirrors the classes in default.nix,
    which documents what each one means."""

    GIT = "git"
    RESTIC = "restic"
    CACHE = "cache"
    HOST = "host"
    MANUAL = "manual"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class Declaration:
    backup: Backup
    why: str
    repo: str | None = None


@dataclass(frozen=True)
class Usage:
    bytes: int = 0
    files: int = 0
    newest: float = 0.0  # mtime of the most recently modified entry

    def __sub__(self, other: Usage) -> Usage:
        return Usage(
            max(0, self.bytes - other.bytes),
            max(0, self.files - other.files),
            self.newest,
        )


@dataclass(frozen=True)
class Finding:
    """An undeclared path. Undeclared directories are reported as one unit."""

    path: Path
    kind: Literal["dir", "file", "symlink"]
    usage: Usage

    def to_json(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "bytes": self.usage.bytes,
            "files": self.usage.files,
            "newest": self.usage.newest,
        }


def load_declared(json_file: Path) -> dict[Path, Declaration]:
    """Read the declarations Nix exports: {path: {backup, why, repo}}."""
    raw = json.loads(json_file.read_text())
    return {
        Path(path): Declaration(
            backup=Backup(fields["backup"]), why=fields["why"], repo=fields.get("repo")
        )
        for path, fields in raw.items()
    }


def is_covered(path: Path, declared: Mapping[Path, Declaration]) -> bool:
    """Is `path` declared, inside a declared path, or a declared SQLite
    database's sidecar file?"""
    if any(p in declared for p in (path, *path.parents)):
        return True
    return any(
        path.name.endswith(suffix)
        and path.with_name(path.name.removesuffix(suffix)) in declared
        for suffix in SQLITE_SIDECARS
    )


def has_declared_descendant(path: Path, declared: Mapping[Path, Declaration]) -> bool:
    return any(path in d.parents for d in declared)


def nearest_declared_parent(
    path: Path, declared: Mapping[Path, Declaration]
) -> Path | None:
    return next((p for p in path.parents if p in declared), None)


def is_managed_symlink(path: Path, root: Path) -> bool:
    """Is `path` a symlink that NixOS recreates? `root` is the filesystem root
    being audited (so system directories can be recognized)."""
    try:
        target = str(path.readlink())
    except OSError:
        return False
    if target.startswith(MANAGED_LINK_PREFIXES):
        return True
    top_dir = path.relative_to(root).parts[0]
    return target.startswith("/nix/store/") and top_dir in NIX_STORE_LINK_DIRS


def measure(tree: Path, device: int, root: Path) -> Usage:
    """Size, file count and newest mtime of `tree`, without leaving `device`
    (mounts and other subvolumes inside it are skipped). `root` is the
    filesystem root being audited."""
    total = files = 0
    newest = 0.0
    for directory, subdirs, names in tree.walk(on_error=lambda _: None):
        # Prune in place, which stops walk() from descending: keep only real
        # directories on the same device (not symlinks, mounts or subvolumes).
        subdirs[:] = [d for d in subdirs if _is_dir_on(directory / d, device)]
        for name in names:
            entry = directory / name
            try:
                st = entry.lstat()
            except OSError:
                continue  # deleted while we were walking
            if stat.S_ISLNK(st.st_mode) and is_managed_symlink(entry, root):
                continue
            files += 1
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
            newest = max(newest, st.st_mtime)
    return Usage(total, files, newest)


def _is_dir_on(path: Path, device: int) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_dev == device


def find_undeclared(root: Path, declared: Mapping[Path, Declaration]) -> list[Finding]:
    """Walk `root` and return everything that no declaration covers."""
    device = root.lstat().st_dev
    findings: list[Finding] = []

    def visit(path: Path) -> None:
        try:
            st = path.lstat()
        except OSError:
            return  # deleted while we were walking
        if st.st_dev != device or is_covered(path, declared):
            return  # another filesystem (not wiped), or declared (kept)

        if stat.S_ISLNK(st.st_mode):
            if not is_managed_symlink(path, root):
                findings.append(Finding(path, "symlink", Usage(0, 1, st.st_mtime)))
        elif not stat.S_ISDIR(st.st_mode):
            findings.append(Finding(path, "file", Usage(st.st_size, 1, st.st_mtime)))
        elif has_declared_descendant(path, declared):
            # Partly declared, like /var/lib: judge each child on its own.
            for child in _children(path):
                visit(child)
        else:
            # Wholly undeclared: report the directory once. Empty ones are
            # skipped; systemd-tmpfiles recreates the directories that matter.
            usage = measure(path, device, root)
            if usage.files:
                findings.append(Finding(path, "dir", usage))

    # The root itself can't be declared; always judge its children.
    for child in _children(root):
        visit(child)
    return findings


def uncommitted_in_git_paths(declared: Mapping[Path, Declaration]) -> list[Path]:
    """Untracked or ignored files inside `git` paths that have no declaration
    of their own. Disposable by design; reported only so we can keep an eye on
    what accumulates."""
    found: list[Path] = []
    for repo, decl in sorted(declared.items()):
        if decl.backup != Backup.GIT:
            continue
        # safe.directory: the audit runs as root, but the repos belong to hermes.
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(repo),
             "status", "--porcelain", "--ignored", "-z"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue  # not a repo (yet), or git isn't available
        for entry in result.stdout.split("\0"):
            # "?? path" is untracked, "!! path" is ignored; directories that
            # are entirely uncommitted come back as one entry ending in "/".
            if not entry.startswith(("??", "!!")):
                continue
            path = repo / entry[3:].rstrip("/")
            relative = path.relative_to(repo)
            if (
                BUILD_ARTIFACTS & set(relative.parts)
                or path.name.endswith(RUNTIME_SUFFIXES)
                or _is_socket(path)
            ):
                continue
            # Declared separately inside the repo (e.g. a database as restic)?
            inner = {p: d for p, d in declared.items() if repo in p.parents}
            if not is_covered(path, inner):
                found.append(path)
    return found


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.lstat().st_mode)
    except OSError:
        return False


def _children(directory: Path) -> list[Path]:
    """Sorted entries of `directory`; none if it can't be listed (only
    happens when not running as root, or if it vanished mid-walk)."""
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def declared_usage(
    declared: Mapping[Path, Declaration], root: Path = Path("/")
) -> dict[Path, Usage]:
    """Usage of each declared path, minus the declared paths nested inside it
    (those have their own backup class, e.g. a cache inside a restic folder)."""
    total = {path: _usage_of(path, root) for path in declared}
    own = dict(total)
    for path in declared:
        if (parent := nearest_declared_parent(path, declared)) is not None:
            own[parent] -= total[path]
    return own


def _usage_of(path: Path, root: Path) -> Usage:
    try:
        st = path.lstat()
    except OSError:
        return Usage()  # declared but doesn't exist (yet)
    if stat.S_ISDIR(st.st_mode):
        return measure(path, st.st_dev, root)
    return Usage(st.st_size, 1, st.st_mtime)


def summarize(
    findings: Sequence[Finding],
    declared: Mapping[Path, Declaration],
    usage: Mapping[Path, Usage],
) -> str:
    """Text for the cron monitor. Paths only (no sizes or times), so it only
    changes, and wakes the model, when the set of problems changes."""
    sections = []
    if findings:
        paths = [str(f.path) for f in findings[:MAX_LISTED]]
        sections.append("UNDECLARED STATE (deleted on reboot):\n" + "\n".join(paths))
    large = [
        str(path)
        for path, decl in sorted(declared.items())
        if decl.backup == Backup.EPHEMERAL and usage[path].bytes > LARGE_EPHEMERAL_BYTES
    ]
    if large:
        sections.append(
            "LARGE EPHEMERAL (over 500 MB but declared disposable; is that right?):\n"
            + "\n".join(large)
        )
    return "\n".join(sections) or OK_SUMMARY


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file, so readers never see a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def cmd_report(root: Path, declared: Mapping[Path, Declaration], out_dir: Path) -> int:
    findings = find_undeclared(root, declared)
    usage = declared_usage(declared, root)
    report = {
        "generated": round(time.time(), 1),
        "undeclared": [f.to_json() for f in findings],
        "uncommitted_in_git": [str(p) for p in uncommitted_in_git_paths(declared)],
        "declared": [
            {
                "path": str(path),
                "backup": decl.backup,
                "why": decl.why,
                "repo": decl.repo,
                "exists": os.path.lexists(path),
                "bytes": usage[path].bytes,
                "files": usage[path].files,
            }
            for path, decl in sorted(declared.items())
        ],
    }
    summary = summarize(findings, declared, usage)
    write_atomic(out_dir / "report.json", json.dumps(report, indent=1))
    write_atomic(out_dir / "summary.txt", summary + "\n")
    print(summary)
    return 0


def cmd_check(root: Path, declared: Mapping[Path, Declaration]) -> int:
    findings = find_undeclared(root, declared)
    for f in findings[:MAX_LISTED]:
        print(f"  {f.path}  ({f.usage.files} files, {f.usage.bytes / 1e6:.1f} MB)")
    # Informational only: never fails the check.
    if uncommitted := uncommitted_in_git_paths(declared):
        print(f"Note: {len(uncommitted)} uncommitted paths inside git repos "
              "(disposable; see report.json):", file=sys.stderr)
        for path in uncommitted[:MAX_LISTED]:
            print(f"  {path}", file=sys.stderr)
    return 1 if findings else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", type=Path, default=Path("/"), help="filesystem root to audit"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser(
        "report", help="write report.json and summary.txt to OUT_DIR"
    )
    report.add_argument("declared", type=Path, help="declarations JSON from Nix")
    report.add_argument("out_dir", type=Path)

    check = commands.add_parser(
        "check", help="list undeclared paths; exit 1 if there are any"
    )
    check.add_argument("declared", type=Path, help="declarations JSON from Nix")

    args = parser.parse_args(argv)
    declared = load_declared(args.declared)
    if args.command == "report":
        return cmd_report(args.root, declared, args.out_dir)
    return cmd_check(args.root, declared)


if __name__ == "__main__":
    sys.exit(main())
