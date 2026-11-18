"""A stand-in ACP agent for test_runner.py: newline-delimited JSON-RPC on stdio, no model.

What a prompt does depends on its text (see `turn`). FAKE_AUTH=fail-new makes session/new say the
sign-in is missing, as `agy acp` does; the prompt "auth" fails the turn the same way, as
claude-agent-acp does with a bad token. FAKE_STEERING=1 advertises steering. FAKE_LOG names a file
that gets every message the agent receives.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from typing import Any

lock = threading.Lock()
answers: dict[int, Any] = {}
answered = threading.Condition(lock)
next_id = 1000
cancelled = threading.Event()


def send(msg: dict[str, Any]) -> None:
    with lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def update(session: str, upd: dict[str, Any]) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": session, "update": upd},
        }
    )


def say(session: str, text: str) -> None:
    update(
        session,
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        },
    )


def ask(method: str, params: dict[str, Any]) -> Any:
    """A request to the client; waits for its answer."""
    global next_id
    with lock:
        rid = next_id
        next_id += 1
    send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    with answered:
        answered.wait_for(lambda: rid in answers)
        return answers.pop(rid)


def turn(rid: Any, session: str, text: str) -> None:
    def done(reason: str = "end_turn") -> None:
        send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": reason}})

    if text == "auth":
        say(session, "Failed to authenticate. API Error: 401")
        send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32000, "message": "Authentication required"},
            }
        )
        return
    if text == "exit":
        os._exit(3)
    if text == "env":
        keys = ("RUNNER_TEST_VAR", "ANTHROPIC_API_KEY", "PASSED_TOKEN")
        say(session, " ".join(f"{k}={os.environ.get(k, '-')}" for k in keys))
        return done()
    if text == "permission":
        update(
            session,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "t1",
                "title": "touch x",
                "kind": "execute",
                "status": "pending",
            },
        )
        result = ask(
            "session/request_permission",
            {
                "sessionId": session,
                "toolCall": {"toolCallId": "t1", "title": "touch x"},
                "options": [
                    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
                ],
            },
        )
        say(session, f"permission: {json.dumps(result['outcome'])}")
        return done()
    if text == "question":
        result = ask(
            "elicitation/create",
            {
                "sessionId": session,
                "mode": "form",
                "message": "Which colour?",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "colour": {"type": "string", "enum": ["red", "blue"]}
                    },
                },
            },
        )
        say(session, f"question: {json.dumps(result)}")
        return done()
    if text == "slow":
        cancelled.clear()
        say(session, "working")
        cancelled.wait(30)
        return done("cancelled" if cancelled.is_set() else "end_turn")
    if text == "later":
        say(session, "now")
        done()
        time.sleep(0.5)
        say(session, " and later")
        return
    say(session, f"echo: {text}")
    done()


def main() -> None:
    log = open(os.environ["FAKE_LOG"], "a") if os.environ.get("FAKE_LOG") else None
    for line in sys.stdin:
        msg = json.loads(line)
        if log:
            log.write(line)
            log.flush()
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method is None:
            with answered:
                answers[rid] = msg.get("result")
                answered.notify_all()
            continue
        if method == "initialize":
            meta = (
                {"steering": {"supported": True}}
                if os.environ.get("FAKE_STEERING")
                else None
            )
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "protocolVersion": 1,
                        "agentInfo": {"name": "fake", "version": "0"},
                        "agentCapabilities": {
                            "loadSession": True,
                            "sessionCapabilities": {"resume": {}},
                        },
                        "_meta": meta,
                    },
                }
            )
        elif method == "session/new":
            if os.environ.get("FAKE_AUTH") == "fail-new":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32000, "message": "Authentication required"},
                    }
                )
                continue
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "sessionId": str(uuid.uuid4()),
                        "models": {
                            "currentModelId": "big",
                            "availableModels": [
                                {"modelId": "big"},
                                {"modelId": "small"},
                            ],
                        },
                    },
                }
            )
        elif method == "session/resume":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "models": {
                            "currentModelId": "big",
                            "availableModels": [{"modelId": "small"}],
                        }
                    },
                }
            )
        elif method in ("session/set_mode", "session/set_model"):
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "_session/steering":
            send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": "injected"}})
        elif method == "session/prompt":
            text = "".join(block.get("text", "") for block in params["prompt"])
            threading.Thread(
                target=turn, args=(rid, params["sessionId"], text), daemon=True
            ).start()
        elif method == "session/cancel":
            cancelled.set()
        elif rid is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": method},
                }
            )


if __name__ == "__main__":
    main()
