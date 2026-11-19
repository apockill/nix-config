"""Tests for endpoint.py."""

from __future__ import annotations

import json

import endpoint
import pytest
from endpoint import Version

ANSWER = {
    "message": "success",
    "software": {"version": "02.09.01.70"},
    "resources": [
        {
            "type": "slicer/settings/bbl",
            "version": "02.08.00.06",
            "url": "https://example.invalid/02.08.00.06.zip",
        }
    ],
}


def test_the_query_is_the_apps_major_minor() -> None:
    assert (
        endpoint.query(Version.parse("02.08.00.50"))
        == "slicer/settings/bbl=02.08.00.00"
    )


def test_parse_finds_the_bbl_package() -> None:
    offer = endpoint.parse(json.dumps(ANSWER))
    assert offer == endpoint.Offer(
        Version.parse("02.08.00.06"), "https://example.invalid/02.08.00.06.zip"
    )
    assert str(offer.version) == "02.08.00.06"


def test_parse_without_a_bbl_package() -> None:
    assert endpoint.parse(json.dumps({**ANSWER, "resources": []})) is None


@pytest.mark.parametrize("body", ["not json", json.dumps({"message": "fail"})])
def test_parse_fails_loudly(body: str) -> None:
    with pytest.raises(endpoint.EndpointError):
        endpoint.parse(body)


@pytest.mark.parametrize(
    ("held", "offered", "installs"),
    [
        ("02.08.00.01", "02.08.00.06", True),
        ("02.08.00.06", "02.08.00.06", False),
        ("02.08.00.09", "02.08.00.06", False),
        ("02.08.00.06", "02.09.00.01", False),  # another major.minor: not for this app
    ],
)
def test_installs_follows_the_apps_rule(
    held: str, offered: str, installs: bool
) -> None:
    app = Version.parse("02.08.00.50")
    assert (
        endpoint.installs(app, Version.parse(held), Version.parse(offered)) is installs
    )


def test_a_bad_version_fails_loudly() -> None:
    with pytest.raises(endpoint.EndpointError):
        Version.parse("2.8")
