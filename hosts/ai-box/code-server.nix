# VS Code in the browser at code.alexthiele.io: a terminal and editor on
# ai-box as the `alex` user (root needs alex's sudo password).
#
# Access control is Cloudflare Access (the shared *.alexthiele.io policy:
# Alex and Bethany). code-server itself has no password and listens only on
# localhost; the only way in is tunnel -> Caddy -> here.
#
# Removing this file and its import removes the feature.
{ lib, ... }:
let
  port = 4444;
in
{
  services.code-server = {
    enable = true;
    user = "alex";
    group = "users";
    host = "127.0.0.1";
    inherit port;
    auth = "none";
    disableTelemetry = true;
    disableUpdateCheck = true;
  };

  # Terminals inherit the service's PATH; give them the full system one
  # (including /run/wrappers for sudo) instead of systemd's minimal default.
  systemd.services.code-server.environment.PATH = lib.mkForce
    "/run/wrappers/bin:/home/alex/.nix-profile/bin:/etc/profiles/per-user/alex/bin:/run/current-system/sw/bin";

  # A specific host block wins over caddy.nix's catch-all `http://` site.
  services.caddy.virtualHosts."http://code.alexthiele.io".extraConfig = ''
    reverse_proxy 127.0.0.1:${toString port}
  '';
}
