# The agent runner

Every coding agent session on ai-box runs through this service: Claude Code (agent `claude`, the
default) and the Antigravity CLI (agent `antigravity`). It starts each session as the agent's own
ACP server ([Agent Client Protocol](https://agentclientprotocol.com), protocol version 1):
claude-agent-acp, or `agy acp`. It holds the connection and serves the API below. It wraps the
vendor harness and never replaces it: the agent's own loop, prompts, tools, skills, subagents and
transcript are unchanged, and the runner only starts, watches, steers and stops it.

- Service: `agent-runner.service`, a **user** service of the agent's user (`systemctl --user
  status agent-runner`, running `agent serve`), separate from the Hermes gateway, so a gateway
  restart leaves sessions running. Switches don't restart it; `agent restart` (`POST
  /v1/restart`) applies a new version: the service exits with code 75 and systemd starts it again.
- CLI: `agent` (`agent --help`; see [CLI](#cli)): sessions and jobs. `cc` is another name for it,
  kept while the Hermes skills say `cc` and jobs from before the runner still run in tmux
  (../../hermes/cc).
- Code: the package `agent_runner/`, one concern per module (its `__init__.py` lists them), stdlib
  Python only, every message and record a typed dataclass checked strictly where JSON comes in
  (`schema.py`). Tests in `tests/`: one module per source module, the end-to-end tests
  (`test_e2e.py`) against a stand-in agent (`fake_acp_agent.py`), and live smoke tests
  (`test_live.py`, skipped without a sign-in). The nix build runs `mypy --strict` and the tests.
  Vendor settings (command, environment, mode, transcript path) come from the vendor directories
  (`../claude`, `../antigravity`) through `aiBox.agents.runner.agents`.
- State: `/var/lib/hermes/agent-runner/sessions/<name>/`: `session.json` (the record),
  `events.jsonl` (every event), `agent.log` (the agent's stderr).

No fallbacks: if an agent can't start, or its sign-in is missing or expired, the session goes to
`failed` with the reason, the call that started it fails with that reason, and Alex gets a Discord
message (`notify-alex`). The same happens when an agent process dies unexpectedly.

## Transport

HTTP/1.1 on the unix socket `/var/lib/hermes/agent-runner/sock` (nix: `aiBox.agents.runner.socket`),
reachable only by the agent's user (`hermes`). There's no auth beyond that: anything that can open
the socket can drive every session. A service that runs as another user, or a page in a browser,
needs a bridge of its own.

One request per connection (`Connection: close`). Bodies are JSON (`Content-Type:
application/json`), checked strictly: a field the call doesn't know, or a value of the wrong type,
is a `400` naming the field (`null` is the same as leaving an optional field out). Errors are
`{"error": "<what went wrong, for a human>"}` with a status:

| status | meaning |
|---|---|
| 400 | a bad request (the message says which field), a body that isn't JSON, a query parameter that isn't a number |
| 404 | no such session / request / path |
| 409 | the session's state doesn't allow it (e.g. `send` to a stopped session, `start` over a live one) |
| 502 | the agent failed: couldn't start, sign-in missing/expired, died (the session is `failed`; `reason` says why) |
| 504 | the agent didn't answer a setup request in time |

```sh
curl --unix-socket /var/lib/hermes/agent-runner/sock http://runner/v1/sessions
```

(The host part of the URL is ignored.)

## Sessions

A session has a **name** (`^[a-z0-9][a-z0-9-]{0,62}$`; `agent start` makes it from a job title), an
**agent**, a **folder** (`dir`), and the agent's own session id once it has started
(`agent_session_id`). A session stays on record after it ends (`stopped`, `failed`) until a new
session takes its name, or for 30 days.

### States

| state | meaning |
|---|---|
| `starting` | the agent process is starting, or a session is being created/resumed |
| `running` | a turn is in progress |
| `waiting` | the agent waits for an answer: a permission request or a question (see `pending`) |
| `idle` | the agent is up and between turns (it may still send updates, e.g. agy finishing subagent work after `end_turn`) |
| `offline` | no agent process (the runner restarted, or a reboot); the next `send` resumes the agent's session |
| `failed` | the agent couldn't start, its sign-in failed, or it died; `reason` says why. A `send` retries by resuming the session when one was created |
| `stopped` | ended by `stop`; final |

### The session object

`GET /v1/sessions/{name}` (and most POSTs) return:

```json
{
  "name": "nix-config-runner",
  "agent": "claude",
  "dir": "/var/lib/hermes/worktrees/nix-config-runner",
  "state": "idle",
  "reason": null,
  "model": "haiku",
  "mode": null,
  "origin": "job: Runner smoke test",
  "env": ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"],
  "session_meta": null,
  "agent_session_id": "9c329bf9-1172-4864-828c-67b80f906603",
  "transcript": "/var/lib/hermes/.claude/projects/-var-lib-hermes-worktrees-nix-config-runner/9c329bf9-1172-4864-828c-67b80f906603.jsonl",
  "title": "Runner smoke test",
  "created_at": 1795000000.0,
  "updated_at": 1795000042.5,
  "turns": 1,
  "alive": true,
  "last_event_at": 1795000042.5,
  "pending": [],
  "queued": [],
  "last_message": "Done: ..."
}
```

- `env` lists the names of the extra variables given at start (values aren't reported).
- `transcript` is the vendor's own transcript file: the complete history, written live by the
  agent (Claude: `~/.claude/projects/<folder>/<id>.jsonl`, subagents in `<id>/subagents/`;
  Antigravity: `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl`,
  subagents in their own `brain/<sub-id>/`). The runner's events are the live channel; the
  transcript is the record.
- `title`: the agent's own title for the conversation, once it has one.
- `pending`: the open permission requests and questions, each the event that announced it (below).
- `queued`: messages waiting for the running turn to end (agents without steering).
- `last_message`: the agent's text since the last prompt.
- `alive`: whether the agent's process is up. `last_event_at`: when the session's latest event
  happened; with `state` it tells a session that's working (`running`, or `idle` with recent
  events: agy finishing subagent work) from one that has gone quiet.

`GET /v1/sessions` returns `{"sessions": [...]}` with the same fields except `pending` (a count),
`queued` and `last_message`, oldest first.

`GET /v1/agents` returns `{"default": "claude", "agents": ["antigravity", "claude"]}`.

### Start: `POST /v1/sessions`

```json
{
  "name": "sculpt-vase",
  "dir": "/var/lib/hermes/sites/apps/sculpt-studio/projects/vase",
  "task": "the first message",
  "agent": "claude",
  "model": "opus",
  "mode": null,
  "resume": null,
  "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"},
  "origin": "sculpt: vase",
  "session_meta": {"claudeCode": {"options": {"disallowedTools": ["WebFetch"]}}}
}
```

Only `name` and `dir` (an existing folder, absolute) are required.

- `agent`: `claude` (default) or `antigravity`.
- `task`: the first message. Without it the session starts `idle`.
- `model`: one the agent offers. Claude takes its aliases (`haiku`, `sonnet`, `opus`) or a full
  model id; Antigravity takes one of its ids (e.g. `gemini-3.8-flash-low`, the cheapest). A model
  the agent rejects fails the start. Omitted: the agent's default.
- `mode`: the agent's permission mode (session/set_mode): Claude `default`, `acceptEdits`, `plan`,
  `auto`, `bypassPermissions` (default: `auto`, from its settings). Antigravity sessions are
  always set to `auto` unless this says otherwise: in its own default mode its prompt and tools
  differ from the terminal UI's.
- `resume`: an agent session id to continue (session/resume) instead of creating one, e.g. from an
  earlier session's `agent_session_id`.
- `env`: extra environment for the agent process. Variables that would switch an agent to metered
  billing (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`) are
  refused. The agent's sign-in comes from the runner (Claude: the subscription token).
- `origin`: free text saying what started the session (`job: <title>`, `sculpt: <project>`), for lists.
- `session_meta`: passed as `_meta` of session/new (and resume): vendor options. For Claude,
  `{"claudeCode": {"options": {...}}}` takes Claude Agent SDK options such as `disallowedTools`
  (merged with the adapter's own) or `maxTurns`.

What happens: the folder is marked trusted for Claude (otherwise Claude ignores the project's
permission allow rules), the agent starts, the session is created, mode and model are set, and the
task is sent. The call returns `201` with the session once the agent has shown signs of life
(first update plus up to 3 s, or 30 s at most), so a sign-in rejected on the first request fails
the start itself (`502`). A name that belongs to a session that isn't `stopped` or `failed` is a
`409`.

### Send: `POST /v1/sessions/{name}/send`

`{"text": "..."}` → `{"delivery": "sent" | "steered" | "queued"}`

- `sent`: it started a new turn.
- `steered`: a turn was running and the agent took the message into it (Claude).
- `queued`: a turn was running and the agent can't be steered (Antigravity): it's sent when the
  turn ends.

An `offline` session (or a `failed` one that had started) is resumed first. `stopped` is a `409`.

### Cancel: `POST /v1/sessions/{name}/cancel`

Ends the running turn (session/cancel), cancels open permission requests and questions, and drops
queued messages. The session stays up (`idle`).

### Stop: `POST /v1/sessions/{name}/stop`

`{"reason": "..."}` (optional). Ends the agent process; the session becomes `stopped` and stays on
record (events, transcript path).

### Answer a request: `POST /v1/sessions/{name}/requests/{request_id}`

Request ids come from the `permission` and `question` events and from `pending`. Ids start with
`p` (permission) or `q` (question).

- Permission: `{"option_id": "<one of the event's options[].optionId>"}`, or `{"cancel": true}`.
- Question (form elicitation; this is how Claude's AskUserQuestion reaches a UI):
  `{"action": "accept", "content": {"<field>": <value>, ...}}` with the fields of the event's
  `schema`, or `{"action": "decline"}`, or `{"action": "cancel"}`.

Returns the session. An id that isn't open is a `404`.

### Restart the service: `POST /v1/restart`

`{"restarting": true}`, then the service shuts down (every agent process ends; sessions become
`offline`) and systemd starts it again as its current version, about 5 s later. This is how a new
runner from a switch takes effect.

### Output as text: `GET /v1/sessions/{name}/output?lines=40`

`{"lines": [...]}`: the last `lines` lines of a plain-text rendering of the session's events
(prompts as `> ...`, the agent's text, `[tool] <title>`, `[permission p1] ...`, `[question q1]
...` with each field and its choices, `[turn ended: <reason>]`, state changes). `lines=0` gives
none. This is what `agent peek` prints.

## CLI

`agent <verb>`; `agent <verb> --help` for each. Every verb is a call or two of the API above, plus
the job layer:

| verb | does |
|---|---|
| `start <title> <dir> [<task-file>]` | start a **job**: a session named after the title (lowercase letters, digits and dashes: `"Sites: gate speed 2"` → `sites-gate-speed-2`), working in `<dir>`, its first message the task file (or `--task TEXT`; neither: it starts `idle`). It gets the starter's `PATH` and `TMPDIR`. Prints `session: <name>` first (tools parse that line), then the session. Options: `--agent`, `--model`, `--mode`, `--resume AGENT_SESSION_ID`, `--env NAME=VALUE`, `--origin` (default `job: <title>`), `--session-meta JSON` |
| `send <name> <message...>` / `send --file F <name>` | a message: `sent`, `steered` or `queued` |
| `peek <name> [lines]` | the output as text (default 40 lines) |
| `answer <name> <request> [value]` | a permission (`p1`: an option id, or `--cancel`) or a question (`q1`: the form's fields as a JSON object, or `--decline`, `--cancel`) |
| `wait <name>` | block until the job needs its starter; prints one of `MARKER <line>` (a line matching `--marker`, default `^[A-Z][A-Z0-9-]*-(DONE\|NEED-LIVE\|RESTART-PLEASE)(:\|\s*$)`; lines there before it started don't count), `WAITING` (then the open requests and the last output), `IDLE (<state>, quiet <n>s)` (no turn running and no event for `--idle` seconds, default 300), `ENDED <state>: <reason>` or `ENDED: no session <name>`, `TIMEOUT` (`--timeout`, default 4 h); exits 0 |
| `list [--json]` | the sessions, oldest first, and the jobs still in tmux |
| `status <name> [--json]`, `transcript <name>` | the session; its vendor transcript's path |
| `cancel <name>`, `stop <name> [--reason R]` | end the turn; end the session |
| `events [<name>] [--since N] [-f]` | events as JSON lines |
| `restart`, `serve` | restart the service; run it |

Jobs started in tmux before the runner (cc-tmux) are handed to `cc-tmux` by `send`, `peek` and
`stop` until they end, and `list` shows them.

## Events

`GET /v1/sessions/{name}/events?since=<seq>&follow=1` and `GET /v1/events?since=<seq>&follow=1`
(all sessions). The response is newline-delimited JSON (`application/x-ndjson`), one event per
line: first every stored event after `since` (default 0), then, with `follow=1`, live events
until the client disconnects. Without `follow` the response ends after the stored ones. On
`/v1/events` the stored history is the last 20,000 events of all sessions; a session's own
endpoint reads its whole log.

Every event has:

```json
{"seq": 1234, "ts": 1795000000.123, "session": "<name>", "kind": "<kind>", ...}
```

`seq` increases across all sessions, so a client resumes with `since=<last seq it saw>`. While
following, a `{"kind": "heartbeat", "ts": ..., "seq": <the runner's latest seq>}` line comes every
15 s when nothing else does; it isn't stored and has no `session`.

| kind | fields | meaning |
|---|---|---|
| `state` | `state`, `reason` | the session's state changed (see States) |
| `session` | `agent_session_id`, `transcript`, `agent_info` | the agent's session was created or resumed |
| `prompt` | `text`, `delivery` (`sent`, `steered`, `queued`) | a message was given to the agent |
| `update` | `update` | an ACP `session/update`, as the agent sent it (below) |
| `turn_end` | `stop_reason` | the turn ended: `end_turn`, `cancelled`, `max_tokens`, `refusal`, ... |
| `permission` | `request_id`, `title`, `tool_call_id`, `options` | the agent asks to run a tool; `options` are ACP permission options (`optionId`, `name`, `kind`: `allow_once`, `allow_always`, `reject_once`, `reject_always`) |
| `question` | `request_id`, `message`, `mode`, `schema`, `url` | the agent asks the user (form elicitation): `schema` is a JSON Schema object whose `properties` are the fields; choices are `enum` or `oneOf`/`anyOf` of `{const, title}` |
| `resolved` | `request_id`, `by` (`client`, `agent`, `runner`), `answer`, `reason` | a permission or question was answered, withdrawn by the agent, or dropped (stop, the agent exited) |
| `cancel` | | `cancel` was sent |
| `error` | `message` | something failed; for a failed session also the reason |
| `notified` | `message`, `ok`, `error` | Alex was told about a failure (`notify-alex`), or telling him failed (`ok: false`) |
| `notification` | `method`, `params` | any other notification from the agent (e.g. `auth/status_update`) |

`update` carries the agent's ACP session update unchanged; `update.sessionUpdate` says which:

- `agent_message_chunk` / `agent_thought_chunk` / `user_message_chunk`: `content` (`{"type":
  "text", "text": ...}`), streamed piece by piece. Concatenate consecutive chunks.
- `tool_call`: a new tool call: `toolCallId`, `title`, `kind` (`read`, `edit`, `execute`,
  `search`, `fetch`, `think`, `other`...), `status`, `rawInput`, `locations`. A subagent's tool
  calls arrive too; Claude marks them with `_meta.claudeCode.parentToolUseId`.
- `tool_call_update`: `toolCallId` plus whatever changed: `status` (`pending`, `in_progress`,
  `completed`, `failed`), `content` (text, diffs), `rawOutput`.
- `plan`: `entries` (`content`, `status`, `priority`): the agent's to-do list.
- `usage_update`: `used`, `size` (context tokens), with Claude's model and rate-limit state in
  `_meta`.
- `available_commands_update`, `current_mode_update`, `config_option_update`,
  `session_info_update` (`title`).

See the ACP schema (agentclientprotocol.com, "Prompt Turn" and "Tool Calls") for the full shapes.
A UI that only shows text and tool calls needs `agent_message_chunk`, `tool_call` and
`tool_call_update`.

## Behaviour worth knowing

- **One process per session**, kept between turns. The runner keeps listening after `end_turn`:
  Antigravity finishes subagent work on its own and streams more updates without a prompt. Those
  arrive as ordinary `update` events while the session is `idle`.
- **Subagents** are the agents' built-in ones (Claude's Agent tool, Antigravity's
  `invoke_subagent`); nothing to configure. Their output shows up as tool calls and in the
  vendor transcript.
- **Restarts**: stopping the runner (or a reboot) ends every agent process; their sessions become
  `offline` and the next `send` resumes them (session/resume, same transcript). A turn that was
  running is lost. The event logs keep their history.
- **Permissions**: Claude runs in its `auto` mode and Antigravity in `auto`, so most tool calls
  don't ask. When one does, the session is `waiting` until a client answers. Over ACP,
  Antigravity ignores its `settings.json` permission rules (a known gap, accepted for now).
- **Sign-in**: Claude uses the agent's subscription token (`CLAUDE_CODE_OAUTH_TOKEN`, from the
  secrets file); without it a Claude session fails to start rather than use some other login.
  Antigravity uses the agent's Google sign-in in `~/.gemini` (`antigravity-login` restores it from
  the vault). A rejected sign-in fails the session, with the reason, and notifies Alex.
