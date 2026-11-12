# Claude Code for the agent: the current release, with its config in ~/.claude.
{
  config,
  inputs,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;

  # Claude Code keeps .claude.json in CLAUDE_CONFIG_DIR, else in ~. The root
  # wipe only keeps ~/.claude (state/paths.nix), and a file of its own in ~
  # can't be bind-mounted because Claude Code replaces it by renaming. So the
  # claude on hermes's PATH defaults it to ~/.claude for every launcher (the
  # agent, cc, code-server's Claude extension).
  claudeCode = pkgs.symlinkJoin {
    name = "claude-code";
    paths = [ pkgs.claude-code ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = "wrapProgram $out/bin/claude --set-default CLAUDE_CONFIG_DIR ${cfg.stateDir}/.claude";
  };
in
{
  # Stable nixpkgs' claude-code lags behind what current models require
  # (Opus 5.5 needs 2.1.280+); this flake tracks Claude Code releases.
  nixpkgs.overlays = [ inputs.claude-code-nix.overlays.default ];

  services.hermes-agent.extraPackages = [ claudeCode ];
}
