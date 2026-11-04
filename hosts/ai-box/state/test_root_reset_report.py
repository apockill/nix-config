"""Tests for root_reset_report.py. Run with `just test`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import root_reset_report as report
from audit import Backup, Declaration

BOOT_ID = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

DECLARED = {
    Path("/var/lib/kept"): Declaration(backup=Backup.RESTIC, why="t"),
    Path("/var/lib/kept/generated"): Declaration(backup=Backup.EPHEMERAL, why="t"),
    Path("/var/lib/lost-kept"): Declaration(backup=Backup.CACHE, why="t"),
    Path("/etc/passwd"): Declaration(backup=Backup.EPHEMERAL, why="t"),
}


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def top(tmp_path: Path) -> Path:
    """A top level with old root 1, and the new root that booted at
    tmp_path/new."""
    top = tmp_path / "top"
    old, new = top / "@root-old" / "1", tmp_path / "new"
    write(top / "@root-old" / "1.info", "n=1\nwhy=test\n")
    write(old / "var" / "lib" / "kept" / "db")
    write(old / "var" / "lib" / "kept" / "generated")  # ephemeral: deleted
    write(old / "var" / "lib" / "lost-kept" / "file")  # kept, but missing: bug
    write(old / "var" / "lib" / "stray" / "junk")  # undeclared: deleted
    write(old / "var" / "lib" / "recreated" / "x")  # undeclared, but back
    (old / "var" / "lib" / "empty").mkdir()  # the audit skips empty dirs
    write(old / "etc" / "passwd")  # ephemeral, regenerated at boot
    (old / "etc" / "localtime").symlink_to("/etc/zoneinfo/UTC")  # NixOS's
    write(new / "var" / "lib" / "kept" / "db")
    write(new / "var" / "lib" / "recreated" / "x")
    write(new / "etc" / "passwd")
    return top


def test_compare_sorts_what_the_wipe_deleted(top: Path) -> None:
    result = report.compare(top / "@root-old" / "1", top.parent / "new", DECLARED)

    assert result.predicted == [Path("/var/lib/recreated"), Path("/var/lib/stray")]
    assert [f.path for f in result.lost] == [Path("/var/lib/stray")]
    assert result.lost[0].usage.files == 1
    assert result.recreated == [Path("/var/lib/recreated")]
    assert result.unpredicted == []
    assert result.deleted == [Path("/var/lib/kept/generated")]
    assert result.errors == [Path("/var/lib/lost-kept")]


def test_main_writes_the_report_with_errors_first(
    top: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "exclusive_bytes", lambda _: 2_500_000_000)
    out = tmp_path / "out"
    declared = tmp_path / "declared.json"
    declared.write_text(
        json.dumps(
            {str(p): {"backup": d.backup, "why": d.why} for p, d in DECLARED.items()}
        )
    )
    write(out / "info", f"result=reset\nold_root=1\nboot_id={BOOT_ID}\nclock=x\n")

    code = report.main(
        [
            str(declared),
            str(out),
            "--top",
            str(top),
            "--new-root",
            str(tmp_path / "new"),
        ]
    )

    assert code == 1
    text = (out / "report.txt").read_text()
    assert text.startswith(
        "ERROR: Declared paths missing from the new root (a root-reset bug; "
        "recover them from @root-old/1):\n  /var/lib/lost-kept\n"
    )
    assert "previous root is @root-old/1" in text
    assert "Prediction matched: no." in text
    assert "@root-old/1  2.5 GB of its own; test (clock then: ?)" in text
    data = json.loads((out / "report.json").read_text())
    assert data["missing_declared"] == ["/var/lib/lost-kept"]
    assert data["lost"][0]["path"] == "/var/lib/stray"
    assert data["recreated"] == ["/var/lib/recreated"]
    assert data["deleted_ephemeral"] == ["/var/lib/kept/generated"]
    assert data["retained"] == [
        {"number": 1, "exclusive_bytes": 2_500_000_000, "n": "1", "why": "test"}
    ]


def test_a_clean_reset_has_no_errors(top: Path, tmp_path: Path) -> None:
    write(tmp_path / "new" / "var" / "lib" / "lost-kept" / "file")
    (tmp_path / "new" / "var" / "lib" / "recreated" / "x").unlink()
    (tmp_path / "new" / "var" / "lib" / "recreated").rmdir()
    info = {"result": "reset", "old_root": "1", "boot_id": BOOT_ID}

    text, data = report.build_report(
        top, tmp_path / "new", DECLARED, info, BOOT_ID, "quiet"
    )

    assert data["errors"] == []
    assert not text.startswith("ERROR")
    assert "Prediction matched: yes." in text


def test_keep_root_skips_without_error(top: Path, tmp_path: Path) -> None:
    stale = {"result": "reset", "old_root": "1", "boot_id": "an earlier boot"}
    text, data = report.build_report(
        top, tmp_path / "new", DECLARED, stale, BOOT_ID, "quiet ai-box.keep-root"
    )
    assert data["errors"] == []
    assert "skipped: ai-box.keep-root is on the kernel command line" in text


@pytest.mark.parametrize(
    ("info", "error"),
    [
        ({"boot_id": "an earlier boot", "result": "reset"}, "did not run"),
        ({"boot_id": BOOT_ID, "result": "failed"}, "failed"),
        ({"boot_id": BOOT_ID, "result": "reset", "old_root": "9"}, "is missing"),
    ],
)
def test_a_reset_that_did_not_happen_is_an_error(
    top: Path, tmp_path: Path, info: dict[str, str], error: str
) -> None:
    text, data = report.build_report(
        top, tmp_path / "new", DECLARED, info, BOOT_ID, "quiet"
    )
    assert text.startswith("ERROR: ")
    assert error in text
    assert "predicted" not in data


def test_keep_root_must_be_a_whole_word() -> None:
    assert report.keep_root_requested("quiet ai-box.keep-root")
    assert report.keep_root_requested("ai-box.keep-root=1 quiet")
    assert not report.keep_root_requested("ai-box.keep-rootfs quiet")
