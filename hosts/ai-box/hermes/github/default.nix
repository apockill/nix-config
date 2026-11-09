# GitHub for Hermes: everything in one place.
#
# Hermes acts on GitHub as "ailex-bot", a GitHub App that Alex owns and
# installed on the repos it may touch (apockill/nix-config,
# apockill/ai-box-apps). The app's private key is the vault item "GitHub App";
# no account password or long-lived token exists. (The ailex-agent machine
# account this replaced was suspended on 2026-11-08.)
#
# - gh-app-token: signs a JWT with the app key, read from 1Password through a
#   pipe (never on disk, argv or the environment), and prints a 1-hour
#   installation token.
# - gh: mints a token per call when GH_TOKEN isn't set. Hermes won't pass
#   GH_TOKEN into the agent's terminal (it treats it as a provider credential,
#   GHSA-rhgp-j443-p4rf), so gh fetches its own and only gh (and git, through
#   gh's credential helper) ever sees it.
# - git: commits are authored as the app's bot user.
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;

  ghAppToken = pkgs.writeShellApplication {
    name = "gh-app-token";
    runtimeInputs = [
      pkgs._1password-cli
      pkgs.openssl
      pkgs.jq
      pkgs.curl
      pkgs.gnused
      pkgs.coreutils
    ];
    text = builtins.readFile ./gh-app-token.sh;
  };

  ghWrapper = pkgs.writeShellScriptBin "gh" ''
    if [ -z "''${GH_TOKEN:-}" ]; then
      GH_TOKEN=$(${ghAppToken}/bin/gh-app-token)
      export GH_TOKEN
    fi
    exec ${pkgs.gh}/bin/gh "$@"
  '';
in
{
  services.hermes-agent.extraPackages = [
    ghWrapper
    ghAppToken
  ];

  home-manager.users.${cfg.user} = {
    programs.git.settings.user = {
      name = "ailex-bot[bot]";
      # the app's bot user id (api.github.com/users/ailex-bot%5Bbot%5D)
      email = "354606656+ailex-bot[bot]@users.noreply.github.com";
    };
    # Also makes gh git's credential helper for github.com.
    programs.gh = {
      enable = true;
      package = ghWrapper;
    };
  };
}
