"""hermes_board.py: kanban cards worked as jobs, against the stand-in agent and a stand-in
`hermes` that records its calls and prints the card's context from a file; and, given Hermes
(AGENT_RUNNER_HERMES: nix-config's card-worker check), against Hermes's own board."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from agent_runner import hermes_board
from agent_runner.hermes_board import MARKER, Board, Lane, kanban, work
from agent_runner.wait import Waiting
from conftest import Service

QUICK = Waiting(marker=re.compile(MARKER), every=0.05, timeout=10, idle=1)
HERMES = os.environ.get("AGENT_RUNNER_HERMES")

FAKE_HERMES = """\
import json, os, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps([os.environ.get("HERMES_KANBAN_RUN_ID"), *sys.argv[2:]]) + "\\n")
if sys.argv[2] == "context":
    print((here / "context.txt").read_text())
sys.exit(int((here / "rc").read_text()) if (here / "rc").exists() else 0)
"""


class Card:
    def __init__(self, tmp: Path) -> None:
        self.dir = tmp / "hermes"
        self.dir.mkdir()
        script = self.dir / "hermes.py"
        script.write_text(FAKE_HERMES)
        command = self.dir / "hermes"
        command.write_text(f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n')
        command.chmod(0o755)
        self.board = Board(str(command), "t_42", "7", str(tmp))

    def says(self, script: str) -> None:
        (self.dir / "context.txt").write_text(f"# Fix the thing\n\nfake: {script}")

    def calls(self) -> list[list[str]]:
        lines = (self.dir / "calls.jsonl").read_text().splitlines()
        calls = [json.loads(line) for line in lines]
        assert {call[0] for call in calls} == {"7"}, "every call names the card's run"
        return [call[1:] for call in calls]

    def work(self, service: Service) -> None:
        work(service.client, self.board, None, None, how=QUICK)


def prompts(service: Service) -> list[str]:
    events = service.events("card-t-42")
    return [e["text"] for e in events if e["kind"] == "prompt"]


@pytest.fixture
def card(tmp_path: Path) -> Card:
    return Card(tmp_path)


def test_done_completes_the_card_and_stops_the_session(
    service: Service, card: Card
) -> None:
    card.says("say CARD-DONE: fixed the thing")
    card.work(service)
    assert card.calls() == [
        ["context", "t_42"],
        ["heartbeat", "t_42", "--note=MARKER"],
        ["complete", "t_42", "--summary=fixed the thing"],
    ]
    status = service.status("card-t-42")
    assert status["state"] == "stopped"
    assert status["origin"] == "kanban card t_42"
    assert prompts(service)[0].startswith(
        "You're working card t_42 of Hermes's kanban board"
    )


def test_a_question_blocks_and_the_retry_resumes_with_the_answer(
    service: Service, card: Card
) -> None:
    card.says("question")
    card.work(service)
    block = card.calls()[-1]
    assert block[:5] == ["block", "t_42", "--kind", "needs_input", "--"]
    assert "Which colour?" in block[5]
    assert service.status("card-t-42")["state"] == "waiting"
    # Alex answers in a comment and unblocks; the lane claims the card again.
    card.says("say CARD-DONE: blue it is")
    card.work(service)
    assert card.calls()[-1] == ["complete", "t_42", "--summary=blue it is"]
    assert prompts(service)[-1].startswith("Card t_42 is back with you")


def test_need_live_blocks(service: Service, card: Card) -> None:
    card.says("say CARD-NEED-LIVE: run ai-box-test")
    card.work(service)
    assert card.calls()[-1][-1] == "CARD-NEED-LIVE: run ai-box-test"


def test_the_usage_limit_is_waited_out(
    service: Service, card: Card, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first turn hits it, so the start itself is refused (429) until it resets.
    card.says(f"limit {int(time.time()) + 2}")

    def sleep(seconds: float) -> None:
        card.says("say CARD-DONE: after the limit")
        time.sleep(seconds)

    monkeypatch.setattr(hermes_board, "sleep", sleep)
    card.work(service)
    calls = card.calls()
    assert calls[1][:2] == ["comment", "t_42"] and "usage limit" in calls[1][3]
    assert calls[-1] == ["complete", "t_42", "--summary=after the limit"]


def test_quiet_without_a_marker_blocks(service: Service, card: Card) -> None:
    card.says("say I looked around")
    card.work(service)
    block = card.calls()[-1]
    assert block[:4] == ["block", "t_42", "--kind", "transient"]
    assert "I looked around" in block[5]


def test_a_board_refusal_ends_the_run(service: Service, card: Card) -> None:
    card.says("say CARD-DONE: x")
    (card.dir / "rc").write_text("1")
    card.work(service)
    assert card.calls()[-1][:4] == ["block", "t_42", "--kind", "transient"]


@pytest.mark.skipif(HERMES is None, reason="needs Hermes: card-worker's build check")
def test_on_hermes_s_own_board(
    service: Service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert HERMES is not None
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))

    def board(*args: str) -> Any:
        return json.loads(kanban(HERMES, *args, "--json"))

    body = "fake: say CARD-DONE: on Hermes's board"
    card = board("create", "a card", "--assignee", "coder", "--body", body)["id"]
    lost = board("create", "a lost card", "--assignee", "coder")["id"]
    kanban(HERMES, "claim", lost, "--ttl=1")
    time.sleep(1.5)
    # The gateway's dispatcher tick starts no worker for a coder card, and takes back a claim
    # that ran out (a lane that's gone): the lost card is ready again, a failure booked.
    tick = board("dispatch")
    assert tick["spawned"] == [] and card in tick["skipped_nonspawnable"], tick
    assert tick["reclaimed"] == 1, tick
    # The lane claims both and works them.
    lane = Lane(service.client, HERMES, None, None, QUICK)
    for thread in lane.tick():
        thread.join(30)
    done, blocked = board("show", card), board("show", lost)
    assert done["task"]["status"] == "done", done
    assert blocked["task"]["status"] == "blocked", blocked
    assert "without CARD-DONE" in blocked["comments"][-1]["body"], blocked
    # None of it went through the profile owner (the gateway that refused a coder profile), and
    # no profile exists.
    events = [e["kind"] for e in done["events"] + blocked["events"]]
    assert "owner_admitted" not in events and "spawned" not in events, events
    assert not (home / "profiles").exists()
