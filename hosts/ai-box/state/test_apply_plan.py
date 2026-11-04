"""Tests for apply-plan.sh on plain directories. Run with `just test`."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("apply-plan.sh")


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def apply_plan(
    tmp_path: Path, steps: list[str], old: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the script on tmp_path/old (or `old`) into a fresh tmp_path/new,
    with strict mode as writeShellApplication sets it."""
    new = tmp_path / "new"
    new.mkdir()
    plan = write(tmp_path / "plan", "".join(f"{step}\n" for step in steps))
    return subprocess.run(
        ["bash", "-o", "errexit", "-o", "nounset", "-o", "pipefail", str(SCRIPT)]
        + [str(old or tmp_path / "old"), str(new), str(plan)],
        capture_output=True,
        text=True,
    )


def tree(root: Path) -> dict[str, str]:
    """Every entry under `root`: file contents, "dir", "-> target" or
    "unreadable"."""
    entries: dict[str, str] = {}
    for directory, dirs, files in root.walk():
        for name in dirs + files:
            path = directory / name
            key = str(path.relative_to(root))
            if path.is_symlink():
                entries[key] = f"-> {path.readlink()}"
            elif path.is_dir():
                entries[key] = "dir"
            else:
                try:
                    entries[key] = path.read_text()
                except PermissionError:
                    entries[key] = "unreadable"
    return entries


def test_nested_copy_delete_copy(tmp_path: Path) -> None:
    old = tmp_path / "old"
    write(old / "a" / "kept")
    write(old / "a" / "b" / "dropped")
    write(old / "a" / "b" / "c" / "kept-again")
    write(old / "undeclared")

    result = apply_plan(tmp_path, ["copy /a", "delete /a/b", "copy /a/b/c"])

    assert result.returncode == 0, result.stderr
    assert tree(tmp_path / "new") == {
        "a": "dir",
        "a/kept": "x",
        "a/b": "dir",
        "a/b/c": "dir",
        "a/b/c/kept-again": "x",
    }
    assert result.stdout.splitlines() == ["copy /a", "delete /a/b", "copy /a/b/c"]


def test_star_segments_expand_in_old_for_copy_and_new_for_delete(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    for app in ("one", "two", ".hidden"):
        write(old / "sites" / app / "state" / "db")
        write(old / "sites" / app / "code")
    write(old / "home" / "alex" / "cache" / "big")
    write(old / "home" / "alex" / "notes")

    result = apply_plan(
        tmp_path, ["copy /home", "copy /sites/*/state", "delete /home/*/cache"]
    )

    assert result.returncode == 0, result.stderr
    new = tree(tmp_path / "new")
    assert {k for k, v in new.items() if v != "dir"} == {
        "home/alex/notes",
        "sites/one/state/db",
        "sites/two/state/db",
        "sites/.hidden/state/db",
    }


def test_missing_paths_are_skipped_silently(tmp_path: Path) -> None:
    write(tmp_path / "old" / "present")

    result = apply_plan(
        tmp_path, ["copy /absent", "copy /absent/*/x", "delete /gone", "copy /present"]
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "copy /present\n"
    assert tree(tmp_path / "new") == {"present": "x"}


def test_paths_with_spaces(tmp_path: Path) -> None:
    write(tmp_path / "old" / "my dir" / "a file")
    result = apply_plan(tmp_path, ["copy /my dir"])
    assert result.returncode == 0, result.stderr
    assert tree(tmp_path / "new") == {"my dir": "dir", "my dir/a file": "x"}


def test_parent_directories_keep_their_mode_and_times(tmp_path: Path) -> None:
    old = tmp_path / "old"
    state = write(old / "var" / "lib" / "hermes" / ".hermes" / "state.db")
    (old / "var" / "lib").chmod(0o751)
    (old / "var" / "lib" / "hermes").chmod(0o2770)
    state.chmod(0o600)
    os.utime(old / "var" / "lib" / "hermes", (1_000_000_000, 1_000_000_000))

    result = apply_plan(tmp_path, ["copy /var/lib/hermes/.hermes"])

    assert result.returncode == 0, result.stderr
    new = tmp_path / "new"

    def mode(path: Path) -> int:
        return stat.S_IMODE(path.lstat().st_mode)

    assert mode(new / "var" / "lib") == 0o751
    assert mode(new / "var" / "lib" / "hermes") == 0o2770
    assert mode(new / "var" / "lib" / "hermes" / ".hermes" / "state.db") == 0o600
    assert (new / "var" / "lib" / "hermes").stat().st_mtime == 1_000_000_000


def test_symlinks_are_never_followed_out_of_the_tree(tmp_path: Path) -> None:
    old, outside = tmp_path / "old", tmp_path / "outside"
    write(outside / "secret")
    write(outside / "victim")
    write(old / "kept" / "file")
    (old / "kept" / "link").symlink_to(outside)  # inside a copied directory
    (old / "abs").symlink_to(outside)  # a parent of a declared path
    (old / "rel").symlink_to("../outside")
    (old / "declared-link").symlink_to(outside)  # a declared path itself

    result = apply_plan(
        tmp_path,
        [
            "copy /abs/secret",
            "copy /rel/secret",
            "copy /declared-link",
            "copy /kept",
            "delete /kept/link/victim",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert tree(tmp_path / "new") == {
        "declared-link": f"-> {outside}",
        "kept": "dir",
        "kept/file": "x",
        "kept/link": f"-> {outside}",
    }
    assert (outside / "victim").exists()
    assert "skipped /abs/secret: a parent directory is a symlink" in result.stdout
    assert "skipped /kept/link/victim" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read unreadable files")
def test_a_failed_copy_fails_the_run_and_leaves_the_old_root_alone(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    write(old / "first" / "file")
    write(old / "second" / "unreadable").chmod(0)
    write(old / "third" / "file")
    before = tree(old)
    mtimes = {p: p.lstat().st_mtime_ns for p in old.rglob("*")}

    result = apply_plan(tmp_path, ["copy /first", "copy /second", "copy /third"])

    assert result.returncode != 0
    assert "third" not in tree(tmp_path / "new")  # stopped at the failure
    assert tree(old) == before
    assert {p: p.lstat().st_mtime_ns for p in old.rglob("*")} == mtimes


def test_a_bad_plan_line_fails(tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    result = apply_plan(tmp_path, ["move /x"])
    assert result.returncode != 0
    assert "bad plan line" in result.stderr
