"""The agent runner: every coding agent session on ai-box, over the Agent Client Protocol.

`agent serve` is the service (server.py). Each session is an agent's own ACP server
(claude-agent-acp, `agy acp`) running as a subprocess of the service; the service holds the
connection and serves a local HTTP API on a unix socket (api.py). Every other verb of `agent` is
the CLI for that API (cli.py). README.md (next to this package) documents the API, the events and
the states.

It is built on libraries for everything they cover: the ACP Python SDK (agent-client-protocol:
the JSON-RPC connection, the protocol's pydantic models), pydantic for the runner's own records,
Starlette and uvicorn for the API, httpx for the CLI's calls. What is the runner's own: sessions
that outlive their callers, the event log and its fan-out, parking requests until someone answers,
jobs and `wait`, the vendors' differences, notifying Alex, and the CLI.

The modules, from the bottom up:
  base, errors  the strict pydantic base and the expected failures
  config      the agents file and the runner's fixed limits
  events      the events (README.md, "Events"); store: sessions on disk; bus: numbering, fan-out
  vendors     where the agents differ; agent: one agent process on the ACP SDK
  parking     permissions and questions waiting for an answer; notify: telling Alex
  session     one session: its process, turns and state; inbox: what its agent sends it
  runner      every session, by name
  api_types, api, server   the API (Starlette) and the service (uvicorn)
  client, render, jobs, wait, cli   the CLI
"""
