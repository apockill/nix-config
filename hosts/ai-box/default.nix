# ai-box: Jetson AGX Orin that hosts AI services and the agents that use them.
#
# Agent accounts and their tooling should live alongside alex's, e.g.
# users/<agent>/default.nix imported here, so they can differ from alex's
# personal setup without touching agilite.
{ inputs, ... }:
{
  imports = [
    inputs.disko.nixosModules.disko
    ./disko.nix
    ../../hardware/jetson-agx-orin
    ../../modules/nixos/common
    ../../modules/nixos/headless
    ../../users/alex
  ];

  home-manager.users.alex.home.stateVersion = "26.05";

  boot.loader.systemd-boot.enable = true;
  boot.loader.systemd-boot.configurationLimit = 10;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "ai-box";

  zramSwap.enable = true;

  # Remote deploys (`just ai-box-deploy`) copy store paths as alex and
  # activate with sudo, so neither can prompt for a password.
  nix.settings.trusted-users = [
    "root"
    "@wheel"
  ];
  security.sudo.wheelNeedsPassword = false;

  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 30d";
  };

  # This value determines the NixOS release from which the default
  # settings for stateful data, like file locations and database versions
  # on your system were taken. Leave it at the release of the first install.
  system.stateVersion = "26.05"; # Did you read the comment?
}
