"""Find state on the root filesystem that isn't declared.

The root filesystem is wiped on every boot; only the paths declared in
aiBox.state.paths (hosts/ai-box/state/paths.nix) are kept. This walks the root
and reports everything not covered by a declaration: state a reboot deletes.

Other filesystems and subvolumes (/nix, /home, /proc, ...) are skipped; they
aren't part of the root and aren't wiped.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Most paths listed in the summary and the reboot-gate output, so a runaway
# directory can't flood Discord or the terminal.
MAX_LISTED = 200

# Symlinks pointing into these are recreated at boot or by NixOS activation
# (e.g. /etc/localtime -> /etc/zoneinfo/..., /var/run -> ../run), so they
# aren't state.
MANAGED_LINK_PREFIXES = (
    "/nix/store/",
    "/etc/static/",
    "/etc/zoneinfo/",
    "/proc/",
    "/run/",
    "../run",
)

# "ephemeral" paths bigger than this are flagged: anything this large is
# probably a cache or data that was wrongly marked disposable.
LARGE_EPHEMERAL_BYTES = 500 * 1000**2  # 500 MB

OK_SUMMARY = "OK: all state on the root filesystem is declared"


@dataclass(frozen=True)
class Declaration:
    backup: str  # git | restic | cache | manual | ephemeral
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
    return {Path(path): Declaration(**fields) for path, fields in raw.items()}


def is_covered(path: Path, declared: Mapping[Path, Declaration]) -> bool:
    """Is `path` declared, or inside a declared path?"""
    return any(p in declared for p in (path, *path.parents))


def has_declared_descendant(path: Path, declared: Mapping[Path, Declaration]) -> bool:
    return any(path in d.parents for d in declared)


def nearest_declared_parent(
    path: Path, declared: Mapping[Path, Declaration]
) -> Path | None:
    return next((p for p in path.parents if p in declared), None)


def is_managed_symlink(path: Path) -> bool:
    try:
        target = str(path.readlink())
    except OSError:
        return False
    return target.startswith(MANAGED_LINK_PREFIXES)


def measure(root: Path, device: int) -> Usage:
    """Size, file count and newest mtime of the tree at `root`, without
    leaving `device` (mounts and other subvolumes inside it are skipped)."""
    total = files = 0
    newest = 0.0
    for directory, subdirs, names in root.walk(on_error=lambda _: None):
        # Prune in place, which stops walk() from descending: keep only real
        # directories on the same device (not symlinks, mounts or subvolumes).
        subdirs[:] = [d for d in subdirs if _is_dir_on(directory / d, device)]
        for name in names:
            entry = directory / name
            try:
                st = entry.lstat()
            except OSError:
                continue  # deleted while we were walking
            if stat.S_ISLNK(st.st_mode) and is_managed_symlink(entry):
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
            if not is_managed_symlink(path):
                findings.append(Finding(path, "symlink", Usage(0, 1, st.st_mtime)))
        elif not stat.S_ISDIR(st.st_mode):
            findings.append(Finding(path, "file", Usage(st.st_size, 1, st.st_mtime)))
        elif has_declared_descendant(path, declared):
            # Partly declared, like /var/lib: judge each child on its own.
            for child in sorted(path.iterdir()):
                visit(child)
        else:
            # Wholly undeclared: report the directory once. Empty ones are
            # skipped; systemd-tmpfiles recreates the directories that matter.
            usage = measure(path, device)
            if usage.files:
                findings.append(Finding(path, "dir", usage))

    # The root itself can't be declared; always judge its children.
    for child in sorted(root.iterdir()):
        visit(child)
    return findings


def declared_usage(declared: Mapping[Path, Declaration]) -> dict[Path, Usage]:
    """Usage of each declared path, minus the declared paths nested inside it
    (those have their own backup class, e.g. a cache inside a restic folder)."""
    total = {path: _usage_of(path) for path in declared}
    own = dict(total)
    for path in declared:
        if (parent := nearest_declared_parent(path, declared)) is not None:
            own[parent] -= total[path]
    return own


def _usage_of(path: Path) -> Usage:
    try:
        st = path.lstat()
    except OSError:
        return Usage()  # declared but doesn't exist (yet)
    if stat.S_ISDIR(st.st_mode):
        return measure(path, st.st_dev)
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
        if decl.backup == "ephemeral" and usage[path].bytes > LARGE_EPHEMERAL_BYTES
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
    usage = declared_usage(declared)
    report = {
        "generated": round(time.time(), 1),
        "undeclared": [f.to_json() for f in findings],
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
