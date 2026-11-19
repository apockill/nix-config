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
- CLI: `agent` (`agent --help`; see [CLI](#cli)): sessions and jobs. It is the only way to run a
  coding job on ai-box.
- Code: the package `agent_runner/`, one concern per module (its `__init__.py` lists them), on the
  ACP Python SDK (`agent-client-protocol`: the connection and the protocol's models), pydantic
  (every record and body, checked strictly where it comes in), Starlette and uvicorn (the API) and
  httpx (the CLI). Tests in `tests/`: one module per source module, the end-to-end tests
  (`test_e2e.py`) against a stand-in agent (`fake_acp_agent.py`), and live smoke tests
  (`test_live.py`, skipped without a sign-in). The nix build runs `mypy --strict` and the tests.
  Vendor settings (command, environment, mode, transcript path) come from the vendor directories
  (`../claude`, `../antigravity`) through `aiBox.agents.runner.agents`.
- State: `/var/lib/hermes/agent-runner/sessions/<name>/`: `session.json` (the record),
  `events.jsonl` (every event), `agent.log` (the agent's stderr).

**Vendor defaults.** Alex: "I just want the agent behavior to be the same for all agents...
Claude Code is optimized for the best agentic experience. I want the best agentic experience, and
only when we want to change from the defaults because we have an engineering reason, such as in
Sculpt, do we diverge from that." So the runner applies no behaviour overrides of its own: no
compaction window, model, effort, mode or tool changes. A session gets the vendor's defaults
unless its caller sets something for an engineering reason it states (Sculpt's builders: a 200k
compaction window, SCBUILD-15; their tool fence). The few things the vendor directories set are
each there for a stated reason (Antigravity's `auto` mode: over ACP its default mode has a
different prompt and tools from its own terminal UI; Claude's folder trust: what accepting its
trust dialog does). Anything that would compromise agent quality needs Alex's skeptical review
first.

No fallbacks: if an agent can't start, or its sign-in is missing or expired, the session goes to
`failed` with the reason, the call that started it fails with that reason, and Alex gets a Discord
message (`notify-alex`). The same happens when an agent process dies unexpectedly. Alex is also
told, once each:
- when an agent hits the account's **usage limit** (once per reset, whichever session hits it;
  the session goes `limited`, see States);
- when a session's turns fail **3 times in a row** for any other reason;
- when a permission or question has waited **30 minutes** with no answer
  (`aiBox.agents.runner.notifyUnansweredAfter`);
- when a runner **stop or restart cuts turns short** (named), and when a session's record
  **can't be read** (it stays listed as `failed`, saying why).

If telling Alex fails, the session's `notify_error` says why (`agent list --json`; the daily
usage digest, `../drift`, reports it).

## Transport

HTTP/1.1 on the unix socket `/var/lib/hermes/agent-runner/sock` (nix: `aiBox.agents.runner.socket`),
mode `0600`: the agent's user (`hermes`) only. The service runs with `UMask=0077`, so its records
and event logs (which hold tool outputs and file contents) are that user's only too; the agents
themselves keep a user service's `0022` (they write files in repositories that others read). A
service that runs as another user, or a page in a browser, needs a bridge of its own.

**From inside a session**, the API is refused (`403`) unless the session was started with
`allow_runner`. Every session runs as the same user, so the runner tells a session's processes
from Hermes by the calling process (the socket's peer pid, `agent_runner/peers.py`): a process
descended from a session's agent is that session; one that left that tree still carries the
session's marker (`AGENT_RUNNER_SESSION`, `AGENT_RUNNER_OF`, set for every agent); and in the
service, any process in the service's own cgroup is an agent's, marker or not. So a fenced
session (a Sculpt builder in `bypassPermissions`) can't start an unfenced one, or answer, send to
or stop another session, with `agent`, `curl --unix-socket` or anything else.

One request per connection (`Connection: close`). Bodies are JSON (`Content-Type:
application/json`), checked strictly: a field the call doesn't know, or a value of the wrong type,
is a `400` naming the field (`null` is the same as leaving an optional field out). Errors are
`{"error": "<what went wrong, for a human>"}` with a status (a `429` adds `"resets_at"`):

| status | meaning |
|---|---|
| 400 | a bad request (the message says which field), a body that isn't JSON, a query parameter that isn't a number |
| 404 | no such session / request / path |
| 403 | the caller is inside a session that may not use the runner (above) |
| 409 | the session's state doesn't allow it (e.g. `send` to a stopped session, `start` over a live one, `restart` while turns run) |
| 429 | the agent hit the account's usage limit: the body has `resets_at` (Unix seconds) when the agent said |
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
| `limited` | the last turn hit the account's usage limit: `limit` says until when (`resets_at`) and which; `send` is refused (`429`) until then, and the session goes `idle` by itself at the reset. Read from the agent's error data (claude-agent-acp's `errorKind: "rate_limit"`, `rateLimit.resetsAt`), never from its text |
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
  "env": ["PATH", "TMPDIR"],
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
  "limit": null,
  "compact_window": null,
  "allow_runner": false,
  "failed_turns": 0,
  "misfits": 0,
  "notify_error": null,
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
- `queued`: messages waiting for the running turn to end (agents without steering). They're in
  the record, so a runner restart keeps them, and they go before a newer message.
- `limit`: the usage limit the last turn hit, `{"resets_at": <Unix seconds or null>, "kind":
  "five_hour"}`; cleared by a turn that ends well.
- `compact_window`: the context size (tokens) at which the agent compacts the conversation, when
  the start's `env` set one (Claude: `CLAUDE_CODE_AUTO_COMPACT_WINDOW`); null means the agent's own
  default.
- `allow_runner`: whether the session's own processes may use this API.
- `failed_turns`: turns that failed in a row; `misfits`: messages from the agent that didn't fit
  ACP (each also an `error` event); `notify_error`: why telling Alex last failed, if it did.
- `last_message`: the agent's text since the last prompt.
- `alive`: whether the agent's process is up. `last_event_at`: when the session's latest event
  happened; with `state` it tells a session that's working (`running`, or `idle` with recent
  events: agy finishing subagent work) from one that has gone quiet.

`GET /v1/sessions` returns `{"sessions": [...]}` with the same fields except `pending` (a count)
and `last_message`, oldest first.

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
  "session_meta": {"claudeCode": {"options": {"disallowedTools": ["WebFetch"]}}},
  "allow_runner": false
}
```

Only `name` and `dir` (an existing folder, absolute) are required.

- `agent`: `claude` (default) or `antigravity`.
- `task`: the first message. Without it the session starts `idle`.
- `model`: one the agent offers. Claude takes its aliases (`haiku`, `sonnet`, `opus`) or a full
  model id; Antigravity takes one of its ids (e.g. `gemini-3.8-flash-low`, the cheapest). A model
  the agent rejects fails the start. Omitted: the agent's default.
- `mode`: the agent's permission mode (session/set_mode): Claude `default`, `acceptEdits`, `plan`,
  `auto`, `bypassPermissions` (default: `auto`, claude-agent-acp's own default, which falls back to
  `default` for a model without auto mode; the canary checks it daily, `../drift`). Antigravity sessions are
  always set to `auto` unless this says otherwise: in its own default mode its prompt and tools
  differ from the terminal UI's.
- `resume`: an agent session id to continue (session/resume) instead of creating one, e.g. from an
  earlier session's `agent_session_id`.
- `env`: extra environment for the agent process. Variables that would move an agent off its
  subscription are refused: Claude's `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
  `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`,
  `CLAUDE_CODE_USE_FOUNDRY`; Antigravity's `GEMINI_API_KEY`, `GOOGLE_API_KEY`. The agent's sign-in
  comes from the runner (Claude: the subscription token). `CLAUDE_CODE_AUTO_COMPACT_WINDOW` here
  sets the session's compaction window (a whole number of tokens; without it, Claude Code's own). `ENABLE_CLAUDEAI_MCP_SERVERS=false` leaves out the
  account's claude.ai connectors (Behaviour).
- `allow_runner`: let the session's own processes use this API (start, send to, answer, stop
  sessions). Off by default; give it only to sessions that start jobs of their own.
- `origin`: free text saying what started the session (`job: <title>`, `sculpt: <project>`), for lists.
- `session_meta`: passed as `_meta` of session/new (and resume): vendor options. For Claude,
  `{"claudeCode": {"options": {...}}}` takes Claude Agent SDK options such as `disallowedTools`
  (merged with the adapter's own) or `maxTurns`.

What happens: the folder is marked trusted for Claude (otherwise Claude ignores the project's
permission allow rules), the agent starts, the session is created, mode and model are set, and the
task is sent. The call returns `201` with the session once the agent has shown signs of life
(first update plus up to 3 s, or 30 s at most), so a sign-in rejected on the first request fails
the start itself (`502`), and a task refused at the usage limit fails it with a `429` and
`resets_at` (the session stays, `limited`: send it a message after the reset, or stop it). A name
that belongs to a session that isn't `stopped` or `failed` is a `409`.

### Send: `POST /v1/sessions/{name}/send`

`{"text": "..."}` → `{"delivery": "sent" | "steered" | "queued"}`

- `sent`: it started a new turn.
- `steered`: a turn was running and the agent took the message into it (Claude).
- `queued`: a turn was running and the agent can't be steered (Antigravity): it's sent when the
  turn ends.

An `offline` session (or a `failed` one that had started) is resumed first; messages still queued
from before go first, then this one (`queued`). `stopped` is a `409`; a `limited` one is a `429`
with `resets_at` until the reset (a limit without a reset time lets the send try).

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
runner from a switch takes effect. While a turn runs or a request waits, it's a `409` naming the
sessions, unless `{"force": true}`: their turns are lost (Alex is told which), their queued
messages kept.

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
| `start <title> <dir> [<task-file>]` | start a **job**: a session named after the title (lowercase letters, digits and dashes: `"Sites: gate speed 2"` → `sites-gate-speed-2`), working in `<dir>`, its first message the task file (or `--task TEXT`; neither: it starts `idle`). It gets the starter's `PATH` and `TMPDIR`. Once it has started, prints `session: <name>` first (tools parse that line), then the session; a failed start prints the runner's error instead (and `resets_at: <t>` at the usage limit) and exits 1. Options: `--agent`, `--model`, `--mode`, `--resume AGENT_SESSION_ID`, `--env NAME=VALUE`, `--origin` (default `job: <title>`), `--session-meta JSON`, `--allow-runner` |
| `send <name> <message...>` / `send --file F <name>` | a message: `sent`, `steered` or `queued` |
| `peek <name> [lines]` | the output as text (default 40 lines) |
| `answer <name> <request> [value]` | a permission (`p1`: an option id, or `--cancel`) or a question (`q1`: the form's fields as a JSON object, or `--decline`, `--cancel`) |
| `wait <name>` | block until the job needs its starter; prints one of `WAITING` (then the open requests and the last output), `MARKER <line>` (a line matching `--marker`, default `^[A-Z][A-Z0-9-]*-(DONE\|NEED-LIVE\|RESTART-PLEASE)(:\|\s*$)`, printed since the session's last prompt: one printed before the waiter started counts, one from an earlier turn doesn't, and prompts are never searched), `LIMITED <resets_at> <what>` (the usage limit; `resets_at` in Unix seconds or `unknown`), `IDLE (<state>, quiet <n>s)` (no turn running and no event for `--idle` seconds, default 300), `ENDED <state>: <reason>` or `ENDED: no session <name>`, `TIMEOUT after <n>s: <name> is still <state>; ...` (`--timeout`, default 4 h: the job runs on and nothing watches it, so wait again or stop it); exits 0. It reconnects while the runner restarts (up to 120 s) |
| `list [--json]` | the sessions, oldest first |
| `status <name> [--json]`, `transcript <name>` | the session; its vendor transcript's path |
| `cancel <name>`, `stop <name> [--reason R]` | end the turn; end the session |
| `events [<name>] [--since N] [-f]` | events as JSON lines |
| `restart [--force]`, `serve` | restart the service (refused while turns run, unless forced); run it |


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
| `error` | `message`, `error_kind`, `data` | something failed; for a failed session also the reason. A failed turn carries the agent's own `error_kind` and error `data` when it gave them (claude-agent-acp: `rate_limit`, `overloaded`, `server_error`, ...; at a usage limit `data.rateLimit.resetsAt`) |
| `notified` | `message`, `ok`, `error` | Alex was told something (`notify-alex`), or sending it failed (`ok: false`) |
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
  running is lost, and Alex is told which; queued messages are kept. The event logs keep their
  history.
- **Compaction**: the runner sets no compaction window, so Claude sessions compact at Claude
  Code's own default, near the model's full window. A caller may set one per session (`env`
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; Sculpt's builders use 200,000, SCBUILD-15). A smaller window
  costs agent quality (the summary loses detail), so a default one needs Alex's review.
- **claude.ai connectors**: a Claude session gets the account's claude.ai connectors as deferred
  MCP tools (`mcp__claude_ai_Gmail__*`, `..._Google_Calendar__*`, `..._Google_Drive__*`,
  `..._Claude_Docs__*`: reading and sending mail drafts, trashing messages, creating and deleting
  calendar events, reading and creating Drive files and docs), once they connect in the
  background. For one session, start it with `env` `ENABLE_CLAUDEAI_MCP_SERVERS=false` (or deny
  `mcp__claude_ai_*` in `session_meta`'s `disallowedTools`); for every Claude session, set that
  variable in `../claude`'s agent `env`, or `disableClaudeAiConnectors` in its settings.
- **Permissions**: Claude runs in its `auto` mode and Antigravity in `auto`, so most tool calls
  don't ask. When one does, the session is `waiting` until a client answers. Over ACP,
  Antigravity ignores its `settings.json` permission rules (a known gap, accepted for now).
- **Sign-in**: Claude uses the agent's subscription token (`CLAUDE_CODE_OAUTH_TOKEN`, from the
  secrets file); without it a Claude session fails to start rather than use some other login.
  Antigravity uses the agent's Google sign-in in `~/.gemini` (`antigravity-login` restores it from
  the vault). A rejected sign-in fails the session, with the reason, and notifies Alex.
