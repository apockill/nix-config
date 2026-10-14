# Anki Vector Robot (Wire-Pod / Escape Pod local integration)
#
# Enables local discovery and network communication for Vector:
# 1. Publishes escapepod.local via mDNS/Avahi to point to ai-box.
# 2. Opens these firewall ports to Vector's IP only (not the rest of the LAN):
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
let
  vectorIp = "192.168.86.61";
  vectorPorts = "80,443,8084,8443";
in
{
  # Publish escapepod.local alias so Anki Vector (Escape Pod firmware) discovers ai-box
  environment.etc."avahi/hosts".text = ''
    192.168.86.26 escapepod.local
  '';
  systemd.services.avahi-daemon.restartTriggers = [
    config.environment.etc."avahi/hosts".source
  ];

  # Ports the physical Vector robot needs, opened to Vector's IP only. Caddy
  # listens on 80 and serves every *.alexthiele.io app; opening it to the whole
  # LAN would let any device skip Cloudflare Access. The Cloudflare tunnel
  # reaches Caddy over localhost, so public routes don't need these ports.
  # If Vector's DHCP lease changes, update vectorIp (or reserve it in the router).
  networking.firewall.extraCommands = ''
    iptables -A nixos-fw -p tcp -s ${vectorIp} -m multiport --dports ${vectorPorts} -j nixos-fw-accept
  '';
  networking.firewall.extraStopCommands = ''
    iptables -D nixos-fw -p tcp -s ${vectorIp} -m multiport --dports ${vectorPorts} -j nixos-fw-accept 2>/dev/null || true
  '';

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
