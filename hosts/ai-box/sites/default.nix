# Everything the web apps in /var/lib/hermes/sites (the ai-box-apps repo)
# need from the host. Each app is a directory under apps/; its instances,
# declared in the repo's namespaces/, are each served at <address>.alexthiele.io.
#
#   caddy.nix   serves each running instance on its socket in /run/sites, the
#               bus gateway, and static apps' files.
#   runner.nix  runs the repo's apps runner (tools/runner, over process-compose)
#               as the one service for the apps, and alerts Alex when an
#               instance fails (monitor.py).
#   below       the `box` CLI for the agent, and the state this feature keeps:
#               the repo checkout and the instances' state root,
#               /var/lib/hermes/sites-instances.
#
# Removing this directory (and its import) removes the whole feature.
{ config, pkgs, ... }:
let
  sites = "${config.services.hermes-agent.stateDir}/sites";
  # The instances' state, beside the repo checkout rather than in it.
  stateRoot = "${config.services.hermes-agent.stateDir}/sites-instances";

  # `box`: the CLI for the apps. It builds each app's commands from its
  # /openapi.json over app.sock. The code lives in the apps repo (stdlib
  # only), so it updates with the apps rather than with a switch.
  boxWrapper = pkgs.writeShellScriptBin "box" ''
    exec ${pkgs.python3}/bin/python3 ${sites}/tools/box/box.py "$@"
  '';
in
{
  imports = [
    ./caddy.nix
    ./runner.nix
  ];

  services.hermes-agent.extraPackages = [ boxWrapper ];

  aiBox.state.paths = {
    # git
    "${sites}" = {
      backup = "git";
      repo = "github.com/apockill/ai-box-apps";
      why = "All web apps; code is committed. Runtime data inside is declared below.";
    };
    # restic
    "${stateRoot}" = {
      backup = "restic";
      why = "The web apps' state root (ai-box-apps DR-42): one directory per app instance (databases, settings, credentials), outside the apps repo so no git clean or worktree reaches it; .trash/ holds destroyed instances' state, .runner/ which namespaces are up.";
    };
    # ephemeral
    "${stateRoot}-scratch" = {
      backup = "ephemeral";
      why = "Scratch state of apps run from working trees other than the live checkout (ai-box-apps STATE-6); fine to lose.";
    };
    # host
    "/var/lib/apps-health" = {
      backup = "host";
      why = "This box's uptime and incident history (portal Status tab).";
    };
  };
}
