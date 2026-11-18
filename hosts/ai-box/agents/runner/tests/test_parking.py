"""Tests for parking.py: parked permissions and questions, and the answers they take."""

from __future__ import annotations

import pytest
from agent_runner.acp import (
    ElicitationResponse,
    PermissionOption,
    PermissionOutcome,
    RequestPermissionResponse,
)
from agent_runner.errors import RunnerError
from agent_runner.events import Event, PermissionAsked, QuestionAsked
from agent_runner.parking import Parking
from agent_runner.schema import JsonObject


def parked() -> Parking:
    parking = Parking()
    p = parking.next_id("permission")
    parking.park(
        10,
        Event(
            1,
            0.0,
            "s",
            PermissionAsked(
                request_id=p,
                title="touch x",
                options=[
                    PermissionOption("allow", "Allow", "allow_once"),
                    PermissionOption("reject", "Reject", "reject_once"),
                ],
            ),
        ),
    )
    q = parking.next_id("question")
    parking.park("r11", Event(2, 0.0, "s", QuestionAsked(request_id=q, message="?")))
    return parking


def test_ids_say_the_kind_and_count_across_kinds() -> None:
    parking = parked()
    assert list(parking.open) == ["p1", "q2"]
    assert parking.open["p1"].kind == "permission"
    assert parking.open["q2"].kind == "question"


def test_a_permission_takes_one_of_its_options_or_cancel() -> None:
    parking = parked()
    answer = parking.answer("s", "p1", {"option_id": "allow"})
    assert answer.rpc_id == 10
    assert answer.response == RequestPermissionResponse(
        PermissionOutcome(outcome="selected", option_id="allow")
    )
    assert answer.outcome == PermissionOutcome(outcome="selected", option_id="allow")
    assert "p1" not in parking.open
    parking = parked()
    cancelled = parking.answer("s", "p1", {"cancel": True, "option_id": "allow"})
    assert cancelled.outcome == PermissionOutcome(outcome="cancelled")


@pytest.mark.parametrize(
    "body, error",
    [
        ({"option_id": "maybe"}, "option_id must be one of allow, reject"),
        ({}, "option_id must be one of allow, reject"),
        ({"option_id": 1}, "option_id: must be a string"),
        ({"action": "accept"}, "action: unknown field"),
    ],
)
def test_a_permission_refuses_other_answers(body: JsonObject, error: str) -> None:
    parking = parked()
    with pytest.raises(RunnerError, match=error) as e:
        parking.answer("s", "p1", body)
    assert e.value.status == 400
    assert "p1" in parking.open  # still waiting


def test_a_question_takes_accept_with_content_decline_or_cancel() -> None:
    answer = parked().answer("s", "q2", {"action": "accept", "content": {"c": "red"}})
    assert (answer.rpc_id, answer.outcome) == (
        "r11",
        ElicitationResponse(action="accept", content={"c": "red"}),
    )
    decline = parked().answer("s", "q2", {"action": "decline", "content": {"x": 1}})
    assert decline.response == ElicitationResponse(action="decline")
    assert parked().answer("s", "q2", {"action": "cancel"}).outcome == (
        ElicitationResponse(action="cancel")
    )


@pytest.mark.parametrize(
    "body, error",
    [
        (
            {"action": "accept"},
            "accept needs content: an object of the schema's fields",
        ),
        ({"action": "maybe"}, "action: must be one of accept, decline, cancel"),
        ({}, "action: missing"),
        ({"action": "accept", "content": []}, "content: must be an object"),
        ({"option_id": "allow", "action": "cancel"}, "option_id: unknown field"),
    ],
)
def test_a_question_refuses_other_answers(body: JsonObject, error: str) -> None:
    with pytest.raises(RunnerError, match=error):
        parked().answer("s", "q2", body)


def test_an_id_that_is_not_open_is_a_404() -> None:
    with pytest.raises(RunnerError, match="s has no open request p9") as e:
        parked().answer("s", "p9", {"option_id": "allow"})
    assert e.value.status == 404


def test_cancel_withdraw_and_drop() -> None:
    parking = parked()
    assert parking.cancel("p1").outcome == PermissionOutcome(outcome="cancelled")
    assert parking.cancel("q2").outcome == ElicitationResponse(action="cancel")
    assert parking.open == {}
    parking = parked()
    assert parking.withdraw("r11") == ["q2"]
    assert parking.withdraw(99) == []
    assert parking.drop() == ["p1"]
    assert parking.open == {}
