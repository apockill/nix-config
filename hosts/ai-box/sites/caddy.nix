# Dynamic reverse proxy and static site server for ai-box, with zero rebuilds or reloads.
#
#   <address>.alexthiele.io   a running instance: /run/sites/<address>/app.sock, the socket the
#                             apps runner gives it (ai-box-apps DR-41)
#   <address>.../_bus/        the bus gateway, same-origin on every instance's address (D13)
#   <app>.alexthiele.io       a static app: the files of /var/lib/hermes/sites/apps/<app>
#   alexthiele.io             the portal instance
#
# A backend app whose instance isn't running answers 502, never its files.
#
# Caddy reaches what it serves through the group `sites`, of which it is the one member: the
# static apps' files in apps/ and the instances' sockets in /run/sites (both kept in the group
# by the apps runner, ./runner.nix). Of the agent's home it sees only apps/, read-only, so the
# group's write bits there give it no writes.
{ ... }:
let
  sites = "/var/lib/hermes/sites";
  run = "/run/sites";
in
{
  services.caddy = {
    enable = true;
    extraConfig = ''
      http:// {
        @subhost host *.alexthiele.io
        handle @subhost {
          # /_bus/ on every label, running instance or not: the gateway serves only the bus
          # (subscribe-only, NODE-26) and the whole domain is behind Cloudflare Access.
          @bus path /_bus/*
          handle @bus {
            reverse_proxy unix/${run}/.bus/app.sock
          }
          @instance {
            file {
              root ${run}
              try_files {labels.2}/
            }
          }
          handle @instance {
            reverse_proxy unix/${run}/{labels.2}/app.sock
          }
          @backendDown {
            file {
              root ${sites}/apps/{labels.2}
              try_files start.sh
            }
          }
          handle @backendDown {
            respond "{labels.2} isn't running" 502
          }
          handle {
            root * ${sites}/apps/{labels.2}
            file_server
          }
        }

        handle {
          reverse_proxy unix/${run}/portal/app.sock
        }
      }
    '';
  };

  users.groups.sites.members = [ "caddy" ];

  systemd.services.caddy = {
    serviceConfig = {
      TemporaryFileSystem = "/var/lib/hermes:ro";
      # "-": Caddy starts without apps/ on a box whose checkout isn't there yet.
      BindReadOnlyPaths = [ "-${sites}/apps" ];
    };
    # The runner puts apps/ in group sites when it starts; the Escape Pod cert Caddy loads at
    # its own start is there (../vector.nix).
    after = [ "ai-box-apps-runner.service" ];
  };

  systemd.tmpfiles.rules = [
    "d ${sites} 0755 hermes hermes -"
  ];
}
