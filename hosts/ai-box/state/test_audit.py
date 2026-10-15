"""Tests for audit.py. Run with `just test`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import audit
from audit import Declaration, Usage


def write(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def decl(backup: str = "restic") -> Declaration:
    return Declaration(backup=backup, why="test")


def undeclared(root: Path, declared: dict[Path, Declaration]) -> list[str]:
    return [str(f.path.relative_to(root)) for f in audit.find_undeclared(root, declared)]


def test_declared_paths_and_their_contents_are_not_reported(tmp_path: Path) -> None:
    write(tmp_path / "kept" / "deep" / "file")
    write(tmp_path / "kept-file")
    declared = {tmp_path / "kept": decl(), tmp_path / "kept-file": decl()}
    assert undeclared(tmp_path, declared) == []


def test_undeclared_directory_is_reported_once_with_its_usage(tmp_path: Path) -> None:
    write(tmp_path / "junk" / "a", size=3)
    write(tmp_path / "junk" / "sub" / "b", size=4)
    [finding] = audit.find_undeclared(tmp_path, {})
    assert finding.path == tmp_path / "junk"
    assert finding.kind == "dir"
    assert (finding.usage.bytes, finding.usage.files) == (7, 2)


def test_partly_declared_directory_is_judged_child_by_child(tmp_path: Path) -> None:
    write(tmp_path / "var" / "lib" / "kept" / "db")
    write(tmp_path / "var" / "lib" / "stray" / "db")
    write(tmp_path / "var" / "lib" / "stray-file")
    declared = {tmp_path / "var" / "lib" / "kept": decl()}
    assert undeclared(tmp_path, declared) == ["var/lib/stray", "var/lib/stray-file"]


def test_empty_directories_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "empty" / "nested").mkdir(parents=True)
    assert undeclared(tmp_path, {}) == []


def test_managed_symlinks_are_ignored_but_others_are_reported(tmp_path: Path) -> None:
    (tmp_path / "localtime").symlink_to("/etc/zoneinfo/America/Los_Angeles")
    (tmp_path / "run").symlink_to("../run")
    (tmp_path / "config").symlink_to("/nix/store/abc-config")
    (tmp_path / "handmade").symlink_to("/home/alex/thing")
    assert undeclared(tmp_path, {}) == ["handmade"]


def test_managed_symlinks_inside_undeclared_dirs_are_not_counted(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "static-link").symlink_to("/etc/static/foo")
    assert undeclared(tmp_path, {}) == []


def test_nested_declarations_are_excluded_from_the_parents_usage(tmp_path: Path) -> None:
    write(tmp_path / "home" / "notes", size=10)
    write(tmp_path / "home" / "cache" / "blob", size=100)
    declared = {
        tmp_path / "home": decl("restic"),
        tmp_path / "home" / "cache": decl("cache"),
        tmp_path / "missing": decl("restic"),
    }
    usage = audit.declared_usage(declared)
    assert usage[tmp_path / "home"].bytes == 10
    assert usage[tmp_path / "home" / "cache"].bytes == 100
    assert usage[tmp_path / "missing"] == Usage()


def test_summary_is_ok_when_nothing_is_wrong() -> None:
    assert audit.summarize([], {}, {}) == audit.OK_SUMMARY


def test_summary_lists_undeclared_paths_and_large_ephemeral_ones(tmp_path: Path) -> None:
    write(tmp_path / "stray")
    findings = audit.find_undeclared(tmp_path, {})
    big, small = Path("/var/cache"), Path("/tmp")
    declared = {big: decl("ephemeral"), small: decl("ephemeral")}
    usage = {big: Usage(bytes=audit.LARGE_EPHEMERAL_BYTES + 1), small: Usage(bytes=1)}

    summary = audit.summarize(findings, declared, usage)

    assert str(tmp_path / "stray") in summary
    assert "/var/cache" in summary
    assert "/tmp" not in summary


def test_summary_has_no_sizes_so_it_only_changes_when_paths_do(tmp_path: Path) -> None:
    write(tmp_path / "stray" / "f", size=1)
    first = audit.summarize(audit.find_undeclared(tmp_path, {}), {}, {})
    write(tmp_path / "stray" / "g", size=5000)
    assert audit.summarize(audit.find_undeclared(tmp_path, {}), {}, {}) == first


@pytest.fixture
def declared_json(tmp_path: Path) -> Path:
    path = tmp_path / "declared.json"
    path.write_text(
        json.dumps({str(tmp_path / "root" / "kept"): {"backup": "cache", "why": "t"}})
    )
    return path


def test_check_exits_1_only_when_something_is_undeclared(
    tmp_path: Path, declared_json: Path
) -> None:
    root = tmp_path / "root"
    write(root / "kept" / "f")
    assert audit.main(["--root", str(root), "check", str(declared_json)]) == 0
    write(root / "stray")
    assert audit.main(["--root", str(root), "check", str(declared_json)]) == 1


def test_report_writes_report_and_summary(tmp_path: Path, declared_json: Path) -> None:
    root, out = tmp_path / "root", tmp_path / "out"
    write(root / "kept" / "f", size=7)
    write(root / "stray")
    out.mkdir()

    audit.main(["--root", str(root), "report", str(declared_json), str(out)])

    report = json.loads((out / "report.json").read_text())
    assert [u["path"] for u in report["undeclared"]] == [str(root / "stray")]
    assert report["declared"][0]["bytes"] == 7
    assert (out / "summary.txt").read_text().startswith("UNDECLARED STATE")
