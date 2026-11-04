"""Tests for root-reset.sh on plain directories, with stand-ins for mount and
btrfs. Run with `just test`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
BOOT_ID = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

# A stand-in for the btrfs CLI, enough for root-reset.sh. Subvolumes are
# directories whose inode is in $FAKE_BTRFS_STATE, so they keep being
# subvolumes when renamed. Like btrfs, it refuses to delete a subvolume that
# still has subvolumes inside.
FAKE_BTRFS = """
import json, os, shutil, sys
from pathlib import Path

state = Path(os.environ["FAKE_BTRFS_STATE"])
top = Path(os.environ["FAKE_BTRFS_TOP"])
inodes = set(json.loads(state.read_text()))

def subvolumes():
    found = [top] if top.stat().st_ino in inodes else []
    for directory, dirs, _ in top.walk():
        found += [directory / d for d in dirs if (directory / d).stat().st_ino in inodes]
    return found

def parent_subvolume(path):
    return next((p for p in path.parents if p in subvolumes()), None)

match sys.argv[1:]:
    case ["subvolume", "create", path]:
        Path(path).mkdir()
        inodes.add(Path(path).stat().st_ino)
    case ["subvolume", "delete", path]:
        path = Path(path)
        if path.stat().st_ino not in inodes:
            sys.exit(f"not a subvolume: {path}")
        if any(path in s.parents for s in subvolumes()):
            sys.exit(f"has nested subvolumes: {path}")
        inodes.discard(path.stat().st_ino)
        shutil.rmtree(path)
    case ["subvolume", "list", "-o", path]:
        for s in subvolumes():
            if parent_subvolume(s) == Path(path):
                print(f"ID 256 gen 1 top level 5 path {s.relative_to(top)}")
    case ["filesystem", "sync", _]:
        pass
    case _:
        sys.exit(f"fake btrfs: unexpected {sys.argv[1:]}")
state.write_text(json.dumps(sorted(inodes)))
"""


class Box:
    """A btrfs top level as plain directories, and a way to run the reset."""

    def __init__(self, tmp_path: Path) -> None:
        self.top = tmp_path / "top"
        self.root = self.top / "@root"
        self.old_roots = self.top / "@root-old"
        self.bin = tmp_path / "bin"
        self.state = tmp_path / "subvolumes.json"
        self.mounts = tmp_path / "mounts"
        self.plan = tmp_path / "plan"
        self.tmp = tmp_path / "tmp"
        for d in (self.root, self.bin, self.tmp):
            d.mkdir(parents=True)
        self.state.write_text("[]")
        self.subvolume(self.root)
        strict = "bash -o errexit -o nounset -o pipefail"
        self.tool("btrfs", f"exec {sys.executable} -c '{FAKE_BTRFS}' \"$@\"")
        self.tool("mount", f'echo "$*" >> {self.mounts}')
        self.tool("umount", "true")
        self.tool(
            "root-reset-apply-plan", f'exec {strict} {HERE / "apply-plan.sh"} "$@"'
        )

    def tool(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def subvolume(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        inodes = json.loads(self.state.read_text())
        self.state.write_text(json.dumps(inodes + [path.stat().st_ino]))

    def old_root(self, n: int) -> Path:
        path = self.old_roots / str(n)
        self.subvolume(path)
        (self.old_roots / f"{n}.info").write_text(f"n={n}\n")
        return path

    def reset(self, steps: list[str]) -> subprocess.CompletedProcess[str]:
        self.plan.write_text("".join(f"{step}\n" for step in steps))
        env = os.environ | {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TMPDIR": str(self.tmp),
            "FAKE_BTRFS_STATE": str(self.state),
            "FAKE_BTRFS_TOP": str(self.top),
        }
        return subprocess.run(
            ["bash", "-o", "errexit", "-o", "nounset", "-o", "pipefail"]
            + [str(HERE / "root-reset.sh"), "/dev/fake", str(self.top), str(self.plan)],
            capture_output=True,
            text=True,
            env=env,
        )

    def numbers(self) -> list[int]:
        return sorted(int(p.name) for p in self.old_roots.iterdir() if p.is_dir())

    def report(self, root: Path | None = None) -> dict[str, str]:
        info = (root or self.root) / "var" / "lib" / "root-reset" / "info"
        return dict(line.split("=", 1) for line in info.read_text().splitlines())


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def snapshot(root: Path) -> dict[Path, tuple[int, int, int]]:
    """Inode, mode and mtime of everything under `root`."""
    return {
        p: (s.st_ino, s.st_mode, s.st_mtime_ns)
        for p in root.rglob("*")
        if (s := p.lstat())
    }


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def test_reset_keeps_declared_state_and_the_old_root(box: Box) -> None:
    write(box.root / "var" / "lib" / "kept" / "db")
    write(box.root / "var" / "lib" / "kept" / "generated")
    write(box.root / "var" / "lib" / "stray" / "junk")

    result = box.reset(["copy /var/lib/kept", "delete /var/lib/kept/generated"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        box.mounts.read_text()
        == "-t btrfs -o subvolid=5 /dev/fake " + str(box.top) + "\n"
    )
    assert files(box.root) == {
        "var/lib/kept/db",
        "var/lib/root-reset/initrd.log",
        "var/lib/root-reset/info",
    }
    assert files(box.old_roots / "1") == {
        "var/lib/kept/db",
        "var/lib/kept/generated",
        "var/lib/stray/junk",
    }
    assert not (box.top / "@root-new").exists()
    assert box.report() == {
        "result": "reset",
        "old_root": "1",
        "boot_id": BOOT_ID,
        "clock": box.report()["clock"],
    }
    info = (box.old_roots / "1.info").read_text()
    assert "n=1\n" in info and f"boot_id={BOOT_ID}\n" in info
    log = (box.root / "var" / "lib" / "root-reset" / "initrd.log").read_text()
    assert "copy /var/lib/kept\ndelete /var/lib/kept/generated\n" in log
    assert "kept @root-new as @root-old/1" in log
    # The new root is a subvolume; the old one still is, under its new name.
    assert box.root.stat().st_ino in json.loads(box.state.read_text())


def test_old_roots_are_numbered_past_the_highest(box: Box) -> None:
    box.old_root(3)
    box.old_root(10)  # numerically highest, not lexically
    result = box.reset([])
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.numbers() == [3, 10, 11]
    assert box.report()["old_root"] == "11"


def test_only_the_newest_five_old_roots_are_kept(box: Box) -> None:
    for n in range(1, 7):
        box.old_root(n)
    box.subvolume(box.old_roots / "1" / "var" / "lib" / "machines")
    box.subvolume(box.old_roots / "1" / "var" / "lib" / "machines" / "deeper")

    result = box.reset([])

    assert result.returncode == 0, result.stdout + result.stderr
    assert box.numbers() == [3, 4, 5, 6, 7]
    assert sorted(p.name for p in box.old_roots.glob("*.info")) == [
        f"{n}.info" for n in (3, 4, 5, 6, 7)
    ]
    assert "deleted @root-old/1 (keeping the newest 5)" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read unreadable files")
def test_a_failed_build_leaves_the_root_untouched(box: Box) -> None:
    write(box.root / "var" / "lib" / "kept" / "db")
    write(box.root / "var" / "lib" / "kept" / "locked").chmod(0)
    write(box.root / "stray")
    before = snapshot(box.root)

    result = box.reset(["copy /var/lib/kept"])

    assert result.returncode == 1
    assert "ERROR: building the new root failed" in result.stdout
    assert not (box.top / "@root-new").exists()
    assert box.numbers() == []
    # Only the report was added (which changed /var/lib's mtime).
    after = snapshot(box.root)
    report_dir = box.root / "var" / "lib" / "root-reset"
    assert set(after) - set(before) == {
        report_dir,
        report_dir / "initrd.log",
        report_dir / "info",
    }
    unchanged = set(before) - {box.root / "var" / "lib"}
    assert {p: after[p] for p in unchanged} == {p: before[p] for p in unchanged}
    assert box.report() == {
        "result": "failed",
        "old_root": "",
        "boot_id": BOOT_ID,
        "clock": box.report()["clock"],
    }


def test_a_root_new_left_by_an_interrupted_reset_is_kept(box: Box) -> None:
    box.subvolume(box.top / "@root-new")
    write(box.top / "@root-new" / "half-built")

    result = box.reset([])

    assert result.returncode == 0, result.stdout + result.stderr
    assert box.numbers() == [1, 2]
    assert files(box.old_roots / "1") == {"half-built"}
    assert (
        "why=@root-new left by an interrupted reset"
        in (box.old_roots / "1.info").read_text()
    )
    assert box.report()["old_root"] == "2"
