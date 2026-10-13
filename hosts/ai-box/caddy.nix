# Dynamic reverse proxy and static site server for ai-box.
# Automatically serves /var/lib/hermes/sites/<subdomain> at <subdomain>.alexthiele.io
# with zero rebuilds or service reloads.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  services.caddy = {
    enable = true;
    extraConfig = ''
      https://escapepod.local:443 {
        tls /var/lib/hermes/sites/vector/wirepod/epod/ep.crt /var/lib/hermes/sites/vector/wirepod/epod/ep.key
        reverse_proxy h2c://127.0.0.1:8443
      }

      http:// {
        @subhost host *.alexthiele.io
        handle @subhost {
          @hasBackend {
            file {
              root /var/lib/hermes/sites/{labels.2}
              try_files start.sh
            }
          }
          handle @hasBackend {
            reverse_proxy unix//var/lib/hermes/sites/{labels.2}/app.sock
          }
          handle {
            root * /var/lib/hermes/sites/{labels.2}
            file_server
          }
        }

        handle {
          @portalBackend {
            file {
              root /var/lib/hermes/sites/portal
              try_files start.sh
            }
          }
          handle @portalBackend {
            reverse_proxy unix//var/lib/hermes/sites/portal/app.sock
          }
          handle {
            root * /var/lib/hermes/sites/portal
            file_server
          }
        }
      }
    '';
  };

  users.users.caddy.extraGroups = [ "hermes" ];

  systemd.tmpfiles.rules = [
    "d /var/lib/hermes/sites 0755 hermes hermes -"
    "d /var/lib/hermes/sites/default 0755 hermes hermes -"
  ];
}
