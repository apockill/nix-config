# Elephant Robotics myArm M750. Its base M5Stack board is a CH9102 USB serial
# port; give it a stable name (by the chip's serial number), since ttyACM
# numbers depend on plug order.
{ ... }:
{
  services.udev.extraRules = ''
    SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d4", ATTRS{serial}=="575E078853", SYMLINK+="myarm-m750"
  '';
}
