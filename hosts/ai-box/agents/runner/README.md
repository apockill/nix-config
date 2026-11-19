# The agent runner

Every coding agent session on ai-box runs through this service: Claude Code (agent `claude`, the
default) and the Antigravity CLI (`antigravity`). It starts each session as the agent's own ACP
server ([Agent Client Protocol](https://agentclientprotocol.com)), claude-agent-acp or `agy acp`,
holds the connection, and serves a local API. It wraps the vendor harness and never replaces it:
the agent's loop, prompts, tools, skills, subagents and transcript are its own, and the runner only
starts, watches, steers and stops it. Sessions outlive their callers: Hermes and Sculpt start
jobs, and Alex watches and steers them in the live view.

- **Use it** with `agent` (`agent --help`), the only way to run a coding job. The API's routes,
  bodies and statuses: `agent_runner/api_types.py` (`GET /v1/openapi.json`); events: `events.py`.
- **Service:** `agent-runner.service`, a *user* service apart from the Hermes gateway, so a gateway
  restart leaves sessions running. A switch doesn't restart it; `agent restart` does.
- **State:** `/var/lib/hermes/agent-runner/sessions/<name>/`: `session.json`, `events.jsonl`,
  `agent.log` (the agent's stderr).

**Vendor defaults.** Alex: "I want the best agentic experience, and only when we want to change
from the defaults because we have an engineering reason, such as in Sculpt, do we diverge from
that." The runner sets no compaction window, model, effort, mode or tools of its own; a caller
may, for a reason it states (Sculpt's builders: 200k compaction, SCBUILD-15, and a tool fence).
Anything that could cost agent quality needs Alex's review first.

**No fallbacks.** An agent that can't start, a missing or expired sign-in, or a dying agent fails
the session with the reason, fails the call, and tells Alex (`notify-alex`). He is also told, once
each: at a usage limit (once per reset), after 3 failed turns in a row, when a permission or
question waits 30 minutes, when a stop or restart cuts turns (named), and when a record can't be
read. A failure to tell him is in the session's `notify_error` and the journal.

## Transport

HTTP/1.1 on the unix socket `/var/lib/hermes/agent-runner/sock`, mode `0600`: the agent's user
only. The service runs with `UMask=0077`, so records and event logs (tool outputs, file contents)
are that user's only too; older files are made so at start, and one that can't be stops the
runner. The agents keep `0022`, since they write files in repositories others read. Bodies are
checked strictly: an unknown field or a wrong type is a `400` naming it.

**From inside a session the API is refused (`403`)** unless the session was started with
`allow_runner`. Every session runs as the same user, so the runner tells who calls from the
socket's peer pid (`peers.py`): a process descended from a session's agent, one carrying the
session's marker (`AGENT_RUNNER_SESSION`), or any process in the service's own cgroup. So a fenced
session (a Sculpt builder) can't start an unfenced one, or steer or stop another, by any client.

## States

| state | meaning |
|---|---|
| `starting` | the agent process is starting, or its session is being created or resumed |
| `running` | a turn is in progress |
| `waiting` | the agent waits for an answer to a permission request or a question (`pending`) |
| `idle` | the agent is up between turns (it may still send updates: agy finishing subagent work) |
| `limited` | the last turn hit the usage limit: `limit` says which and until when; sends get `429` until then, and the session goes `idle` by itself at the reset |
| `offline` | no agent process (a runner restart, a reboot); the next send resumes the agent's session |
| `failed` | the agent couldn't start, its sign-in failed, or it died; `reason` says why; a send retries by resuming, once a session was created |
| `stopped` | ended by `stop`; final. Ended sessions stay on record 30 days, or until the name is reused |

## Behaviour worth knowing

- **Restarts lose no session.** A restart or reboot ends the agent processes, not their sessions;
  the next message resumes each (session/resume, same transcript). A turn that was running is lost
  and Alex is told which; `agent restart` refuses while turns run unless forced. Queued messages
  (sent while an unsteerable agent's turn ran) are in the record and survive.
- **Usage limits are read from the agent's error data** (claude-agent-acp's `errorKind:
  "rate_limit"`, `rateLimit.resetsAt`), never from its text. `limit` stays in the record until a
  turn succeeds, so an offline session still shows it.
- **A start waits for signs of life** (the first update plus up to 3 s, at most 30 s), so a rejected
  sign-in or model fails the start, not a later turn.
- **The transcript is the record**, the events the live channel: `transcript` is the vendor's own
  file, subagents included. One agent process serves a session across turns.
- **No claude.ai connectors:** the runner's subscription token is inference-only (no
  `user:mcp_servers` scope), so its Claude sessions load none of the account's connectors (Gmail,
  Calendar, Drive). `ENABLE_CLAUDEAI_MCP_SERVERS=false` makes sure for one session (Sculpt's
  builders set it), in case the token ever changes.
- **Folder trust:** a Claude session's folder is marked trusted at start, as accepting Claude's
  trust dialog would; otherwise Claude ignores the project's permission allow rules.
- **Permissions:** both agents run in `auto`, so few tool calls ask (the session is `waiting` until
  one is answered). Over ACP Antigravity ignores its `settings.json` rules (a known, accepted gap).
- **Sign-in:** Claude uses the subscription token (`CLAUDE_CODE_OAUTH_TOKEN`, from the secrets
  file) and fails without it rather than use another login; Antigravity uses the Google sign-in in
  `~/.gemini` (`antigravity-login` restores it from the vault).
