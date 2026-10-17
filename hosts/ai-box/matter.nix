# Host side of the Matter controller (the app itself is sites/matter in
# ai-box-apps). New Matter devices are set up over Bluetooth LE: the app's
# matter.js server runs in BLE-proxy mode, and its proxy client talks to BlueZ
# over D-Bus as hermes. This module provides only that Bluetooth stack.
{ ... }:
{
  hardware.bluetooth.enable = true;

  aiBox.state.paths."/var/lib/bluetooth" = {
    backup = "host";
    why = "BlueZ's adapter state and bonds for this box's own Bluetooth controller.";
  };
}
