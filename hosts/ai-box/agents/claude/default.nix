# Claude (Anthropic): everything specific to Claude Code on ai-box.
#   claude-code.nix  the claude CLI (current release), config in ~/.claude
#   acp.nix          claude-agent-acp, Claude Code as an ACP server for the agent runner
#   (here)           user settings, and the links to the shared AGENTS.md and skills
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
  claudeDir = "${cfg.stateDir}/.claude";
  acp = pkgs.callPackage ./acp.nix { claude = config.aiBox.agents.claude.cli; };
in
{
  imports = [ ./claude-code.nix ];

  aiBox.agents.claude.acp = acp;
  services.hermes-agent.extraPackages = [ acp ];

  # Claude Code reads AGENTS.md in a repository, but at user level only its own CLAUDE.md, and
  # skills only from .claude/skills.
  aiBox.agents.links = {
    "${claudeDir}/CLAUDE.md" = config.aiBox.agents.instructions;
    "${claudeDir}/skills" = config.aiBox.agents.skills;
  };

  home-manager.users.${cfg.user} =
    { lib, pkgs, ... }:
    {
      # Claude Code writes to its settings, so this is a writable copy rather
      # than a home-manager link. Local changes last until the next activation.
      home.activation.claudeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run install -D -m 0640 ${
          pkgs.writeText "claude-settings.json" (
            builtins.toJSON {
              theme = "dark";
              # Alex: Opus always at high effort (medium is the Claude Code default).
              effortLevel = "high";
              env.CLAUDE_CODE_EFFORT_LEVEL = "high";
            }
          )
        } "$HOME/.claude/settings.json"
      '';
    };
}
