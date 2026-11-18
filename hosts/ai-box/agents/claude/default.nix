# Claude (Anthropic): everything specific to Claude Code on ai-box.
#   claude-code.nix  the claude CLI (current release), config in ~/.claude
#   acp.nix          claude-agent-acp, Claude Code as an ACP server for the agent runner
{ config, pkgs, ... }:
let
  acp = pkgs.callPackage ./acp.nix { claude = config.aiBox.agents.claude.cli; };
in
{
  imports = [ ./claude-code.nix ];

  aiBox.agents.claude.acp = acp;
  services.hermes-agent.extraPackages = [ acp ];
}
