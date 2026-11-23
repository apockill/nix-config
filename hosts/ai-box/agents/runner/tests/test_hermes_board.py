"""hermes_board.py: a kanban card worked as a job, against the stand-in agent and a stand-in
`hermes` that records its calls and prints the card's context from a file."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest
from agent_runner import hermes_board
from agent_runner.hermes_board import MARKER, Board, work
from agent_runner.wait import Waiting
from conftest import Service

QUICK = Waiting(marker=re.compile(MARKER), every=0.05, timeout=10, idle=1)

FAKE_HERMES = """\
import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps(sys.argv[2:]) + "\\n")
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
        self.board = Board(str(command), "t_42")
        self.env = {"HERMES_KANBAN_TASK": "t_42", "HERMES_KANBAN_WORKSPACE": str(tmp)}

    def says(self, script: str) -> None:
        (self.dir / "context.txt").write_text(f"# Fix the thing\n\nfake: {script}")

    def calls(self) -> list[list[str]]:
        lines = (self.dir / "calls.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def work(self, service: Service) -> int:
        return work(service.client, self.board, self.env, None, None, QUICK)


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
    assert card.work(service) == 0
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
    assert card.work(service) == 0
    block = card.calls()[-1]
    assert block[:5] == ["block", "t_42", "--kind", "needs_input", "--"]
    assert "Which colour?" in block[5]
    assert service.status("card-t-42")["state"] == "waiting"
    # Alex answers in a comment and unblocks; Hermes runs the card again.
    card.says("say CARD-DONE: blue it is")
    assert card.work(service) == 0
    assert card.calls()[-1] == ["complete", "t_42", "--summary=blue it is"]
    assert prompts(service)[-1].startswith("Hermes retried card t_42")


def test_need_live_blocks(service: Service, card: Card) -> None:
    card.says("say CARD-NEED-LIVE: run ai-box-test")
    assert card.work(service) == 0
    assert card.calls()[-1][-1] == "CARD-NEED-LIVE: run ai-box-test"


def test_the_usage_limit_exits_75(service: Service, card: Card) -> None:
    # The first turn hits it, so the start itself is refused (429).
    card.says(f"limit {int(time.time()) + 3600}")
    assert card.work(service) == hermes_board.RATE_LIMITED
    assert [call[0] for call in card.calls()] == ["context"]


def test_quiet_without_a_marker_is_a_crash(service: Service, card: Card) -> None:
    card.says("say I looked around")
    assert card.work(service) == hermes_board.CRASHED
    comment = card.calls()[-1]
    assert comment[0] == "comment" and "I looked around" in comment[3]


def test_a_board_refusal_is_a_crash(service: Service, card: Card) -> None:
    card.says("say CARD-DONE: x")
    (card.dir / "rc").write_text("1")
    assert card.work(service) == hermes_board.CRASHED


def test_main_needs_a_card_and_leaves_the_exit_trailer(
    service: Service, card: Card, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hermes_board.main(service.client, {}, None, None, card.board.hermes) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "[kanban-worker-exit] rc=1"
