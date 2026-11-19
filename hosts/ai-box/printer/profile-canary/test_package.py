"""Tests for package.py."""

from __future__ import annotations

import zipfile
from pathlib import Path

import package
import pytest
from conftest import profiles_tree


def zip_of(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return path


def test_download_and_unpack(tmp_path: Path) -> None:
    src = zip_of(
        tmp_path / "src.zip",
        {"BBL.json": '{"version": "02.08.00.06"}', "BBL/a.json": "{}"},
    )
    package.download(src.as_uri(), tmp_path / "got.zip")
    raw = package.unpack(tmp_path / "got.zip", tmp_path / "raw")
    assert package.version_of(raw) == "02.08.00.06"
    assert (raw / "BBL" / "a.json").is_file()


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"../evil.json": "{}"}, "leaves the package"),
        ({"other/BBL.json": "{}"}, "no BBL.json and BBL/"),
    ],
)
def test_unpack_fails_loudly(
    tmp_path: Path, members: dict[str, str], message: str
) -> None:
    with pytest.raises(package.PackageError, match=message):
        package.unpack(zip_of(tmp_path / "p.zip", members), tmp_path / "raw")


def test_a_failed_download_is_a_package_error(tmp_path: Path) -> None:
    with pytest.raises(package.PackageError, match="downloading"):
        package.download((tmp_path / "missing.zip").as_uri(), tmp_path / "got.zip")


def test_premerge_runs_the_script_with_the_services_inputs(tmp_path: Path) -> None:
    script = tmp_path / "premerge.py"
    # records its arguments where --out points
    script.write_text(
        "import json, sys, pathlib\n"
        "a = sys.argv[1:]\n"
        "out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir()\n"
        "(out / 'args.json').write_text(json.dumps(a))\n"
    )
    tools = package.Premerge(
        script, tmp_path / "d.json", tmp_path / "P.cpp", tmp_path / "PC.cpp"
    )
    raw = profiles_tree(tmp_path / "raw", "02.08.00.06")
    out = package.premerge(raw, "02.08.00.06", tools, tmp_path / "merged")
    args = (out / "args.json").read_text()
    assert '"--expect-version", "02.08.00.06"' in args
    assert str(tmp_path / "d.json") in args


def test_a_failing_premerge_is_a_package_error(tmp_path: Path) -> None:
    script = tmp_path / "premerge.py"
    script.write_text("import sys; sys.exit('BBL.json is version 1, not 2')")
    tools = package.Premerge(script, tmp_path, tmp_path, tmp_path)
    with pytest.raises(package.PackageError, match="not 2"):
        package.premerge(tmp_path, "2", tools, tmp_path / "out")


def test_version_of_a_tree_without_bbl_json(tmp_path: Path) -> None:
    with pytest.raises(package.PackageError):
        package.version_of(tmp_path)
