"""The agent runner: every coding agent session on ai-box, over the Agent Client Protocol.

`agent serve` is the service (server.py). Each session is an agent's own ACP server
(claude-agent-acp, `agy acp`) running as a subprocess of the service; the service holds the
connection and serves a local HTTP API on a unix socket (api.py). Every other verb of `agent` is
the CLI for that API (cli.py). README.md (next to this package) documents the API, the events and
the states.

The modules, from the bottom up:
  schema      typed records: dataclasses, checked strictly where JSON comes in
  config      the agents file and the runner's fixed limits
  acp, updates  the ACP messages used, and views of the session updates the runner reads
  rpc         one agent process: JSON-RPC over its stdio
  events      the events (README.md, "Events"); store: sessions on disk; bus: numbering, fan-out
  vendors     where the agents differ; handshake: opening a session on a started agent
  parking     permissions and questions waiting for an answer; notify: telling Alex
  session     one session: its process, turns and state; inbox: what its agent sends it
  runner      every session, by name
  http_io, api_types, api, server   the API and the service
  client, render, jobs, wait, cli   the CLI
"""
