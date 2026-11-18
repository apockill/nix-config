# Claude (Anthropic): everything specific to Claude Code on ai-box.
#   claude-code.nix  the claude CLI (current release), config in ~/.claude
#   acp.nix          claude-agent-acp, Claude Code as an ACP server for the agent runner
#   (here)           user settings, the links to the shared AGENTS.md and skills, the runner's
#                    agent "claude"
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

  # Sessions through the runner (../runner): Claude Code's own binary, on the subscription token.
  aiBox.agents.runner.agents.claude = {
    command = [ "${acp}/bin/claude-agent-acp" ];
    env = {
      CLAUDE_CONFIG_DIR = claudeDir;
      CLAUDE_CODE_EXECUTABLE = "${config.aiBox.agents.claude.cli}/bin/claude";
    };
    passEnv = [ "CLAUDE_CODE_OAUTH_TOKEN" ];
    refusedEnv = [
      "ANTHROPIC_API_KEY"
      "ANTHROPIC_AUTH_TOKEN"
    ];
    transcript = "${claudeDir}/projects/{cwd_slug}/{session_id}.jsonl";
    # In a folder never trusted, the SDK route ignores the project's allow rules.
    claudeTrustFile = "${claudeDir}/.claude.json";
  };

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
