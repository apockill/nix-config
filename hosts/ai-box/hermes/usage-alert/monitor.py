"""Cron gate for usage-alert (see ./default.nix): is a disk or the memory over 95% used?

Prints `OK` while everything is under the line, otherwise `OVER <resource>...` naming
what is full, e.g. `OVER disk:/ memory`. A disk is named by its shortest mount point: on
ai-box `disk:/` is the one btrfs filesystem behind /, /nix, /persist and /home. The
output carries no percentages, so Hermes's monitor mode runs the agent only when a
resource crosses the line, not while usage drifts with a resource still full.

A resource goes over above ALERT_PERCENT and comes back only at or under CLEAR_PERCENT,
so one hovering at the line alerts once instead of on every tick. To know which side of
that band a resource is on, the script keeps the set it last reported as over in a small
state file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Over this share used, a resource is full (Alex: "if we reach over 95%").
ALERT_PERCENT = 95.0
# A full resource is back to normal only at or under this share, so usage wobbling
# around ALERT_PERCENT (memory moves by gigabytes as models load) gives one alert, not
# one per tick. 2 points is about 20 GB of ai-box's disk and 1.3 GB of its memory.
CLEAR_PERCENT = 93.0
# Filesystem types that store data on a disk. The rest of the mount table is RAM (tmpfs,
# whose use already shows in MemAvailable) or virtual (proc, sysfs, cgroup) and is
# skipped. squashfs and ISO images are read-only and always 100% used, so they aren't
# listed either.
DISK_FILESYSTEMS = frozenset(
    {"btrfs", "ext2", "ext3", "ext4", "exfat", "f2fs", "vfat", "xfs"}
)
# Which resources were over at the last tick. ~/.hermes/cache is kept across reboots
# (hosts/ai-box/state/paths.nix), so a reboot mid-alert doesn't re-alert.
DEFAULT_STATE = Path("/var/lib/hermes/.hermes/cache/usage-alert-over.json")
# The mount table escapes space, tab, newline and backslash in mount points as octal
# (`\040`).
MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


@dataclass(frozen=True)
class Usage:
    """How full one resource is."""

    name: str  # `disk:<mount point>` or `memory`
    percent: float


def parse_mounts(text: str) -> list[list[Path]]:
    """The mount points of each disk filesystem in a mount table, shortest first.

    A device shows up many times (btrfs subvolumes and impermanence's bind mounts all
    come from /dev/nvme0n1p2) and is just as full at each of them, so its mounts are
    grouped: e.g. `[[/, /nix, /persist, ...], [/boot]]`.
    """
    by_device: dict[str, list[Path]] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[2] not in DISK_FILESYSTEMS:
            continue
        point = MOUNT_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), fields[1])
        by_device.setdefault(fields[0], []).append(Path(point))
    return [
        sorted(points, key=lambda p: (len(str(p)), str(p)))
        for points in by_device.values()
    ]


def disk_percent(mount: Path) -> float:
    """The share of the filesystem at `mount` in use, as df's Use% computes it.

    Blocks reserved for root don't count as available, so a full disk reads 100% even
    though root could still write a little.
    """
    stat = os.statvfs(mount)
    used = stat.f_blocks - stat.f_bfree
    usable = used + stat.f_bavail
    return 100.0 * used / usable if usable else 0.0


def disk_usage(devices: list[list[Path]]) -> list[Usage]:
    """Measure each device once, at the first of its mount points that can be read."""
    usages = []
    for points in devices:
        for point in points:
            try:
                percent = disk_percent(point)
            except OSError:
                continue  # e.g. a bind mount under /root, which hermes can't enter
            usages.append(Usage(f"disk:{point}", percent))
            break
    return usages


def memory_usage(meminfo: str) -> Usage:
    """The share of RAM in use: all but MemAvailable (free plus reclaimable cache).

    The Jetson's GPU allocates from the same RAM, so models loaded on the GPU count here
    too.
    """
    kilobytes: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, _, value = line.partition(":")
        if value.split():
            kilobytes[key] = int(value.split()[0])
    available = kilobytes["MemAvailable"] / kilobytes["MemTotal"]
    return Usage("memory", 100.0 * (1 - available))


def over(usages: list[Usage], was_over: set[str]) -> set[str]:
    """The resources over now: above ALERT_PERCENT, or above CLEAR_PERCENT if they were
    over last tick."""
    return {
        usage.name
        for usage in usages
        if usage.percent > (CLEAR_PERCENT if usage.name in was_over else ALERT_PERCENT)
    }


def load_state(path: Path) -> set[str]:
    """The resources that were over at the last tick."""
    try:
        names = json.loads(path.read_text())
    except (OSError, ValueError):
        return set()  # first run, or a lost file: start from nothing over
    if not isinstance(names, list):
        return set()
    return {name for name in names if isinstance(name, str)}


def save_state(path: Path, names: set[str]) -> None:
    """Write the over set, replacing the file whole so a crash can't leave half of it.

    The full disk can be the one holding the file, so a failed write is skipped: the
    next tick then compares with the older set, which only loses the band for a
    resource between CLEAR_PERCENT and ALERT_PERCENT.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        partial.write_text(json.dumps(sorted(names)) + "\n")
        partial.replace(path)
    except OSError:
        pass


def gate_line(names: set[str]) -> str:
    """The gate's output: `OK`, or `OVER` and the resources over, sorted."""
    return f"OVER {' '.join(sorted(names))}" if names else "OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print OK, or OVER and what is over 95% used."
    )
    parser.add_argument(
        "--proc",
        type=Path,
        default=Path("/proc"),
        help="where to read self/mounts and meminfo (tests point it at fakes)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help="file remembering which resources were over at the last tick",
    )
    args = parser.parse_args(argv)

    usages = disk_usage(parse_mounts((args.proc / "self" / "mounts").read_text()))
    usages.append(memory_usage((args.proc / "meminfo").read_text()))
    was_over = load_state(args.state)
    now_over = over(usages, was_over)
    if now_over != was_over:
        save_state(args.state, now_over)
    print(gate_line(now_over))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
