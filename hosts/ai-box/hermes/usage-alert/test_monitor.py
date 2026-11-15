"""Tests for monitor.py. Run with `just test`."""

from __future__ import annotations

import os
from pathlib import Path

import monitor
import pytest
from monitor import Usage

# A trimmed copy of ai-box's mount table: one btrfs device behind many subvolumes and
# bind mounts, the EFI partition, and RAM or virtual filesystems that must be skipped.
MOUNTS = """\
/dev/nvme0n1p2 / btrfs rw,relatime,subvol=/@root 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
/dev/nvme0n1p2 /nix btrfs rw,relatime,subvol=/@nix 0 0
tmpfs /run tmpfs rw,nosuid,nodev,mode=755 0 0
/dev/nvme0n1p2 /persist btrfs rw,relatime,subvol=/@persist 0 0
/dev/nvme0n1p2 /root/.cache btrfs rw,relatime,subvol=/@persist/root/.cache 0 0
/dev/nvme0n1p2 /home btrfs rw,relatime,subvol=/@home 0 0
/dev/nvme0n1p1 /boot vfat rw,relatime,fmask=0022,dmask=0022 0 0
tmpfs /dev/shm tmpfs rw,nosuid,nodev 0 0
none /run/keys ramfs rw,nosuid,nodev,relatime,mode=750 0 0
/dev/loop0 /mnt/image squashfs ro,relatime 0 0
"""
MEM_TOTAL_KB = 64_330_756  # ai-box's MemTotal


def fake_proc(tmp_path: Path, memory_percent: float) -> Path:
    """A /proc with ai-box's mount table and a meminfo `memory_percent` used."""
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True, exist_ok=True)
    (proc / "self" / "mounts").write_text(MOUNTS)
    available = round(MEM_TOTAL_KB * (1 - memory_percent / 100))
    (proc / "meminfo").write_text(
        f"MemTotal:       {MEM_TOTAL_KB} kB\n"
        "MemFree:         9038080 kB\n"
        f"MemAvailable:   {available} kB\n"
        "HugePages_Total:       0\n"
    )
    return proc


@pytest.fixture
def disks(monkeypatch: pytest.MonkeyPatch) -> dict[Path, float]:
    """Fake disk usage by mount point, every disk at 50%; unlisted mounts raise."""
    percents = {Path("/"): 50.0, Path("/boot"): 50.0}

    def fake_disk_percent(mount: Path) -> float:
        if mount not in percents:
            raise PermissionError(mount)
        return percents[mount]

    monkeypatch.setattr(monitor, "disk_percent", fake_disk_percent)
    return percents


def run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], memory_percent: float
) -> str:
    proc = fake_proc(tmp_path, memory_percent)
    assert (
        monitor.main(["--proc", str(proc), "--state", str(tmp_path / "over.json")]) == 0
    )
    return capsys.readouterr().out


def test_parse_mounts_groups_each_disk_shortest_first_and_skips_ram() -> None:
    assert monitor.parse_mounts(MOUNTS) == [
        [Path(p) for p in ["/", "/nix", "/home", "/persist", "/root/.cache"]],
        [Path("/boot")],
    ]


def test_parse_mounts_decodes_escaped_mount_points() -> None:
    assert monitor.parse_mounts(r"/dev/sda1 /mnt/my\040disk ext4 rw 0 0") == [
        [Path("/mnt/my disk")]
    ]


def test_memory_usage_is_everything_but_mem_available() -> None:
    meminfo = "MemTotal: 1000 kB\nMemFree: 10 kB\nMemAvailable: 250 kB\n"
    assert monitor.memory_usage(meminfo) == Usage("memory", 75.0)


def test_disk_percent_reads_a_real_filesystem(tmp_path: Path) -> None:
    assert 0.0 <= monitor.disk_percent(tmp_path) <= 100.0


def test_unreachable_mount_point_falls_through_to_the_next() -> None:
    reachable = Path(os.sep)
    devices = [[Path("/no/such/mount/point"), reachable]]
    [usage] = monitor.disk_usage(devices)
    assert usage.name == "disk:/"


def test_alert_and_recovery_print_one_line_per_state_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], disks: dict[Path, float]
) -> None:
    assert run(tmp_path, capsys, memory_percent=50) == "OK\n"

    disks[Path("/")] = 96.0
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/\n"
    disks[Path("/")] = 99.0  # filling further doesn't change the line
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/\n"

    # A second resource going over changes the line, and so does it coming back.
    assert run(tmp_path, capsys, memory_percent=96) == "OVER disk:/ memory\n"
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/\n"

    disks[Path("/")] = 50.0
    assert run(tmp_path, capsys, memory_percent=50) == "OK\n"


def test_a_resource_stays_over_until_it_drops_under_the_clear_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], disks: dict[Path, float]
) -> None:
    disks[Path("/")] = 94.0  # in the band, never over: still OK
    assert run(tmp_path, capsys, memory_percent=50) == "OK\n"
    disks[Path("/")] = 95.5
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/\n"
    disks[Path("/")] = 94.0  # hovering back under 95% doesn't clear it
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/\n"
    disks[Path("/")] = 92.9
    assert run(tmp_path, capsys, memory_percent=50) == "OK\n"


def test_boot_partition_is_its_own_resource(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], disks: dict[Path, float]
) -> None:
    disks[Path("/boot")] = 97.0
    assert run(tmp_path, capsys, memory_percent=50) == "OVER disk:/boot\n"


def test_unreadable_state_counts_as_nothing_over(tmp_path: Path) -> None:
    state = tmp_path / "over.json"
    assert monitor.load_state(state) == set()
    state.write_text("{not json")
    assert monitor.load_state(state) == set()
    state.write_text('{"disk:/": true}')
    assert monitor.load_state(state) == set()


def test_state_round_trips(tmp_path: Path) -> None:
    state = tmp_path / "cache" / "over.json"
    monitor.save_state(state, {"memory", "disk:/"})
    assert monitor.load_state(state) == {"memory", "disk:/"}
    assert [p.name for p in state.parent.iterdir()] == ["over.json"]


def test_failed_state_write_is_skipped(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monitor.save_state(blocker / "over.json", {"disk:/"})  # mkdir fails: no exception


def test_runs_against_this_machine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert monitor.main(["--state", str(tmp_path / "over.json")]) == 0
    line = capsys.readouterr().out
    assert line == "OK\n" or line.startswith("OVER ")
