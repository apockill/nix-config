# Cloudflare Tunnel daemon for ai-box.
# Connects the 'openclaw' tunnel to Cloudflare Zero Trust using credentials
# managed securely in 1Password.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  systemd.services.cloudflared = {
    description = "Cloudflare Tunnel (openclaw)";
    after = [
      "network-online.target"
      "hermes-secrets.service"
    ];
    wants = [ "network-online.target" ];
    requires = [ "hermes-secrets.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      EnvironmentFile = "/run/hermes-secrets/env";
      ExecStart = "${pkgs.cloudflared}/bin/cloudflared tunnel --no-autoupdate run --token \${CLOUDFLARE_TUNNEL_TOKEN}";
      Restart = "always";
      RestartSec = "5s";
    };
  };
}
