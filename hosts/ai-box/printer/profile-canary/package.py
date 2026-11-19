"""A BBL profile package from Bambu's CDN: downloaded, unpacked and pre-merged.

The zip's top level is BBL.json and BBL/, the layout of the profiles the app bundles. It's
pre-merged with the slicer service's own premerge.py and the defaults of the bambu-studio it
runs, so a slice with it differs from ours only in the profiles.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import endpoint

# The zip is about 2.4 MB; ten minutes means the CDN is stuck.
DOWNLOAD_TIMEOUT_S = 10 * 60
# premerge.py takes a few seconds on the full tree.
PREMERGE_TIMEOUT_S = 5 * 60


class PackageError(Exception):
    pass


@dataclass(frozen=True)
class Premerge:
    """premerge.py and the inputs it takes besides the profiles: the slicer service's."""

    script: Path
    defaults: Path
    preset_cpp: Path
    print_config_cpp: Path


def download(url: str, to: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": endpoint.USER_AGENT})
    try:
        with (
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as r,
            to.open("wb") as f,
        ):
            shutil.copyfileobj(r, f)
    except OSError as e:
        raise PackageError(f"downloading {url}: {e}") from e


def unpack(zip_path: Path, to: Path) -> Path:
    """Unpack the package into `to`; return it (the dir holding BBL.json and BBL/)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                # ZipFile.extract keeps every member inside `to`, but say so loudly instead.
                if name.startswith("/") or ".." in Path(name).parts:
                    raise PackageError(
                        f"{zip_path}: member {name!r} leaves the package"
                    )
            z.extractall(to)
    except zipfile.BadZipFile as e:
        raise PackageError(f"{zip_path}: {e}") from e
    if not (to / "BBL.json").is_file() or not (to / "BBL").is_dir():
        raise PackageError(f"{zip_path}: no BBL.json and BBL/ at its top level")
    return to


def version_of(profiles: Path) -> str:
    """The BBL.json version of a profiles dir (raw or pre-merged)."""
    try:
        return str(json.loads((profiles / "BBL.json").read_text())["version"])
    except (OSError, ValueError, KeyError) as e:
        raise PackageError(f"{profiles}: no BBL.json version: {e}") from e


def premerge(raw: Path, version: str, tools: Premerge, out: Path) -> Path:
    """Pre-merge the raw package into `out` as the slicer service's tree is; return `out`."""
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(tools.script),
                "--profiles",
                str(raw),
                "--expect-version",
                version,
                "--defaults",
                str(tools.defaults),
                "--preset-cpp",
                str(tools.preset_cpp),
                "--print-config-cpp",
                str(tools.print_config_cpp),
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=PREMERGE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        raise PackageError(f"premerge.py took over {PREMERGE_TIMEOUT_S} s") from e
    if run.returncode != 0:
        raise PackageError(f"premerge.py failed: {run.stderr.strip()[-500:]}")
    return out
