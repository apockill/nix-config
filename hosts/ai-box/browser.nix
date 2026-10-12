# Headless Chromium with live-view via noVNC on a virtual X11 display (Xvfb).
# Exposed to Hermes Agent over Chrome DevTools Protocol (CDP port 9222)
# and to Alex via noVNC web streaming (port 6080 / browser.alexthiele.io).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  display = ":99";
  profileDir = "/var/lib/hermes/browser-profile";
in
{
  systemd.tmpfiles.rules = [
    "d ${profileDir} 0750 hermes hermes -"
  ];

  # 1. Virtual X11 display
  systemd.services.browser-xvfb = {
    description = "Virtual X11 display for agent browser";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      ExecStart = "${pkgs.xorg-server}/bin/Xvfb ${display} -screen 0 1280x800x24 -ac +extension GLX +render -noreset";
      Restart = "always";
      RestartSec = "2s";
    };
  };

  # 2. VNC server + noVNC web proxy (HTML5 viewer on port 6080)
  systemd.services.browser-novnc = {
    description = "noVNC web stream for virtual display";
    after = [ "browser-xvfb.service" ];
    requires = [ "browser-xvfb.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      Restart = "always";
      RestartSec = "2s";
    };
    script = ''
      # Wait for Xvfb socket to appear
      while [ ! -e /tmp/.X11-unix/X99 ]; do
        sleep 0.2
      done

      # Start x11vnc in background
      ${pkgs.x11vnc}/bin/x11vnc -display ${display} -forever -shared -nopw -listen 127.0.0.1 -rfbport 5900 &
      VNC_PID=$!

      trap "kill $VNC_PID 2>/dev/null || true" EXIT

      # Start noVNC web server proxying to 5900
      exec ${pkgs.novnc}/bin/novnc --vnc 127.0.0.1:5900 --listen 0.0.0.0:6080
    '';
  };

  # 3. Chromium running on :99 with CDP exposed on localhost:9222
  systemd.services.browser-chromium = {
    description = "Chromium instance with CDP and persistent profile";
    after = [ "browser-xvfb.service" ];
    requires = [ "browser-xvfb.service" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      DISPLAY = display;
    };
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      Restart = "always";
      RestartSec = "5s";
      ExecStart = ''
        ${pkgs.chromium}/bin/chromium \
          --remote-debugging-port=9222 \
          --remote-debugging-address=127.0.0.1 \
          --user-data-dir=${profileDir} \
          --no-first-run \
          --no-default-browser-check \
          --disable-blink-features=AutomationControlled \
          --window-size=1280,800 \
          --window-position=0,0 \
          about:blank
      '';
    };
  };
}
