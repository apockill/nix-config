"""Tests for parking.py: parked permissions and questions, the answers they take, and the
futures the SDK's handlers await."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from acp.schema import (
    AcceptElicitationResponse,
    AllowedOutcome,
    CancelElicitationResponse,
    DeclineElicitationResponse,
    DeniedOutcome,
    PermissionOption,
    RequestPermissionResponse,
)
from agent_runner.base import JsonObject
from agent_runner.errors import RunnerError
from agent_runner.events import Event, PermissionAsked, QuestionAsked
from agent_runner.parking import Parking, Reply, outcome


def run(test: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(test())


def parked() -> tuple[Parking, asyncio.Future[Reply], asyncio.Future[Reply]]:
    """A permission p1 (agent's id 10) and a question q2 (agent's id "r11"); needs a loop."""
    parking = Parking()
    p = parking.next_id("permission")
    permission = parking.park(
        10,
        Event(
            seq=1,
            ts=0.0,
            session="s",
            body=PermissionAsked(
                request_id=p,
                title="touch x",
                options=[
                    PermissionOption(
                        option_id="allow", name="Allow", kind="allow_once"
                    ),
                    PermissionOption(
                        option_id="reject", name="Reject", kind="reject_once"
                    ),
                ],
            ),
        ),
    )
    q = parking.next_id("question")
    question = parking.park(
        "r11",
        Event(
            seq=2, ts=0.0, session="s", body=QuestionAsked(request_id=q, message="?")
        ),
    )
    return parking, permission, question


def test_ids_say_the_kind_and_count_across_kinds() -> None:
    async def test() -> None:
        parking, _, _ = parked()
        assert list(parking.open) == ["p1", "q2"]
        assert parking.open["p1"].kind == "permission"
        assert parking.open["q2"].kind == "question"
        assert parking.open["q2"].rpc_id == "r11"

    run(test)


def test_a_permission_takes_one_of_its_options_or_cancel() -> None:
    async def test() -> None:
        parking, permission, _ = parked()
        reply = parking.answer("s", "p1", {"option_id": "allow"})
        selected = AllowedOutcome(outcome="selected", option_id="allow")
        assert reply == RequestPermissionResponse(outcome=selected)
        assert await permission == reply  # what the SDK's handler returns to the agent
        assert outcome(reply) == selected
        assert "p1" not in parking.open
        parking, permission, _ = parked()
        cancelled = parking.answer("s", "p1", {"cancel": True, "option_id": "allow"})
        assert outcome(cancelled) == DeniedOutcome(outcome="cancelled")
        assert (await permission) == cancelled

    run(test)


@pytest.mark.parametrize(
    "body, error",
    [
        ({"option_id": "maybe"}, "option_id must be one of allow, reject"),
        ({}, "option_id must be one of allow, reject"),
        ({"option_id": 1}, "option_id: Input should be a valid string"),
        ({"action": "accept"}, "action: Extra inputs are not permitted"),
    ],
)
def test_a_permission_refuses_other_answers(body: JsonObject, error: str) -> None:
    async def test() -> None:
        parking, permission, _ = parked()
        with pytest.raises(RunnerError, match=error) as e:
            parking.answer("s", "p1", body)
        assert e.value.status == 400
        assert "p1" in parking.open and not permission.done()  # still waiting

    run(test)


def test_a_question_takes_accept_with_content_decline_or_cancel() -> None:
    async def test() -> None:
        parking, _, question = parked()
        reply = parking.answer("s", "q2", {"action": "accept", "content": {"c": "red"}})
        assert reply == AcceptElicitationResponse(action="accept", content={"c": "red"})
        assert outcome(reply) == reply and await question == reply
        parking, _, _ = parked()
        decline = parking.answer("s", "q2", {"action": "decline", "content": {"x": 1}})
        assert decline == DeclineElicitationResponse(action="decline")
        parking, _, _ = parked()
        assert parking.answer(
            "s", "q2", {"action": "cancel"}
        ) == CancelElicitationResponse(action="cancel")

    run(test)


@pytest.mark.parametrize(
    "body, error",
    [
        (
            {"action": "accept"},
            "accept needs content: an object of the schema's fields",
        ),
        (
            {"action": "maybe"},
            "action: Input should be 'accept', 'decline' or 'cancel'",
        ),
        ({}, "action: Field required"),
        (
            {"action": "accept", "content": []},
            "content: Input should be a valid dictionary",
        ),
        (
            {"option_id": "allow", "action": "cancel"},
            "option_id: Extra inputs are not permitted",
        ),
    ],
)
def test_a_question_refuses_other_answers(body: JsonObject, error: str) -> None:
    async def test() -> None:
        parking, _, _ = parked()
        with pytest.raises(RunnerError, match=error):
            parking.answer("s", "q2", body)

    run(test)


def test_an_id_that_is_not_open_is_a_404() -> None:
    async def test() -> None:
        parking, _, _ = parked()
        with pytest.raises(RunnerError, match="s has no open request p9") as e:
            parking.answer("s", "p9", {"option_id": "allow"})
        assert e.value.status == 404

    run(test)


def test_cancel_answers_withdraw_and_drop_do_not() -> None:
    async def test() -> None:
        parking, permission, question = parked()
        assert outcome(parking.cancel("p1")) == DeniedOutcome(outcome="cancelled")
        assert outcome(parking.cancel("q2")) == CancelElicitationResponse(
            action="cancel"
        )
        assert parking.open == {}
        assert permission.done() and question.done()
        parking, permission, question = parked()
        assert parking.withdraw("r11") == ["q2"]
        assert question.cancelled()  # the agent took it back: no reply goes out
        assert parking.withdraw(99) == []
        assert parking.drop() == ["p1"]
        assert permission.cancelled()
        assert parking.open == {}

    run(test)
