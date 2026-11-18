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
  imports = [
    ./claude-code.nix
    ./skew.nix # claude-agent-acp's SDK and the CLI must be the same Claude Code release
  ];

  aiBox.agents.claude.acp = acp;
  services.hermes-agent.extraPackages = [ acp ];

  # Every claude here keeps its config in ~/.claude (CLAUDE_CONFIG_DIR, ./claude-code.nix), its
  # .claude.json included, so there's no ~/.claude.json to keep.
  aiBox.state.paths.${claudeDir} = {
    backup = "cache";
    why = "Claude Code (agents/claude): settings, .claude.json (folder trust, onboarding) and session transcripts, which the agent runner points at; handy across reboots, not needed on a new box.";
  };

  # Sessions through the runner (../runner): Claude Code's own binary, on the subscription token.
  aiBox.agents.runner.agents.claude = {
    command = [ "${acp}/bin/claude-agent-acp" ];
    env = {
      CLAUDE_CONFIG_DIR = claudeDir;
      CLAUDE_CODE_EXECUTABLE = "${config.aiBox.agents.claude.cli}/bin/claude";
      # Compact at 200k tokens rather than near the 1M window: every request re-reads the whole
      # context from cache, and on 11-18 62% of the cache reads came from contexts over 400k
      # (workspace designs/acp-daemons/SKEPTIC.md, finding 2). Sculpt's builders use 200k too
      # (SCBUILD-15). A session's --env CLAUDE_CODE_AUTO_COMPACT_WINDOW=... overrides it.
      CLAUDE_CODE_AUTO_COMPACT_WINDOW = "200000";
    };
    compactWindowEnv = "CLAUDE_CODE_AUTO_COMPACT_WINDOW";
    passEnv = [ "CLAUDE_CODE_OAUTH_TOKEN" ];
    # Each would move the session off the subscription: to metered API billing (a key or token),
    # to Bedrock, Vertex or Foundry, or to another endpoint.
    refusedEnv = [
      "ANTHROPIC_API_KEY"
      "ANTHROPIC_AUTH_TOKEN"
      "ANTHROPIC_BASE_URL"
      "CLAUDE_CODE_USE_BEDROCK"
      "CLAUDE_CODE_USE_VERTEX"
      "CLAUDE_CODE_USE_FOUNDRY"
    ];
    transcript = "${claudeDir}/projects/{cwd_slug}/{session_id}.jsonl";
    # In a folder never trusted, the SDK route ignores the project's allow rules.
    claudeTrustFile = "${claudeDir}/.claude.json";
  };

  # At user level Claude Code reads only its own CLAUDE.md, and skills only from .claude/skills:
  # these links give it the shared ones. Measured on 2026-11-18 (claude 2.1.326, the CLI and
  # claude-agent-acp, the API requests themselves): the linked file reaches the model once, in
  # a repo with only AGENTS.md, with a CLAUDE.md importing @AGENTS.md, and with neither; a repo's
  # AGENTS.md reaches it once too, never twice. Claude reading a bare AGENTS.md depends on the
  # account's state (this account's config does, a fresh one didn't); `@AGENTS.md` in a CLAUDE.md
  # works either way.
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
