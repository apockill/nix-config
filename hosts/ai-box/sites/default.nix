# Everything the web apps in /var/lib/hermes/sites (the ai-box-apps repo)
# need from the host. Each app is a directory under apps/; its instances,
# declared in the repo's namespaces/, are each served at <address>.alexthiele.io.
#
#   caddy.nix   serves each running instance on its socket in /run/sites, the
#               bus gateway, and static apps' files.
#   runner.nix  runs the repo's apps runner (tools/runner, over process-compose)
#               as the one service for the apps, and alerts Alex when an
#               instance fails (monitor.py).
#   below       the `box` CLI for the agent. The instances' state root,
#               /var/lib/hermes/instances, is declared in ../state/paths.nix.
#
# Removing this directory (and its import) removes the whole feature.
{ config, pkgs, ... }:
let
  sites = "${config.services.hermes-agent.stateDir}/sites";

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
      repo = "github.com/ailex-agent/ai-box-apps";
      why = "All web apps; code is committed. Runtime data inside is declared below.";
    };
    # host
    "/var/lib/apps-health" = {
      backup = "host";
      why = "This box's uptime and incident history (portal Status tab).";
    };
  };
}
