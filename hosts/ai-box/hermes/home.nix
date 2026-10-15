# The agent's home directory config, via home-manager (like alex's). Change it
# here, not on the box: home-manager regenerates these files on every boot and
# switch.
{
  config,
  inputs,
  ...
}:
let
  cfg = config.services.hermes-agent;
in
{
  imports = [ inputs.home-manager.nixosModules.home-manager ];

  home-manager.users.${cfg.user} =
    { lib, pkgs, ... }:
    {
      home.stateVersion = "26.05";

      programs.git = {
        enable = true;
        settings.user = {
          name = "ailex-agent";
          email = "341263899+ailex-agent@users.noreply.github.com";
        };
      };

      # Also configures git to use gh for GitHub credentials. The package is
      # ghWrapper (hermes/default.nix), which supplies the token.
      programs.gh.enable = true;

      # No programs.bash: Hermes builds the agent's terminal environment from a
      # login-shell snapshot and strips credentials (GH_TOKEN, ...) it finds
      # there. Shell rc files that load secrets would get them stripped. The
      # VS Code app loads secrets for its own terminals instead.

      # Claude Code writes to its settings, so this is a writable copy rather
      # than a home-manager link. Local changes last until the next activation.
      home.activation.claudeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run install -D -m 0640 ${
          pkgs.writeText "claude-settings.json" (builtins.toJSON { theme = "dark"; })
        } "$HOME/.claude/settings.json"
      '';
    };
}
