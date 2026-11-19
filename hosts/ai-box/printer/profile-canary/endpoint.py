"""Which BBL profile package Bambu offers a Bambu Studio version: the question the app asks.

Bambu Studio 02.08.00.50 (PresetUpdater::priv::sync_config and sync_resources in
src/slic3r/Utils/PresetUpdater.cpp, the URL from GUI_App::get_http_url) asks
  GET https://api.bambulab.com/v1/iot-service/api/slicer/resource?slicer/settings/bbl=<version>
with its own version's last two parts zeroed (02.08.00.50 asks for 02.08.00.00). The answer's
`resources` list names the package's version and the zip's URL. The app takes it only if it has
its own major.minor and is newer than the profiles it holds.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

URL = "https://api.bambulab.com/v1/iot-service/api/slicer/resource"
# Who asks: the canary, honestly (the endpoint refuses Python's default user agent).
USER_AGENT = "ai-box-profile-canary/1 (+https://github.com/apockill/nix-config)"
RESOURCE = "slicer/settings/bbl"
# The endpoint answers in well under a second; a minute means it's down.
TIMEOUT_S = 60


class EndpointError(Exception):
    pass


@dataclass(frozen=True, order=True)
class Version:
    """A Bambu version, four two-digit parts: 02.08.00.06."""

    parts: tuple[int, int, int, int]

    @classmethod
    def parse(cls, text: str) -> Version:
        try:
            a, b, c, d = (int(p) for p in text.strip().split("."))
        except ValueError as e:
            raise EndpointError(f"not a Bambu version: {text!r}") from e
        return cls((a, b, c, d))

    def __str__(self) -> str:
        return ".".join(f"{p:02d}" for p in self.parts)


@dataclass(frozen=True)
class Offer:
    version: Version
    url: str


def query(app: Version) -> str:
    """The query string the app sends: its major.minor, the rest zeroed."""
    a, b, _, _ = app.parts
    return f"{RESOURCE}={Version((a, b, 0, 0))}"


def parse(body: str) -> Offer | None:
    """The BBL package the endpoint's answer offers, or None if it offers none."""
    try:
        answer = json.loads(body)
    except json.JSONDecodeError as e:
        raise EndpointError(f"the endpoint's answer isn't JSON: {body[:200]!r}") from e
    if not isinstance(answer, dict) or answer.get("message") != "success":
        raise EndpointError(f"the endpoint didn't answer success: {body[:200]!r}")
    for r in answer.get("resources") or []:
        if isinstance(r, dict) and str(r.get("type", "")).lower() == RESOURCE:
            return Offer(Version.parse(str(r["version"])), str(r["url"]))
    return None


def ask(app: Version, url: str = URL) -> Offer | None:
    request = urllib.request.Request(
        f"{url}?{query(app)}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as r:
            return parse(r.read().decode())
    except OSError as e:
        raise EndpointError(f"asking {url}: {e}") from e


def installs(app: Version, held: Version, offered: Version) -> bool:
    """Whether the app, holding `held`, would install `offered` (sync_resources' version check)."""
    return offered.parts[:2] == app.parts[:2] and offered > held
