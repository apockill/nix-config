"""Tests for audit.py. Run with `just test`."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import audit
import pytest
from audit import Backup, Declaration, Usage


def write(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def decl(backup: Backup = Backup.RESTIC) -> Declaration:
    return Declaration(backup=backup, why="test")


def undeclared(root: Path, declared: dict[Path, Declaration]) -> list[str]:
    return [
        str(f.path.relative_to(root)) for f in audit.find_undeclared(root, declared)
    ]


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
    (tmp_path / "handmade").symlink_to("/home/alex/thing")
    assert undeclared(tmp_path, {}) == ["handmade"]


def test_dynamic_user_state_is_judged_by_its_private_dir(tmp_path: Path) -> None:
    """systemd recreates /var/lib/<name> -> private/<name> for DynamicUser
    services; only the data under /var/lib/private needs a declaration."""
    lib = tmp_path / "var" / "lib"
    write(lib / "private" / "kept" / "state.db")
    write(lib / "private" / "leftover" / "fabric.json")
    (lib / "kept").symlink_to("private/kept")
    (lib / "leftover").symlink_to("private/leftover")
    declared = {tmp_path / "var" / "lib" / "private" / "kept": decl(Backup.CACHE)}
    assert undeclared(tmp_path, declared) == ["var/lib/private/leftover"]


def test_store_links_are_managed_only_in_system_dirs(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "sshd_config").symlink_to("/nix/store/abc-sshd_config")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sh").symlink_to("/nix/store/abc-bash/bin/sh")
    home_bin = tmp_path / "var" / "lib" / "hermes" / ".local" / "bin"
    home_bin.mkdir(parents=True)
    (home_bin / "claude").symlink_to("/nix/store/abc-claude-code/bin/claude")
    assert undeclared(tmp_path, {}) == ["var"]


def test_managed_symlinks_inside_undeclared_dirs_are_not_counted(
    tmp_path: Path,
) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "static-link").symlink_to("/etc/static/foo")
    assert undeclared(tmp_path, {}) == []


def test_nested_declarations_are_excluded_from_the_parents_usage(
    tmp_path: Path,
) -> None:
    write(tmp_path / "home" / "notes", size=10)
    write(tmp_path / "home" / "cache" / "blob", size=100)
    declared = {
        tmp_path / "home": decl(Backup.RESTIC),
        tmp_path / "home" / "cache": decl(Backup.CACHE),
        tmp_path / "missing": decl(Backup.RESTIC),
    }
    usage = audit.declared_usage(declared, tmp_path)
    assert usage[tmp_path / "home"].bytes == 10
    assert usage[tmp_path / "home" / "cache"].bytes == 100
    assert usage[tmp_path / "missing"] == Usage()


def test_summary_is_ok_when_nothing_is_wrong() -> None:
    assert audit.summarize([], {}, {}) == audit.OK_SUMMARY


def test_summary_lists_undeclared_paths_and_large_ephemeral_ones(
    tmp_path: Path,
) -> None:
    write(tmp_path / "stray")
    findings = audit.find_undeclared(tmp_path, {})
    big, small = Path("/var/cache"), Path("/tmp")
    declared = {big: decl(Backup.EPHEMERAL), small: decl(Backup.EPHEMERAL)}
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


def test_sqlite_sidecars_are_covered_by_their_database(tmp_path: Path) -> None:
    write(tmp_path / "app" / "data.db")
    write(tmp_path / "app" / "data.db-wal")
    write(tmp_path / "app" / "other.db-wal")
    declared = {tmp_path / "app" / "data.db": decl()}
    assert undeclared(tmp_path, declared) == ["app/other.db-wal"]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_uncommitted_files_in_git_paths_are_noted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "sites"
    write(repo / "app" / "main.py")
    write(repo / ".gitignore").write_text("*.db\n__pycache__/\n*.log\n")
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    write(repo / "app" / "kept.db")  # ignored, but declared separately
    write(repo / "app" / "kept.db-wal")  # its SQLite sidecar
    write(repo / "app" / "stray.db")  # ignored, undeclared: noted
    write(repo / "app" / "notes.txt")  # untracked: noted
    write(repo / "app" / "__pycache__" / "main.pyc")  # build output: skipped
    write(repo / "app" / "dist" / "index.js")  # build output: skipped
    write(repo / "app" / "app.log")  # runtime file: skipped
    write(repo / "app" / ".runner.pid")  # runtime file: skipped
    # Runtime socket: skipped. Bound by relative path; full tmp paths can
    # exceed the 108-byte AF_UNIX limit.
    monkeypatch.chdir(repo / "app")
    sock = socket.socket(socket.AF_UNIX)
    sock.bind("app.sock")
    declared = {
        repo: Declaration(backup=Backup.GIT, why="t", repo="example"),
        repo / "app" / "kept.db": decl(),
    }

    found = audit.uncommitted_in_git_paths(declared)

    sock.close()
    assert sorted(str(p.relative_to(repo)) for p in found) == [
        "app/notes.txt",
        "app/stray.db",
    ]


def test_uncommitted_note_never_fails_the_check(tmp_path: Path) -> None:
    repo = tmp_path / "root" / "repo"
    write(repo / "untracked")
    git(repo.parent, "init", "-q", str(repo))
    declared_json = tmp_path / "declared.json"
    declared_json.write_text(
        json.dumps({str(repo): {"backup": "git", "why": "t", "repo": "x"}})
    )
    assert (
        audit.main(["--root", str(tmp_path / "root"), "check", str(declared_json)]) == 0
    )


def test_unknown_backup_class_is_rejected(tmp_path: Path) -> None:
    declared_json = tmp_path / "declared.json"
    declared_json.write_text(json.dumps({"/x": {"backup": "nope", "why": "t"}}))
    with pytest.raises(ValueError):
        audit.load_declared(declared_json)


def test_backup_enum_matches_the_nix_classes() -> None:
    nix = (Path(__file__).parent / "default.nix").read_text()
    classes = nix.split("classes = [", 1)[1].split("];", 1)[0].split()
    assert sorted(c.strip('"') for c in classes) == sorted(b.value for b in Backup)


def test_unreadable_directories_are_skipped_not_fatal(tmp_path: Path) -> None:
    locked = tmp_path / "var" / "locked"
    write(locked / "secret")
    write(tmp_path / "var" / "stray")
    declared = {tmp_path / "var" / "kept": decl()}
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running as root; permissions aren't enforced")
        assert "var/stray" in undeclared(tmp_path, declared)
    finally:
        locked.chmod(0o755)


def test_runtime_written_files_in_watched_paths_are_noted(tmp_path: Path) -> None:
    config = tmp_path / ".config"
    write(config / "gh" / "hosts.yml")  # written at runtime: noted
    (config / "git").mkdir(parents=True)
    (config / "git" / "config").symlink_to(
        "/nix/store/abc-hm-git-config"
    )  # home-manager: skipped
    (config / "empty").mkdir()  # nothing written: skipped
    write(tmp_path / "other" / "file")  # not watched: skipped
    declared = {
        config: Declaration(backup=Backup.EPHEMERAL, why="t", watch=True),
        tmp_path / "other": decl(Backup.EPHEMERAL),
    }

    written = audit.runtime_written(declared)

    assert list(written) == [config / "gh"]
    assert written[config / "gh"] == (config / "gh" / "hosts.yml").stat().st_mtime


def test_watch_flag_is_loaded_from_the_nix_json(tmp_path: Path) -> None:
    declared_json = tmp_path / "declared.json"
    declared_json.write_text(
        json.dumps(
            {
                "/a": {"backup": "ephemeral", "why": "t", "watch": True},
                "/b": {"backup": "cache", "why": "t"},
            }
        )
    )
    declared = audit.load_declared(declared_json)
    assert declared[Path("/a")].watch and not declared[Path("/b")].watch


def test_pattern_segment_covers_any_one_name(tmp_path: Path) -> None:
    write(tmp_path / "sites" / "a" / "state" / "db.sqlite")
    write(tmp_path / "sites" / ".hidden" / "state" / "f")
    write(tmp_path / "sites" / "b" / "other")  # not the declared segment
    write(tmp_path / "sites" / "b" / "deep" / "state" / "f")  # one level too deep
    declared = {tmp_path / "sites" / "*" / "state": decl()}
    assert undeclared(tmp_path, declared) == ["sites/b/deep", "sites/b/other"]


def test_sqlite_sidecars_are_covered_under_a_pattern(tmp_path: Path) -> None:
    write(tmp_path / "apps" / "a" / "data.db-wal")
    write(tmp_path / "apps" / "a" / "other.db-wal")
    declared = {tmp_path / "apps" / "*" / "data.db": decl()}
    assert undeclared(tmp_path, declared) == ["apps/a/other.db-wal"]


def test_descendants_are_found_through_a_pattern(tmp_path: Path) -> None:
    declared = {tmp_path / "sites" / "*" / "state": decl()}
    assert audit.has_declared_descendant(tmp_path / "sites" / "a", declared)
    assert audit.has_declared_descendant(tmp_path / "sites", declared)
    assert not audit.has_declared_descendant(
        tmp_path / "sites" / "a" / "state", declared
    )
    assert not audit.has_declared_descendant(tmp_path / "other" / "a", declared)


def test_exact_declarations_dont_match_as_patterns(tmp_path: Path) -> None:
    declared = {tmp_path / "a" / "b": decl()}
    assert audit.is_covered(tmp_path / "a" / "b" / "c", declared)
    assert not audit.is_covered(tmp_path / "a" / "x", declared)
    assert not audit.is_covered(tmp_path / "a", declared)


def test_pattern_usage_sums_its_matches(tmp_path: Path) -> None:
    write(tmp_path / "sites" / "a" / "state" / "f", size=3)
    write(tmp_path / "sites" / "b" / "state" / "f", size=4)
    write(tmp_path / "sites" / "b" / "state" / "cache" / "f", size=100)
    write(tmp_path / "sites" / "c" / "code", size=1000)  # no state dir
    pattern = tmp_path / "sites" / "*" / "state"
    cache = tmp_path / "sites" / "b" / "state" / "cache"
    usage = audit.declared_usage({pattern: decl(), cache: decl(Backup.CACHE)}, tmp_path)
    assert usage[pattern].bytes == 7
    assert usage[cache].bytes == 100
    assert audit.expand(tmp_path / "nothing" / "*") == []


def test_declarations_under_a_pattern_count_inside_git_repos(tmp_path: Path) -> None:
    repo = tmp_path / "sites"
    write(repo / "app" / "main.py")
    write(repo / ".gitignore").write_text("state/\n")
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    write(repo / "app" / "state" / "db")  # ignored, declared by the pattern
    write(repo / "app" / "notes.txt")  # untracked: noted
    declared = {
        repo: Declaration(backup=Backup.GIT, why="t", repo="example"),
        repo / "*" / "state": decl(),
    }
    found = audit.uncommitted_in_git_paths(declared)
    assert [str(p.relative_to(repo)) for p in found] == ["app/notes.txt"]
