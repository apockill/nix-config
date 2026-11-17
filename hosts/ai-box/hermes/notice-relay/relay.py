"""Delivers the lab apps' notices to people on Discord: Hermes's side of each app's relay.

Sculpt Studio (ai-box-apps apps/sculpt-studio, "The Discord relay (Hermes)") and lab-printer
(apps/printer, "Notices: the design studio's and the relay's") keep their notices until a relay
reports them delivered. The notice-relay Hermes cron job (./default.nix) runs this every minute,
in no-agent mode. Each run:

1. Reads the Discord bot's credentials and the person map from the agent's secrets file: a cron
   script's environment carries no secrets. `hermes send` gets the credentials for its call.
2. Sculpt Studio (`box <studio> notices`): groups the notices by their `person` and sends each
   person one Discord message, a line per notice (the project's title, what happened, the link).
   A person who is the agent itself (--agent-person) has nobody to tell: their notices are marked
   delivered without a message.
3. lab-printer (`box <printer> notices`, the relay's route; the studio follows its own): sends
   each notice to --printer-to as its own message, with its photo when it has one.
4. Marks delivered (`notices-delivered`) only what `hermes send` reported sent, so a failed send
   is tried again on the next run, and appends one JSON line per notice to --log.

An app that can't be read (restarting, down, or a printer that is off) is skipped until a later
run: the apps-health cron job reports apps that stay down. A notice that couldn't be delivered (an
unknown person, Discord refusing) stays with its app, is printed, and the run exits 1, so Hermes's
cron failure alert tells Alex (once per distinct problem, then again after its repeat cooldown).
A run with nothing to report prints nothing, which keeps the cron job silent.

Exit codes: 0 every notice delivered (or none waiting), 1 some not delivered, 2 bad configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_UNDELIVERED = 1
EXIT_CONFIG = 2

# The secrets file's lines this script reads: the bot token and home channel are what
# `hermes send` needs for Discord; the person map is the vault item "Notice relay people".
TOKEN_VAR = "DISCORD_BOT_TOKEN"
HOME_CHANNEL_VAR = "DISCORD_HOME_CHANNEL"
PEOPLE_VAR = "NOTICE_RELAY_PEOPLE"
# Set by Hermes for its own cron agent runs; `hermes send` skips a send to the target they name
# (the run delivers there itself). This script delivers its own messages, so they are dropped.
CRON_AUTO_DELIVER_PREFIX = "HERMES_CRON_AUTO_DELIVER_"
# A box call answers within seconds (notices are polled without waiting).
BOX_TIMEOUT_SECONDS = 60
# A Discord send with a photo upload.
SEND_TIMEOUT_SECONDS = 120  # 2 minutes
# `MEDIA:<path>` in a message makes `hermes send` attach that file; notice text comes from the
# apps (a Sculpt builder writes it), so a tag in it is defused rather than obeyed.
MEDIA_TAG = re.compile(r"MEDIA:", re.IGNORECASE)


class ConfigError(Exception):
    """The secrets file or the arguments can't be used (exit 2)."""


class AppUnavailable(Exception):
    """A box call to an app failed: the app is down, restarting, or refused."""


@dataclass(frozen=True)
class Message:
    """One Discord message and the notices it delivers."""

    app: str
    to: str
    text: str
    ids: tuple[str, ...]
    person: str = ""
    photo: Path | None = None


@dataclass
class Run:
    """What one run did: the problems to report and the log lines to append."""

    problems: list[str] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self, app: str, ids: Iterable[str], outcome: str, to: str = "", person: str = ""
    ) -> None:
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        for notice_id in ids:
            self.log.append(
                {
                    "at": at,
                    "app": app,
                    "id": notice_id,
                    "person": person,
                    "to": to,
                    "outcome": outcome,
                }
            )


class Box:
    """The lab apps' calls, through the `box` CLI."""

    def __init__(self, box: str) -> None:
        self.box = box

    def call(self, app: str, command: str, *args: str) -> Any:
        """Run `box <app> <command> <args> --json` and return its JSON answer."""
        out = self._run(app, command, *args, "--json")
        try:
            return json.loads(out)
        except ValueError as e:
            raise AppUnavailable(f"box {app} {command}: answer isn't JSON") from e

    def photo(self, app: str, notice_id: str, out: Path) -> Path:
        """Save a printer notice's photo to `out`."""
        self._run(app, "notice-photo", "--id", notice_id, "-o", str(out))
        if not out.is_file():
            raise AppUnavailable(f"box {app} notice-photo: no file at {out}")
        return out

    def _run(self, app: str, command: str, *args: str) -> str:
        argv = [self.box, app, command, *args]
        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=BOX_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AppUnavailable(f"box {app} {command}: {e}") from e
        if done.returncode != 0:
            reason = done.stderr.strip().splitlines()[-1:] or [
                f"exit {done.returncode}"
            ]
            raise AppUnavailable(reason[0])
        return done.stdout


class Discord:
    """Sends through `hermes send`, with the bot's credentials from the secrets file."""

    def __init__(self, hermes: str, secrets: dict[str, str]) -> None:
        self.hermes = hermes
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(CRON_AUTO_DELIVER_PREFIX)
        }
        self.env.update(
            {k: secrets[k] for k in (TOKEN_VAR, HOME_CHANNEL_VAR) if k in secrets}
        )

    def send(self, to: str, text: str) -> str | None:
        """Send `text` to `to` (a `hermes send` target); None when sent, else why not."""
        argv = [self.hermes, "send", "--json", "--to", to, "--file", "-"]
        try:
            done = subprocess.run(
                argv,
                input=text,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=SEND_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"hermes send: {e}"
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            reason = done.stderr.strip().splitlines()[-1:] or [
                f"exit {done.returncode}"
            ]
            return f"hermes send: {reason[0]}"
        if not isinstance(answer, dict):
            return "hermes send: unexpected answer"
        if (
            answer.get("success") is True
            and not answer.get("skipped")
            and not answer.get("error")
        ):
            return None
        return str(
            answer.get("error") or answer.get("reason") or "hermes send: not sent"
        )


def read_secrets(path: Path, names: Sequence[str]) -> dict[str, str]:
    """The `NAME=value` lines of the secrets file for `names` (the file isn't shell-quoted, so it
    is read line by line rather than sourced)."""
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e.strerror}") from e
    found: dict[str, str] = {}
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() in names:
            found[name.strip()] = value.strip()
    return found


def parse_people(spec: str) -> dict[str, str]:
    """`person=target,person=target` into {person: target}, e.g.
    `a@example.com=discord:123` -> {"a@example.com": "discord:123"}."""
    people: dict[str, str] = {}
    for entry in spec.split(","):
        if not entry.strip():
            continue
        person, sep, target = entry.partition("=")
        if not sep or not person.strip() or not target.strip():
            raise ConfigError(
                f"{PEOPLE_VAR}: entry {entry.strip()!r} isn't person=target"
            )
        people[person.strip()] = target.strip()
    return people


def one_line(text: str) -> str:
    """The notice's text on one line, with any MEDIA tag defused."""
    return MEDIA_TAG.sub("MEDIA :", " ".join(str(text).split()))


def sculpt_messages(
    app: str,
    notices: list[dict[str, Any]],
    people: dict[str, str],
    agent_persons: set[str],
    run: Run,
) -> tuple[list[Message], list[str]]:
    """One message per person for Sculpt Studio's notices, and the ids of the agent's own notices.
    A person with no Discord target is reported; their notices stay."""
    lines: dict[str, list[str]] = {}
    ids: dict[str, list[str]] = {}
    acknowledged: list[str] = []
    for notice in notices:
        person = str(notice.get("person", ""))
        if person in agent_persons:
            acknowledged.append(str(notice["id"]))
            continue
        title = one_line(notice.get("title", "")) or "A project"
        link = str(notice.get("link", ""))
        line = f"**{title}**: {one_line(notice.get('text', ''))}"
        lines.setdefault(person, []).append(f"{line} <{link}>" if link else line)
        ids.setdefault(person, []).append(str(notice["id"]))
    messages: list[Message] = []
    for person, person_lines in lines.items():
        if person not in people:
            run.problems.append(
                f"{app}: no Discord target for {person!r}: {len(person_lines)} notice(s) kept "
                f'(add them to the vault item "Notice relay people")'
            )
            continue
        messages.append(
            Message(
                app, people[person], "\n".join(person_lines), tuple(ids[person]), person
            )
        )
    return messages, acknowledged


def printer_message(
    app: str, notice: dict[str, Any], to: str, photo: Path | None
) -> Message:
    """A printer notice's message: its text, the print's name when the text lacks it, its photo."""
    text = one_line(notice.get("text", ""))
    name = one_line(notice.get("print_name", ""))
    if name and name not in text:
        text = f"{text} ({name})"
    if photo is not None:
        text = f"{text}\nMEDIA:{photo}"
    return Message(app, to, text, (str(notice["id"]),), photo=photo)


def deliver(box: Box, discord: Discord, message: Message, run: Run) -> None:
    """Send one message, then mark its notices delivered."""
    error = discord.send(message.to, message.text)
    if error is not None:
        run.problems.append(
            f"{message.app}: {len(message.ids)} notice(s) for {message.to} not delivered: {error}"
        )
        run.record(
            message.app, message.ids, f"not sent: {error}", message.to, message.person
        )
        return
    mark(box, message.app, list(message.ids), run, "sent", message.to, message.person)


def mark(
    box: Box,
    app: str,
    ids: list[str],
    run: Run,
    outcome: str,
    to: str = "",
    person: str = "",
) -> None:
    """Report notices delivered to their app."""
    if not ids:
        return
    try:
        box.call(app, "notices-delivered", "--ids", json.dumps(ids))
    except AppUnavailable as e:
        run.problems.append(
            f"{app}: {outcome}, but not marked delivered ({e}): they will be sent again"
        )
        outcome = f"{outcome}, not marked delivered: {e}"
    run.record(app, ids, outcome, to, person)


def pending(box: Box, app: str, *args: str) -> list[dict[str, Any]]:
    """An app's notices waiting for the relay; none while the app can't be read."""
    try:
        answer = box.call(app, "notices", *args)
    except AppUnavailable as e:
        print(f"{app}: skipped, can't read its notices: {e}", file=sys.stderr)
        return []
    notices = answer.get("notices") if isinstance(answer, dict) else None
    if not isinstance(notices, list):
        print(f"{app}: skipped, its notices answer has no list", file=sys.stderr)
        return []
    return [n for n in notices if isinstance(n, dict) and "id" in n]


def relay_sculpt(
    box: Box,
    discord: Discord,
    args: argparse.Namespace,
    people: dict[str, str],
    run: Run,
) -> None:
    messages, acknowledged = sculpt_messages(
        args.sculpt, pending(box, args.sculpt), people, set(args.agent_person), run
    )
    mark(box, args.sculpt, acknowledged, run, "acknowledged (the agent's own)")
    for message in messages:
        deliver(box, discord, message, run)


def relay_printer(
    box: Box, discord: Discord, args: argparse.Namespace, run: Run
) -> None:
    for notice in pending(box, args.printer):
        photo: Path | None = None
        if notice.get("has_photo"):
            out = args.photo_dir / f"notice-relay-{notice['id']}.jpg"
            try:
                photo = box.photo(args.printer, str(notice["id"]), out)
            except AppUnavailable as e:
                # The notice still goes out; the next run can't do better if the photo is gone.
                print(
                    f"{args.printer}: notice {notice['id']} without its photo: {e}",
                    file=sys.stderr,
                )
        try:
            deliver(
                box,
                discord,
                printer_message(args.printer, notice, args.printer_to, photo),
                run,
            )
        finally:
            if photo is not None:
                photo.unlink(missing_ok=True)


def append_log(path: Path, lines: list[dict[str, Any]]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="notice-relay", description=__doc__.split("\n\n")[0]
    )
    p.add_argument(
        "--sculpt", metavar="APP", help="Sculpt Studio's instance, e.g. lab-sculpt"
    )
    p.add_argument(
        "--printer", metavar="APP", help="lab-printer's instance, e.g. lab-printer"
    )
    p.add_argument(
        "--printer-to",
        default="discord",
        help="hermes send target for printer notices (default: the home channel)",
    )
    p.add_argument(
        "--agent-person",
        action="append",
        default=[],
        metavar="NAME",
        help="a Sculpt person that is the agent itself: acknowledged, never messaged (repeatable)",
    )
    p.add_argument("--secrets", type=Path, default=Path("/run/hermes-secrets/env"))
    p.add_argument(
        "--photo-dir",
        type=Path,
        required=True,
        help="where photos wait for their send (a Hermes media cache)",
    )
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--box", default="box")
    p.add_argument("--hermes", default="hermes")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        secrets = read_secrets(args.secrets, (TOKEN_VAR, HOME_CHANNEL_VAR, PEOPLE_VAR))
        if TOKEN_VAR not in secrets:
            raise ConfigError(f"{args.secrets} has no {TOKEN_VAR}")
        people = parse_people(secrets.get(PEOPLE_VAR, ""))
        if args.sculpt and not people:
            raise ConfigError(f"{args.secrets} has no {PEOPLE_VAR}")
        args.photo_dir.mkdir(parents=True, exist_ok=True)
    except (ConfigError, OSError) as e:
        print(f"notice-relay: {e}")
        return EXIT_CONFIG
    box, discord, run = Box(args.box), Discord(args.hermes, secrets), Run()
    if args.sculpt:
        relay_sculpt(box, discord, args, people, run)
    if args.printer:
        relay_printer(box, discord, args, run)
    append_log(args.log, run.log)
    for problem in run.problems:
        print(problem)
    return EXIT_UNDELIVERED if run.problems else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
