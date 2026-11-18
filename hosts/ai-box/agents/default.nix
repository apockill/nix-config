# The coding agents on ai-box: Claude Code and the Antigravity CLI, on the subscriptions Alex pays
# for. Each vendor has one directory holding everything specific to it (packages, settings,
# permissions, auth, models, hooks); everything outside them talks about "the agent".
#   claude/       Claude Code (Anthropic)
#   antigravity/  the Antigravity CLI, agy (Google)
#
# Decisions and evidence: the agent's workspace designs/agent-agnostic.md and
# designs/agent-agnostic-spike.md.
{ lib, ... }:
let
  package =
    description:
    lib.mkOption {
      type = lib.types.package;
      internal = true;
      inherit description;
    };
in
{
  imports = [
    ./claude
    ./antigravity
  ];

  options.aiBox.agents = {
    claude.cli = package "The claude CLI on the agent's PATH.";
    claude.acp = package "claude-agent-acp: Claude Code as an ACP server.";
    antigravity.cli = package "The Antigravity CLI (agy) on the agent's PATH; `agy acp` is its ACP server.";
  };
}
