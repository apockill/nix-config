"""Tests for rpc.py: JSON-RPC over an agent's stdio, against a tiny scripted agent."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from agent_runner import rpc
from agent_runner.acp import InitializeResult, RpcId
from agent_runner.errors import RunnerError
from agent_runner.rpc import AgentExited, Connection, RpcError
from agent_runner.schema import JsonObject

AGENT = r"""
import json, os, signal, sys
if os.environ.get("IGNORE_TERM"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    with open(os.environ["LOG"], "a") as f:
        f.write(line)
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params")
    if method is None:
        continue
    if method == "echo":
        send({"jsonrpc": "2.0", "id": rid, "result": params})
    elif method == "fail":
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": -32000, "message": "nope", "data": {"x": 1}}})
    elif method == "ask":
        send({"jsonrpc": "2.0", "id": 99, "method": "client/q", "params": {"a": 1}})
        answer = json.loads(sys.stdin.readline())
        send({"jsonrpc": "2.0", "id": rid, "result": answer})
    elif method == "note":
        send({"jsonrpc": "2.0", "method": "n/x", "params": None})
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif method == "garbage":
        print("not json", flush=True)
        send([1, 2])
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif method == "stderr":
        sys.stderr.write("oops\n"); sys.stderr.flush()
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif method == "wrongshape":
        send({"jsonrpc": "2.0", "id": rid, "result": {"agentCapabilities": 5}})
    elif method == "die":
        os._exit(4)
    elif method == "hang":
        pass
"""

Received = list[tuple[str, JsonObject, RpcId | None]]


def run(
    tmp_path: Path,
    test: Callable[[Connection, Received], Awaitable[None]],
    **env: str,
) -> None:
    script = tmp_path / "agent.py"
    script.write_text(AGENT)

    async def main() -> None:
        conn = await Connection.spawn(
            [sys.executable, str(script)],
            str(tmp_path),
            {"LOG": str(tmp_path / "in.log"), **env},
            tmp_path / "agent.log",
        )
        received: Received = []

        async def on_message(
            method: str, params: JsonObject, rid: RpcId | None
        ) -> None:
            received.append((method, params, rid))
            if rid is not None:
                conn.respond(rid, {"answered": method})

        conn.on_message = on_message
        try:
            await test(conn, received)
        finally:
            await conn.terminate()

    asyncio.run(main())


def sent(tmp_path: Path) -> list[JsonObject]:
    return [json.loads(line) for line in (tmp_path / "in.log").read_text().splitlines()]


def test_a_request_and_its_result(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        assert await conn.call("echo", {"a": [1]}, 5) == {"a": [1]}
        conn.notify("hello", {"b": None})
        await conn.call("echo", {}, 5)  # after the notification, in order

    run(tmp_path, test)
    assert sent(tmp_path)[0] == {
        "id": 1,
        "method": "echo",
        "params": {"a": [1]},
        "jsonrpc": "2.0",
    }
    assert sent(tmp_path)[1] == {
        "method": "hello",
        "params": {"b": None},
        "jsonrpc": "2.0",
    }


def test_an_error_answer_is_an_rpc_error(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        with pytest.raises(RpcError) as e:
            await conn.call("fail", {}, 5)
        assert (e.value.code, str(e.value), e.value.data) == (-32000, "nope", {"x": 1})

    run(tmp_path, test)


def test_the_agents_requests_and_notifications(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        answer = await conn.call("ask", {}, 5)
        assert answer == {
            "jsonrpc": "2.0",
            "id": 99,
            "result": {"answered": "client/q"},
        }
        await conn.call("note", {}, 5)
        assert received == [("client/q", {"a": 1}, 99), ("n/x", {}, None)]

    run(tmp_path, test)


def test_an_answer_of_the_wrong_shape_is_an_rpc_error(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        with pytest.raises(RpcError, match="doesn't fit ACP.*agentCapabilities"):
            await conn.request(InitializeResult, "wrongshape", {}, 5)
        result = await conn.request(InitializeResult, "echo", {"agentInfo": None}, 5)
        assert result == InitializeResult()

    run(tmp_path, test)


def test_what_is_not_json_rpc_goes_to_the_stderr_tail(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        await conn.call("garbage", {}, 5)
        assert "not a JSON-RPC message" in conn.stderr_tail()
        assert "not json" in conn.stderr_tail()
        assert received == []

    run(tmp_path, test)


def test_stderr_is_logged_and_kept(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        await conn.call("stderr", {}, 5)
        for _ in range(50):
            if conn.stderr:
                break
            await asyncio.sleep(0.02)
        assert conn.stderr_tail() == "oops"

    run(tmp_path, test)
    assert (tmp_path / "agent.log").read_text() == "oops\n"


def test_an_agent_that_exits_ends_open_requests(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        with pytest.raises(AgentExited, match="code 4"):
            await conn.call("die", {}, 5)
        assert await conn.closed == 4
        assert not conn.running
        with pytest.raises(AgentExited):
            conn.notify("late", {})
        conn.respond(1, {})  # answering a dead agent is no error

    run(tmp_path, test)


def test_a_request_that_takes_too_long(tmp_path: Path) -> None:
    async def test(conn: Connection, received: Received) -> None:
        with pytest.raises(RunnerError, match="didn't answer hang within 0 s") as e:
            await conn.call("hang", {}, 0.2)
        assert e.value.status == 504
        assert conn.pending == {}

    run(tmp_path, test)


def test_terminate_kills_an_agent_that_ignores_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rpc, "STOP_GRACE_SECONDS", 0.3)

    async def test(conn: Connection, received: Received) -> None:
        await conn.call("echo", {}, 5)  # the handler is installed
        start = time.monotonic()
        await conn.terminate()
        assert not conn.running
        assert await conn.closed == -9
        assert time.monotonic() - start < 3

    run(tmp_path, test, IGNORE_TERM="1")


def test_a_command_that_cannot_run(tmp_path: Path) -> None:
    async def main() -> None:
        with pytest.raises(RunnerError, match="can't run /nonexistent") as e:
            await Connection.spawn(["/nonexistent"], str(tmp_path), {}, tmp_path / "l")
        assert e.value.status == 500

    asyncio.run(main())
