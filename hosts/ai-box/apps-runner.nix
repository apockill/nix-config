# Autodiscovery process runner for backend apps in /var/lib/hermes/sites.
# Automatically launches and monitors any app containing an executable start.sh.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  runnerScript = pkgs.writeShellScript "ai-box-apps-runner" ''
    SITES_DIR="/var/lib/hermes/sites"
    while true; do
      for d in "$SITES_DIR"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        [[ "$name" =~ ^(\.|_|default) ]] && continue
        if [ -x "$d/start.sh" ]; then
          pidfile="$d/.runner.pid"
          if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            : # Process is healthy and running
          else
            echo "[apps-runner] Launching backend app: $name"
            (
              cd "$d"
              nohup ./start.sh > app.log 2>&1 &
              echo $! > "$pidfile"
            )
          fi
        fi
      done
      sleep 10
    done
  '';
in
{
  systemd.services.ai-box-apps-runner = {
    description = "Autodiscovery runner for ai-box backend apps";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      WorkingDirectory = "/var/lib/hermes/sites";
      ExecStart = "${runnerScript}";
      Restart = "always";
      RestartSec = "5s";
    };
  };
}
