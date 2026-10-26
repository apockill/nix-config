# Everything the web apps in /var/lib/hermes/sites (the ai-box-apps repo)
# need from the host. Each app is a subdirectory served at
# <name>.alexthiele.io; the apps' own code and dependencies live in that repo.
#
#   caddy.nix   serves each app: its app.sock if it has a start.sh, else its
#               files.
#   runner.nix  launches, health-checks and heals the apps (runner.py), and
#               alerts Alex when one fails (monitor.py).
#   below       the `box` CLI for the agent, and the apps' declared state: each
#               app keeps its persistent data in its own state/ directory.
#
# Removing this directory (and its import) removes the whole feature.
{ config, pkgs, ... }:
let
  sites = "${config.services.hermes-agent.stateDir}/sites";

  # `box`: the CLI for the apps. It builds each app's commands from its
  # /openapi.json over app.sock. The code lives in the apps repo (stdlib
  # only), so it updates with the apps rather than with a switch.
  boxWrapper = pkgs.writeShellScriptBin "box" ''
    exec ${pkgs.python3}/bin/python3 ${sites}/box.py "$@"
  '';
in
{
  imports = [
    ./caddy.nix
    ./runner.nix
    ./desk-idle.nix
  ];

  services.hermes-agent.extraPackages = [ boxWrapper ];

  aiBox.state.paths = {
    # git
    "${sites}" = {
      backup = "git";
      repo = "github.com/ailex-agent/ai-box-apps";
      why = "All web apps; code is committed. Runtime data inside is declared below.";
    };
    # restic
    "${sites}/*/state" = {
      backup = "restic";
      why = "Each app's persistent data (databases, settings, credentials), kept in <app>/state/ (gitignored in ai-box-apps).";
    };
    # host
    "/var/lib/apps-health" = {
      backup = "host";
      why = "This box's uptime and incident history (portal Status tab).";
    };
  };
}
