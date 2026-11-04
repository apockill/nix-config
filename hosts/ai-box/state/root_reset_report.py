"""Report what this boot's root reset deleted, against what the audit predicted.

Runs once per boot as root (root-reset.nix), after the initrd's root reset
(root-reset.sh) built a fresh root from the declared state and kept the
previous one as @root-old/<N> in the btrfs top level. It compares that old
root with the new one (/), using the same declarations as the audit:

- predicted: what the audit (audit.py) finds undeclared in the old root, the
  paths a reboot was expected to delete;
- lost: undeclared entries of the old root that are gone from the new one.
  Predicted but not lost means something recreated it since boot;
- deleted: declared ephemeral paths that are gone, as planned;
- errors: declared, kept paths that exist in the old root but not in the new
  one. Those are a root-reset bug, and the report starts with them.

It also lists the old roots that are kept, with the space each holds on its
own (btrfs's "exclusive" size). Writes report.txt and report.json to the
report directory, where the initrd left its log (initrd.log) and summary
(info).

Like the audit, the walk stays on the old root's subvolume, and goes into a
declared directory only to check the declarations nested in it: what's
inside a kept directory was copied as a whole.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import audit
from audit import Backup, Declaration, Finding, Usage

# The kernel command-line word that makes the initrd skip the reset.
KEEP_ROOT_PARAM = "ai-box.keep-root"

# Where the top-level subvolume keeps the old roots, as @root-old/<N>.
OLD_ROOTS = "@root-old"

# The running kernel's boot id, which the initrd records in its summary.
BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")
CMDLINE_FILE = Path("/proc/cmdline")


@dataclass
class Comparison:
    """The old root against the new one. Paths are as they were under /."""

    predicted: list[Path] = field(default_factory=list)
    lost: list[Finding] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    errors: list[Path] = field(default_factory=list)

    @property
    def recreated(self) -> list[Path]:
        """Predicted to be deleted, but there again since boot."""
        lost = {f.path for f in self.lost}
        return [p for p in self.predicted if p not in lost]

    @property
    def unpredicted(self) -> list[Path]:
        """Lost although the audit didn't list it (an audit bug)."""
        predicted = set(self.predicted)
        return [f.path for f in self.lost if f.path not in predicted]


@dataclass(frozen=True)
class OldRoot:
    number: int
    info: dict[str, str]
    exclusive_bytes: int | None  # None if btrfs couldn't tell


def read_info(path: Path) -> dict[str, str]:
    """A key=value file the initrd wrote; empty if it doesn't exist."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    return dict(line.split("=", 1) for line in lines if "=" in line)


def keep_root_requested(cmdline: str) -> bool:
    return any(
        word == KEEP_ROOT_PARAM or word.startswith(KEEP_ROOT_PARAM + "=")
        for word in cmdline.split()
    )


def rebase(declared: Mapping[Path, Declaration], root: Path) -> dict[Path, Declaration]:
    """The declarations of / as paths under `root`."""
    return {root / path.relative_to("/"): decl for path, decl in declared.items()}


def governing(path: Path, declared: Mapping[Path, Declaration]) -> Declaration | None:
    """The declaration that decides what happens to `path`: its own, else its
    nearest declared ancestor's, else its SQLite database's (as in the audit)."""
    for candidate in (path, *path.parents):
        if (declared_path := audit.declaration_of(candidate, declared)) is not None:
            return declared[declared_path]
    for suffix in audit.SQLITE_SIDECARS:
        if path.name.endswith(suffix):
            database = path.with_name(path.name.removesuffix(suffix))
            if (declared_path := audit.declaration_of(database, declared)) is not None:
                return declared[declared_path]
    return None


def compare(
    old_root: Path, new_root: Path, declared: Mapping[Path, Declaration]
) -> Comparison:
    """Compare `old_root` with `new_root` under the declarations of /."""
    in_old = rebase(declared, old_root)
    device = old_root.lstat().st_dev
    result = Comparison(
        predicted=[
            _live(f.path, old_root) for f in audit.find_undeclared(old_root, in_old)
        ]
    )

    def visit(path: Path) -> None:
        try:
            st = path.lstat()
        except OSError:
            return
        if st.st_dev != device:
            return  # a nested subvolume: not part of the root
        live = _live(path, old_root)
        present = os.path.lexists(new_root / live.relative_to("/"))
        if stat.S_ISDIR(st.st_mode) and audit.has_declared_descendant(path, in_old):
            # Partly declared: judge each child on its own.
            for child in audit._children(path):
                visit(child)
            return
        decl = governing(path, in_old)
        if decl is None:
            if not present and (finding := _undeclared(path, st, device, old_root)):
                result.lost.append(Finding(live, finding.kind, finding.usage))
        elif decl.backup == Backup.EPHEMERAL:
            if not present:
                result.deleted.append(live)
        elif not present:
            result.errors.append(live)

    for child in audit._children(old_root):
        visit(child)
    return result


def _live(path: Path, root: Path) -> Path:
    """`path` under `root`, as the path it had under /."""
    return Path("/") / path.relative_to(root)


def _undeclared(
    path: Path, st: os.stat_result, device: int, root: Path
) -> Finding | None:
    """`path` as the audit would report it if undeclared, or None if the
    audit skips it (a symlink NixOS recreates, an empty directory)."""
    if stat.S_ISLNK(st.st_mode):
        if audit.is_managed_symlink(path, root):
            return None
        return Finding(path, "symlink", Usage(0, 1, st.st_mtime))
    if not stat.S_ISDIR(st.st_mode):
        return Finding(path, "file", Usage(st.st_size, 1, st.st_mtime))
    usage = audit.measure(path, device, root)
    return Finding(path, "dir", usage) if usage.files else None


def old_roots(top: Path) -> list[OldRoot]:
    """The kept old roots in the btrfs top level `top`, oldest first."""
    directory = top / OLD_ROOTS
    numbers = sorted(
        int(entry.name)
        for entry in audit._children(directory)
        if entry.name.isdigit() and entry.is_dir()
    )
    return [
        OldRoot(
            number=n,
            info=read_info(directory / f"{n}.info"),
            exclusive_bytes=exclusive_bytes(directory / str(n)),
        )
        for n in numbers
    ]


def exclusive_bytes(path: Path) -> int | None:
    """Bytes only `path` holds (freed if it's deleted), or None when btrfs
    can't tell (e.g. not on btrfs)."""
    try:
        result = subprocess.run(
            ["btrfs", "filesystem", "du", "-s", "--raw", str(path)],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    # Columns: Total, Exclusive, Set shared, Filename.
    fields = result.stdout.strip().splitlines()[-1].split()
    return int(fields[1]) if len(fields) >= 4 and fields[1].isdigit() else None


@contextmanager
def mounted_top_level(device: str, mountpoint: Path) -> Iterator[Path]:
    """Mount `device`'s btrfs top level read-only on `mountpoint`."""
    mountpoint.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["mount", "-t", "btrfs", "-o", "ro,subvolid=5", device, str(mountpoint)],
        check=True,
    )
    try:
        yield mountpoint
    finally:
        subprocess.run(["umount", str(mountpoint)], check=False)


def build_report(
    top: Path,
    new_root: Path,
    declared: Mapping[Path, Declaration],
    info: Mapping[str, str],
    boot_id: str,
    cmdline: str,
) -> tuple[str, dict[str, object]]:
    """The report as text and as JSON."""
    errors: list[str] = []
    comparison: Comparison | None = None
    old_root = info.get("old_root", "")

    if info.get("boot_id") != boot_id:
        if keep_root_requested(cmdline):
            status = f"skipped: {KEEP_ROOT_PARAM} is on the kernel command line"
        else:
            status = "did not run (no record from the initrd for this boot)"
            errors.append(f"The root reset {status}.")
    elif info.get("result") != "reset":
        status = "failed; the previous root was kept as it was"
        errors.append(f"The root reset {status}. See initrd.log.")
    elif not old_root.isdigit() or not (top / OLD_ROOTS / old_root).is_dir():
        status = "reset, but the old root wasn't kept"
        errors.append(f"The root was reset, but {OLD_ROOTS}/{old_root} is missing.")
    else:
        status = f"reset; the previous root is {OLD_ROOTS}/{old_root}"
        comparison = compare(top / OLD_ROOTS / old_root, new_root, declared)
        if comparison.errors:
            errors.append(
                "Declared paths missing from the new root (a root-reset bug; "
                f"recover them from {OLD_ROOTS}/{old_root}):\n"
                + "\n".join(f"  {p}" for p in comparison.errors)
            )

    retained = old_roots(top)
    lines = [f"ERROR: {e}" for e in errors]
    lines.append(f"Root reset, boot {boot_id}: {status}")
    if comparison is not None:
        matched = not comparison.recreated and not comparison.unpredicted
        lines += [
            f"Audit predicted {len(comparison.predicted)} undeclared paths; "
            f"{len(comparison.lost)} were deleted. "
            f"Prediction matched: {'yes' if matched else 'no'}.",
            *_section(
                "Deleted, undeclared:",
                [
                    f"{f.path}  ({f.usage.files} files, {f.usage.bytes / 1e6:.1f} MB)"
                    for f in comparison.lost
                ],
            ),
            *_section(
                "Predicted, but there again (recreated since boot):",
                comparison.recreated,
            ),
            *_section("Deleted, but not predicted:", comparison.unpredicted),
            *_section("Deleted, declared ephemeral:", comparison.deleted),
        ]
    lines.append("Old roots kept (oldest first):")
    lines += [
        f"  {OLD_ROOTS}/{r.number}  {_size(r.exclusive_bytes)} of its own; "
        f"{r.info.get('why', '?')} (clock then: {r.info.get('clock', '?')})"
        for r in retained
    ]

    report: dict[str, object] = {
        "generated": round(time.time(), 1),
        "boot_id": boot_id,
        "status": status,
        "errors": errors,
        "old_root": int(old_root) if comparison is not None else None,
        "retained": [
            {"number": r.number, "exclusive_bytes": r.exclusive_bytes, **r.info}
            for r in retained
        ],
    }
    if comparison is not None:
        report |= {
            "predicted": [str(p) for p in comparison.predicted],
            "lost": [f.to_json() for f in comparison.lost],
            "recreated": [str(p) for p in comparison.recreated],
            "unpredicted": [str(p) for p in comparison.unpredicted],
            "deleted_ephemeral": [str(p) for p in comparison.deleted],
            "missing_declared": [str(p) for p in comparison.errors],
        }
    return "\n".join(lines) + "\n", report


def _section(title: str, items: Sequence[object]) -> list[str]:
    return [title, *(f"  {item}" for item in items)] if items else []


def _size(n: int | None) -> str:
    if n is None:
        return "size unknown"
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("declared", type=Path, help="declarations JSON from Nix")
    parser.add_argument(
        "report_dir", type=Path, help="where the initrd left its info; output too"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--device", help="btrfs device to mount the top level of")
    source.add_argument("--top", type=Path, help="an already mounted top level")
    parser.add_argument(
        "--mountpoint",
        type=Path,
        default=Path("/run/root-reset-report"),
        help="where to mount --device",
    )
    parser.add_argument(
        "--new-root", type=Path, default=Path("/"), help="the root that booted"
    )
    args = parser.parse_args(argv)

    declared = audit.load_declared(args.declared)
    info = read_info(args.report_dir / "info")
    boot_id = BOOT_ID_FILE.read_text().strip()
    cmdline = CMDLINE_FILE.read_text()

    def run(top: Path) -> tuple[str, dict[str, object]]:
        return build_report(top, args.new_root, declared, info, boot_id, cmdline)

    if args.top is not None:
        text, report = run(args.top)
    else:
        with mounted_top_level(args.device, args.mountpoint) as top:
            text, report = run(top)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    audit.write_atomic(args.report_dir / "report.json", json.dumps(report, indent=1))
    audit.write_atomic(args.report_dir / "report.txt", text)
    print(text, end="")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
