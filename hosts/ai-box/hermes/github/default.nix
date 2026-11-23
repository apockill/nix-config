# GitHub for Hermes: the ailex-agent account (vault item "GitHub"), a collaborator on
# Alex's repos.
#
# - gh reads the account's token from the secrets file: Hermes passes GH_TOKEN to no
#   process it starts (GHSA-rhgp-j443-p4rf).
# - git: commits are authored as ailex-agent.
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;

  ghWrapper = pkgs.writeShellScriptBin "gh" ''
    if [ -z "''${GH_TOKEN:-}" ] && [ -r /run/hermes-secrets/env ]; then
      export GH_TOKEN=$(${pkgs.gnused}/bin/sed -n 's/^GH_TOKEN=//p' /run/hermes-secrets/env)
    fi
    exec ${pkgs.gh}/bin/gh "$@"
  '';
in
{
  aiBox.hermesSecrets = ''
    # "GitHub": the ailex-agent account's token (./github)
    GH_TOKEN={{ op://ai-assistant/kb6xnh67wvh2hu7gtl3cgzxu4u/token }}
  '';

  services.hermes-agent.extraPackages = [ ghWrapper ];

  home-manager.users.${cfg.user} = {
    programs.git.settings.user = {
      name = "ailex-agent";
      email = "341263899+ailex-agent@users.noreply.github.com";
    };
    # Also makes gh git's credential helper for github.com.
    programs.gh = {
      enable = true;
      package = ghWrapper;
    };
  };
}
