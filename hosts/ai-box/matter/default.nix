# Matter: a local controller for Matter smart-home devices (the desk light plug).
#
# python-matter-server holds the Matter "fabric" (this box's pairing
# credentials) and serves a WebSocket API on localhost only. The `matter` CLI
# (./matter.py) wraps it: list devices, switch them, pair new ones.
# Delete this directory (and its import) to remove the feature; paired
# devices then need re-pairing.
{ config, lib, pkgs, ... }:
let
  port = 5580;
  matterCli = pkgs.writers.writePython3Bin "matter" {
    libraries = [ pkgs.python3Packages.websockets ];
    flakeIgnore = [ "E501" ];
  } (builtins.readFile ./matter.py);
in
{
  services.matter-server = {
    enable = true;
    inherit port;
    extraArgs = {
      # Localhost only: the API is unauthenticated.
      listen-address = "127.0.0.1";
      primary-interface = "wlP1p1s0";
      # Pair brand-new (or reset) devices over Bluetooth LE: hci0.
      bluetooth-adapter = 0;
    };
  };
  # BlueZ for Bluetooth pairing, and let the sandboxed service use it.
  hardware.bluetooth.enable = true;
  systemd.services.matter-server.serviceConfig.RestrictAddressFamilies = lib.mkForce [
    "AF_BLUETOOTH"
    "AF_INET"
    "AF_INET6"
    "AF_NETLINK"
    "AF_UNIX"
  ];

  # Devices are reached over the LAN (IPv6 + mDNS via Avahi, already running
  # for Vector). Outgoing connections and their replies need no firewall rule.

  services.hermes-agent.extraPackages = [ matterCli ];

  aiBox.state.paths."/var/lib/private/matter-server" = {
    backup = "restic";
    why = "Matter fabric: this box's pairing credentials and paired devices. Losing it means re-pairing every device.";
  };
  aiBox.state.paths."/var/lib/matter-server" = {
    backup = "ephemeral";
    why = "systemd's DynamicUser link to /var/lib/private/matter-server; recreated on service start.";
  };
}
