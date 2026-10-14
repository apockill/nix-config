# Anki Vector Robot (Wire-Pod / Escape Pod local integration)
#
# Enables local discovery and network communication for Vector:
# 1. Publishes escapepod.local via mDNS/Avahi to point to ai-box.
# 2. Opens local firewall ports for Vector to connect over home Wi-Fi:
#    - Port 80: HTTP captive portal / connectivity check
#    - Port 443: HTTPS Escape Pod proxy for auth & OTA
#    - Port 8084: Wire-Pod token session authentication
#    - Port 8443: Wire-Pod Chipper gRPC voice server
# 3. Proxies https://escapepod.local:443 in Caddy with the Escape Pod TLS cert.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  # Publish escapepod.local alias so Anki Vector (Escape Pod firmware) discovers ai-box
  environment.etc."avahi/hosts".text = ''
    192.168.86.26 escapepod.local
  '';
  systemd.services.avahi-daemon.restartTriggers = [
    config.environment.etc."avahi/hosts".source
  ];

  # Ports required by physical Vector robot on the local home network
  networking.firewall.allowedTCPPorts = [
    80
    443
    8084
    8443
  ];

  # Reverse proxy escapepod.local:443 to Wire-Pod Chipper on port 8443
  services.caddy.extraConfig = lib.mkAfter ''
    https://escapepod.local:443 {
      tls /var/lib/hermes/sites/vector/wirepod/epod/ep.crt /var/lib/hermes/sites/vector/wirepod/epod/ep.key
      reverse_proxy https://127.0.0.1:8443 {
        transport http {
          tls_insecure_skip_verify
        }
      }
    }
  '';
}
