"""Tests for monitor.py. Run with `just test`."""

from __future__ import annotations

import monitor

REST = [27.59, 46.59, 41.64, 12.3, -84.19, -5.62]
NOW = 1_800_000_000.0


def state(
    power: int = 1,
    angles: list[float] | None = None,
    moved_ago: float = 3600.0,
    move_state: str = "done",
    gripper: str = "ok",
) -> dict:
    return {
        "connection": "connected",
        "power": power,
        "bus": {"state": "powered", "gripper": gripper},
        "angles": (angles or [*REST, -15.0]),
        "connected_for_s": 86400.0,
        "move": {"t": NOW - moved_ago, "state": move_state},
    }


def out_of_rest() -> list[float]:
    return [27.59, 60.0, 41.64, 12.3, -70.0, -5.62, -15.0]


def test_no_alert() -> None:
    assert monitor.alert_line(None) == "alert: none"


def test_alert_names_its_kind_time_and_later_kinds_only() -> None:
    alert = {
        "at": "2026-11-18T11:43:11-0800",
        "kind": "temp_rise",
        "msg": "hot\n  servo 4",
        "also": [{"kind": "temp_rise"}, {"kind": "servo_dropout"}, {"kind": "temp"}],
    }
    line = monitor.alert_line(alert)
    assert line.startswith("alert: temp_rise at 11-18 ")
    assert line.endswith(" (later also: servo_dropout, temp) - hot servo 4")


def test_alert_line_ignores_how_many_entries_are_folded_in() -> None:
    alert = {"t": NOW, "kind": "servo_dropout", "msg": "J7 silent", "also": []}
    more = {**alert, "also": [{"kind": "servo_dropout", "at": "later"}] * 50}
    assert monitor.alert_line(alert) == monitor.alert_line(more)


def test_released_names_its_last_release() -> None:
    events = [
        {
            "t": NOW - 60,
            "msg": "released at the rest pose: its joints stream that pose",
        },
        {"t": NOW - 30, "msg": "J7 read a jump"},
    ]
    line = monitor.arm_line(state(power=0), REST, events, None, NOW)
    assert line == f"arm: released at its rest at {monitor.stamp(NOW - 60)}"
    assert (
        monitor.arm_line(state(power=0), REST, [], None, NOW)
        == "arm: released at its rest"
    )


def test_powered_at_rest_within_tolerance() -> None:
    near = [a + 2.5 for a in REST] + [-15.0]
    assert (
        monitor.arm_line(state(angles=near), REST, [], None, NOW)
        == "arm: powered at its rest"
    )


def test_out_of_rest_is_stuck_only_once_still_for_stuck_s() -> None:
    fresh = state(angles=out_of_rest(), moved_ago=monitor.STUCK_S - 10)
    assert (
        monitor.arm_line(fresh, REST, [], None, NOW) == "arm: powered out of its rest"
    )
    still = state(
        angles=out_of_rest(), moved_ago=monitor.STUCK_S + 10, gripper="missing"
    )
    assert monitor.arm_line(still, REST, [], None, NOW) == (
        f"arm: STUCK powered out of its rest and still since {monitor.stamp(NOW - monitor.STUCK_S - 10)}"
        " (J2, J5 away from its rest); gripper servo silent; no lab stretch held"
    )


def test_stuck_line_is_stable_across_ticks() -> None:
    st = state(angles=out_of_rest(), moved_ago=600)
    assert monitor.arm_line(st, REST, [], None, NOW) == monitor.arm_line(
        {**st, "move": {"t": NOW - 600, "state": "done"}}, REST, [], None, NOW + 120
    )


def test_a_running_move_is_never_stuck() -> None:
    st = state(angles=out_of_rest(), moved_ago=7200, move_state="running")
    assert monitor.arm_line(st, REST, [], None, NOW) == "arm: powered out of its rest"


def test_a_lab_stretch_waits_longer() -> None:
    st = state(angles=out_of_rest(), moved_ago=monitor.STUCK_S + 10)
    assert (
        monitor.arm_line(st, REST, [], "calibrate", NOW)
        == "arm: powered out of its rest"
    )
    st = state(angles=out_of_rest(), moved_ago=monitor.STUCK_IN_STRETCH_S + 10)
    assert monitor.arm_line(st, REST, [], "calibrate", NOW).endswith(
        "; lab stretch held by calibrate"
    )


def test_no_move_since_the_link_came_up_counts_from_then() -> None:
    st = {**state(angles=out_of_rest()), "move": None, "connected_for_s": 100.0}
    assert monitor.arm_line(st, REST, [], None, NOW) == "arm: powered out of its rest"


def test_a_disconnected_arm_is_unknown() -> None:
    st = {**state(), "power": None, "connection": "disconnected"}
    assert monitor.arm_line(st, REST, [], None, NOW) == (
        "arm: unknown, lab-arm's link to it is disconnected"
    )
