"""Tests for relay.py against a fake `box` and a fake `hermes`. Run with `just test`.

The fakes are small Python executables in a temp dir: the fake box serves each app's notices from
a JSON file and records what was marked delivered; the fake hermes records every send and fails
for the targets the test names.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import relay

FAKE_BOX = """
import json, sys
from pathlib import Path
here = Path(__file__).parent
state = json.loads((here / "box.json").read_text())
app, command, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
if app in state.get("down", []):
    print(f"error: box {app} {command}: the app isn't running", file=sys.stderr)
    sys.exit(1)
if command == "notices":
    print(json.dumps({"notices": state["notices"].get(app, [])}))
elif command == "notices-delivered":
    ids = json.loads(rest[rest.index("--ids") + 1])
    if app in state.get("mark_fails", []):
        print(f"error: box {app} notices-delivered: HTTP 500", file=sys.stderr)
        sys.exit(1)
    with (here / "delivered.jsonl").open("a") as f:
        f.write(json.dumps({"app": app, "ids": ids}) + "\\n")
    print(json.dumps({"delivered": len(ids)}))
elif command == "notice-photo":
    notice_id = rest[rest.index("--id") + 1]
    if notice_id in state.get("no_photo", []):
        print(f"error: box {app} notice-photo: HTTP 404: notice {notice_id} has no photo", file=sys.stderr)
        sys.exit(1)
    out = Path(rest[rest.index("-o") + 1])
    out.write_bytes(b"\\xff\\xd8 jpeg")
    print(out)
"""

FAKE_HERMES = """
import json, os, sys
from pathlib import Path
here = Path(__file__).parent
args = sys.argv[1:]
to = args[args.index("--to") + 1]
text = sys.stdin.read()
fails = json.loads((here / "hermes.json").read_text()).get("fail", {})
media = [l[len("MEDIA:"):] for l in text.splitlines() if l.startswith("MEDIA:")]
with (here / "sent.jsonl").open("a") as f:
    f.write(json.dumps({
        "to": to, "text": text, "media_exists": [os.path.exists(m) for m in media],
        "token": os.environ.get("DISCORD_BOT_TOKEN"),
        "auto_deliver": os.environ.get("HERMES_CRON_AUTO_DELIVER_PLATFORM"),
    }) + "\\n")
print("warning: install out of sync", file=sys.stderr)
if to in fails:
    print(json.dumps({"error": fails[to]}))
    sys.exit(1)
print(json.dumps({"success": True, "platform": "discord", "chat_id": to}))
"""

ALEX = "alex@example.com"
BETH = "beth@example.com"
PEOPLE = f"{ALEX}=discord:111,{BETH}=discord:222"


def sculpt(
    notice_id: str,
    person: str,
    title: str = "Door sock",
    text: str = "Round 1: 1 option(s)",
) -> dict[str, Any]:
    return {
        "id": notice_id,
        "person": person,
        "project": "p1",
        "title": title,
        "kind": "round",
        "text": text,
        "link": f"https://lab-sculpt.example/#/p/p1?m={notice_id}",
        "at": "2026-11-16T16:44:00-0800",
    }


def printed(
    notice_id: str,
    text: str = "Print finished - Tag.",
    name: str = "Tag",
    photo: bool = True,
) -> dict[str, Any]:
    return {
        "id": notice_id,
        "kind": "finished",
        "print_name": name,
        "text": text,
        "has_photo": photo,
        "route": "relay",
    }


class Fakes:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.box_state: dict[str, Any] = {"notices": {}}
        self.hermes_state: dict[str, Any] = {}
        for name, source in (("box", FAKE_BOX), ("hermes", FAKE_HERMES)):
            exe = root / name
            exe.write_text(f"#!{sys.executable}\n{source}")
            exe.chmod(0o755)
        self.secrets = root / "env"
        self.secrets.write_text(
            f"DISCORD_BOT_TOKEN=tok\nDISCORD_HOME_CHANNEL=111\nNOTICE_RELAY_PEOPLE={PEOPLE}\nOTHER=x=y\n"
        )
        self.photos = root / "images"
        self.log = root / "logs" / "notice-relay.log"

    def run(self, *extra: str) -> int:
        (self.root / "box.json").write_text(json.dumps(self.box_state))
        (self.root / "hermes.json").write_text(json.dumps(self.hermes_state))
        args = [
            "--sculpt",
            "lab-sculpt",
            "--printer",
            "lab-printer",
            "--printer-to",
            "discord",
            "--agent-person",
            "hermes",
            "--agent-person",
            "hermes-test",
            "--secrets",
            str(self.secrets),
            "--photo-dir",
            str(self.photos),
            "--log",
            str(self.log),
            "--box",
            str(self.root / "box"),
            "--hermes",
            str(self.root / "hermes"),
            *extra,
        ]
        return relay.main(args)

    def lines(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def sent(self) -> list[dict[str, Any]]:
        return self.lines("sent.jsonl")

    def delivered(self) -> list[dict[str, Any]]:
        return self.lines("delivered.jsonl")

    def logged(self) -> list[dict[str, Any]]:
        return (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fakes:
    monkeypatch.setenv("HERMES_CRON_AUTO_DELIVER_PLATFORM", "discord")
    return Fakes(tmp_path)


def test_nothing_waiting_is_silent(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fakes.run() == relay.EXIT_OK
    assert fakes.sent() == []
    assert fakes.delivered() == []
    assert not fakes.log.exists()
    assert capsys.readouterr().out == ""


def test_sculpt_one_message_per_person(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-sculpt"] = [
        sculpt("n-1", ALEX, text="Round 9: 1 option(s) - Here's\nthe file."),
        sculpt("n-2", BETH, title="Shelf"),
        sculpt("n-3", ALEX, text="Which colours?"),
    ]
    assert fakes.run() == relay.EXIT_OK
    sent = {s["to"]: s for s in fakes.sent()}
    assert set(sent) == {"discord:111", "discord:222"}
    assert sent["discord:111"]["text"].splitlines() == [
        "**Door sock**: Round 9: 1 option(s) - Here's the file. <https://lab-sculpt.example/#/p/p1?m=n-1>",
        "**Door sock**: Which colours? <https://lab-sculpt.example/#/p/p1?m=n-3>",
    ]
    assert sent["discord:222"]["text"].startswith("**Shelf**: Round 1")
    # The bot's credentials come from the secrets file; Hermes's own cron routing doesn't leak in.
    assert sent["discord:111"]["token"] == "tok"
    assert sent["discord:111"]["auto_deliver"] is None
    assert sorted(fakes.delivered(), key=lambda d: d["ids"]) == [
        {"app": "lab-sculpt", "ids": ["n-1", "n-3"]},
        {"app": "lab-sculpt", "ids": ["n-2"]},
    ]
    assert {
        (entry["id"], entry["outcome"], entry["person"]) for entry in fakes.logged()
    } == {
        ("n-1", "sent", ALEX),
        ("n-3", "sent", ALEX),
        ("n-2", "sent", BETH),
    }
    assert capsys.readouterr().out == ""


def test_agent_persons_are_acknowledged_without_a_message(fakes: Fakes) -> None:
    fakes.box_state["notices"]["lab-sculpt"] = [
        sculpt("n-1", "hermes"),
        sculpt("n-2", "hermes-test"),
    ]
    assert fakes.run() == relay.EXIT_OK
    assert fakes.sent() == []
    assert fakes.delivered() == [
        {"app": "lab-sculpt", "ids": ["n-1"]},
        {"app": "lab-sculpt", "ids": ["n-2"]},
    ]
    assert [(entry["person"], entry["outcome"]) for entry in fakes.logged()] == [
        ("hermes", "acknowledged (the agent's own)"),
        ("hermes-test", "acknowledged (the agent's own)"),
    ]


def test_unknown_person_is_kept_and_reported(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-sculpt"] = [
        sculpt("n-1", "stranger@example.com"),
        sculpt("n-2", ALEX),
    ]
    assert fakes.run() == relay.EXIT_UNDELIVERED
    assert [s["to"] for s in fakes.sent()] == ["discord:111"]
    assert fakes.delivered() == [{"app": "lab-sculpt", "ids": ["n-2"]}]
    out = capsys.readouterr().out
    assert "no Discord target for 'stranger@example.com': 1 notice(s) kept" in out
    assert "Notice relay people" in out


def test_failed_send_keeps_the_notices(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-sculpt"] = [
        sculpt("n-1", BETH),
        sculpt("n-2", ALEX),
    ]
    fakes.hermes_state["fail"] = {
        "discord:222": "Discord API error (403): Cannot send messages to this user"
    }
    assert fakes.run() == relay.EXIT_UNDELIVERED
    assert fakes.delivered() == [{"app": "lab-sculpt", "ids": ["n-2"]}]
    # The log keeps what was done; the failure is in the run's output, not logged every retry.
    assert [entry["id"] for entry in fakes.logged()] == ["n-2"]
    out = capsys.readouterr().out
    assert out.strip() == (
        "lab-sculpt: 1 notice(s) for discord:222 not delivered: "
        "Discord API error (403): Cannot send messages to this user"
    )
    # The same failure prints the same text on the next run (Hermes groups alerts by it).
    assert fakes.run() == relay.EXIT_UNDELIVERED
    assert capsys.readouterr().out == out


def test_skipped_send_is_not_delivered(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-printer"] = [printed("p-1", photo=False)]
    (fakes.root / "hermes").write_text(
        f"#!{sys.executable}\nimport json\n"
        'print(json.dumps({"success": True, "skipped": True, "reason": "cron_auto_delivery_duplicate_target"}))\n'
    )
    assert fakes.run() == relay.EXIT_UNDELIVERED
    assert fakes.delivered() == []
    assert "cron_auto_delivery_duplicate_target" in capsys.readouterr().out


def test_printer_notice_with_its_photo(fakes: Fakes) -> None:
    fakes.box_state["notices"]["lab-printer"] = [
        printed("p-1"),
        printed(
            "p-2", text="The plate is waiting to be cleared.", name="Tag", photo=False
        ),
    ]
    assert fakes.run() == relay.EXIT_OK
    first, second = fakes.sent()
    photo = fakes.photos / "notice-relay-p-1.jpg"
    assert first["to"] == "discord"
    assert first["text"] == f"Print finished - Tag.\nMEDIA:{photo}"
    assert first["media_exists"] == [True]
    assert not photo.exists()  # removed after the send
    assert second["text"] == "The plate is waiting to be cleared. (Tag)"
    assert fakes.delivered() == [
        {"app": "lab-printer", "ids": ["p-1"]},
        {"app": "lab-printer", "ids": ["p-2"]},
    ]


def test_printer_notice_goes_without_a_missing_photo(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-printer"] = [printed("p-1")]
    fakes.box_state["no_photo"] = ["p-1"]
    assert fakes.run() == relay.EXIT_OK
    assert fakes.sent()[0]["text"] == "Print finished - Tag."
    assert "without its photo" in capsys.readouterr().err


def test_media_tags_in_notice_text_are_defused(fakes: Fakes) -> None:
    fakes.box_state["notices"]["lab-sculpt"] = [
        sculpt("n-1", ALEX, text="see MEDIA:/etc/passwd and media:/x")
    ]
    fakes.box_state["notices"]["lab-printer"] = [
        printed("p-1", text="MEDIA:/etc/shadow", photo=False)
    ]
    assert fakes.run() == relay.EXIT_OK
    for s in fakes.sent():
        assert "MEDIA:/" not in s["text"] and "media:/" not in s["text"]
        assert s["media_exists"] == []


def test_down_app_is_skipped_silently(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["down"] = ["lab-printer"]
    fakes.box_state["notices"]["lab-sculpt"] = [sculpt("n-1", ALEX)]
    assert fakes.run() == relay.EXIT_OK
    assert [s["to"] for s in fakes.sent()] == ["discord:111"]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "lab-printer: skipped" in captured.err


def test_sent_but_not_marked_is_reported(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.box_state["notices"]["lab-printer"] = [printed("p-1", photo=False)]
    fakes.box_state["mark_fails"] = ["lab-printer"]
    assert fakes.run() == relay.EXIT_UNDELIVERED
    assert len(fakes.sent()) == 1
    assert "sent, but not marked delivered" in capsys.readouterr().out
    assert fakes.logged()[0]["outcome"].startswith("sent, not marked delivered")


def test_missing_people_is_a_config_error(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.secrets.write_text("DISCORD_BOT_TOKEN=tok\n")
    assert fakes.run() == relay.EXIT_CONFIG
    assert "has no NOTICE_RELAY_PEOPLE" in capsys.readouterr().out
    assert fakes.sent() == []


def test_missing_secrets_file_is_a_config_error(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes.secrets.unlink()
    assert fakes.run() == relay.EXIT_CONFIG
    assert "can't read" in capsys.readouterr().out


def test_parse_people() -> None:
    assert relay.parse_people(" a@x=discord:1 , b@x=discord:2,") == {
        "a@x": "discord:1",
        "b@x": "discord:2",
    }
    with pytest.raises(relay.ConfigError):
        relay.parse_people("a@x")


def test_read_secrets_keeps_values_with_equals_signs(tmp_path: Path) -> None:
    env = tmp_path / "env"
    env.write_text("# comment\nA=1=2\nB = two\nC=unused\n")
    assert relay.read_secrets(env, ("A", "B")) == {"A": "1=2", "B": "two"}
