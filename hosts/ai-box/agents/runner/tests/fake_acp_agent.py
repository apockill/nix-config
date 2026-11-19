"""A stand-in ACP agent for the tests: newline-delimited JSON-RPC on stdio, no model.

What a prompt does depends on its text (see `turn`). FAKE_AUTH=fail-new makes session/new say the
sign-in is missing, as `agy acp` does; the prompt "auth" fails the turn the same way, as
claude-agent-acp does with a bad token. FAKE_STEERING=1 advertises steering. FAKE_LOAD_ONLY=1
advertises session/load but not session/resume (as agy does) and replays a message on load.
FAKE_CONFIG_MODEL=1 offers models as a config option (as Claude does). FAKE_LOG names a file that
gets every message the agent receives.

Turns that fail as claude-agent-acp 0.108 fails them (v2/outcome.js, result-end.js): "limit <t>"
with a usage limit resetting at <t> (Unix seconds), "limit-unknown" with one that gives no reset time,
"fail" with a server error. "call <socket> <path>" has a tool's process (a grandchild) GET the
runner's API and say the answer's status line; "call-escaped" does it from a process that left
the agent's tree (double fork). "umask" says the agent's umask.
"""

from __future__ import annotations

import json
import os
import subprocess
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


def next_request_id() -> int:
    global next_id
    with lock:
        rid = next_id
        next_id += 1
    return rid


def ask(method: str, params: dict[str, Any]) -> Any:
    """A request to the client; waits for its answer (its result, or its error)."""
    rid = next_request_id()
    send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    with answered:
        answered.wait_for(lambda: rid in answers)
        return answers.pop(rid)


# A tool's process: GET a path of the runner's API on its socket, print the status line.
CALL = """
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
s.sendall(b"GET " + sys.argv[2].encode() + b" HTTP/1.1\\r\\nHost: x\\r\\nConnection: close\\r\\n\\r\\n")
out = b""
while chunk := s.recv(65536):
    out += chunk
head, _, body = out.partition(b"\\r\\n\\r\\n")
print(head.split(b"\\r\\n")[0].decode(), body.decode())
"""


def call_runner(sock: str, path: str, escaped: bool) -> str:
    if not escaped:
        run = [sys.executable, "-c", CALL, sock, path]
        return subprocess.run(run, capture_output=True, text=True).stdout.strip()
    # Leave the agent's tree: a child forks the caller and exits, so the caller is reparented.
    read, write = os.pipe()
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            os.dup2(write, 1)
            os.execv(sys.executable, [sys.executable, "-c", CALL, sock, path])
        os._exit(0)
    os.close(write)
    with os.fdopen(read) as f:
        return f.read().strip()


def turn_error(rid: Any, message: str, data: dict[str, Any]) -> None:
    error = {"code": -32603, "message": f"Internal error: {message}", "data": data}
    send({"jsonrpc": "2.0", "id": rid, "error": error})


def turn(rid: Any, session: str, text: str) -> None:
    def done(reason: str = "end_turn") -> None:
        send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": reason}})

    if text.startswith("limit"):
        data: dict[str, Any] = {"errorKind": "rate_limit"}
        if text != "limit-unknown":
            data["rateLimit"] = {
                "status": "rejected",
                "resetsAt": int(text.split()[1]),
                "rateLimitType": "five_hour",
                "utilization": 1.0,
            }
        return turn_error(rid, "You've hit your session limit · resets 7am", data)
    if text == "fail":
        return turn_error(rid, "API Error: 500", {"errorKind": "server_error"})
    if text.startswith("call"):
        _, sock, path = text.split()
        say(session, call_runner(sock, path, text.startswith("call-escaped")))
        return done()
    if text == "umask":
        mask = os.umask(0)
        os.umask(mask)
        say(session, f"umask {mask:04o}")
        return done()

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
    if text.startswith("say "):
        say(session, text[4:])
        return done()
    if text == "malformed":
        # A permission request without its options' ids: the runner refuses it.
        result = ask(
            "session/request_permission",
            {"sessionId": session, "toolCall": {"toolCallId": "t1"}, "options": [{}]},
        )
        say(session, f"malformed: {json.dumps(result)}")
        return done()
    if text == "unknown":
        result = ask("fs/read_text_file", {"sessionId": session, "path": "/x"})
        say(session, f"unknown: {json.dumps(result)}")
        return done()
    if text == "notify":
        send({"jsonrpc": "2.0", "method": "auth/status_update", "params": {"ok": True}})
        return done()
    if text == "withdraw":
        asked = next_request_id()  # not `rid`: done() answers the prompt's
        send(
            {
                "jsonrpc": "2.0",
                "id": asked,
                "method": "session/request_permission",
                "params": {
                    "sessionId": session,
                    "toolCall": {"toolCallId": "t2", "title": "rm y"},
                    "options": [
                        {"optionId": "allow", "name": "Allow", "kind": "allow_once"}
                    ],
                },
            }
        )
        time.sleep(0.3)
        send(
            {
                "jsonrpc": "2.0",
                "method": "$/cancel_request",
                "params": {"requestId": asked},
            }
        )
        return done()
    if text == "later":
        say(session, "now")
        done()
        time.sleep(0.5)
        say(session, " and later")
        return
    say(session, f"echo: {text}")
    done()


def model_option(current: str) -> dict[str, Any]:
    """Claude's way to offer models: a select config option of category "model"."""
    return {
        "id": "model",
        "name": "Model",
        "category": "model",
        "type": "select",
        "currentValue": current,
        "options": [
            {"value": "big", "name": "Big"},
            {"value": "small", "name": "Small"},
        ],
    }


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
                answers[rid] = msg.get("result", msg.get("error"))
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
                            "sessionCapabilities": (
                                {}
                                if os.environ.get("FAKE_LOAD_ONLY")
                                else {"resume": {}}
                            ),
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
            result: dict[str, Any] = {"sessionId": str(uuid.uuid4())}
            if os.environ.get("FAKE_CONFIG_MODEL"):
                result["configOptions"] = [model_option("big")]
            else:
                result["models"] = {
                    "currentModelId": "big",
                    "availableModels": [
                        {"modelId": "big", "name": "Big"},
                        {"modelId": "small", "name": "Small"},
                    ],
                }
            send({"jsonrpc": "2.0", "id": rid, "result": result})
        elif method == "session/resume":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "models": {
                            "currentModelId": "big",
                            "availableModels": [{"modelId": "small", "name": "Small"}],
                        }
                    },
                }
            )
        elif method == "session/load":
            # The conversation so far comes back as updates before the answer.
            say(params["sessionId"], "history")
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/set_config_option":
            option = model_option(params["value"])
            send({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": [option]}})
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
