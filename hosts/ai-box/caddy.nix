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
      http://browser.alexthiele.io {
        redir / /vnc.html
        reverse_proxy 127.0.0.1:6080
      }

      http:// {
        @subdomain header_regexp sub Host ^([^.]+)\.alexthiele\.io$
        handle @subdomain {
          root * /var/lib/hermes/sites/{re.sub.1}
          file_server
        }
        handle {
          root * /var/lib/hermes/sites/default
          file_server
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
