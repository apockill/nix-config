# The agent's dotfiles, generated from this repo. Change them here, not on the
# box: they're rewritten on every activation (each boot and switch).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  home = cfg.stateDir;
  gh = "${pkgs.gh}/bin/gh";

  gitconfig = pkgs.writeText "hermes-gitconfig" ''
    [user]
      name = ailex-agent
      email = 341263899+ailex-agent@users.noreply.github.com
    [credential "https://github.com"]
      helper =
      helper = !${gh} auth git-credential
    [credential "https://gist.github.com"]
      helper =
      helper = !${gh} auth git-credential
  '';

  # Interactive shells (the VS Code terminal, ssh) get the agent's secrets.
  bashrc = pkgs.writeText "hermes-bashrc" ''
    if [ -r /run/hermes-secrets/env ]; then
      set -a
      . /run/hermes-secrets/env
      set +a
    fi
  '';

  claudeSettings = pkgs.writeText "claude-settings.json" (builtins.toJSON { theme = "dark"; });
in
{
  # Activation runs with a minimal PATH, so tools are referenced by store path.
  system.activationScripts.hermes-dotfiles = lib.stringAfter [ "users" ] ''
    # Read-only links into the store.
    ${pkgs.coreutils}/bin/ln -sfn ${gitconfig} ${home}/.gitconfig
    ${pkgs.coreutils}/bin/ln -sfn ${bashrc} ${home}/.bashrc
    # A writable copy: Claude Code writes to its settings. Local changes last
    # until the next activation.
    ${pkgs.coreutils}/bin/install -D -o ${cfg.user} -g ${cfg.group} -m 0640 \
      ${claudeSettings} ${home}/.claude/settings.json
  '';
}
