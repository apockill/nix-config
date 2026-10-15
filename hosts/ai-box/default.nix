# ai-box: Jetson AGX Orin that hosts AI services and the agents that use them.
#
# Agent accounts and their tooling should live alongside alex's, e.g.
# users/<agent>/default.nix imported here, so they can differ from alex's
# personal setup without touching agilite.
{ inputs, config, ... }:
{
  imports = [
    inputs.disko.nixosModules.disko
    ./disko.nix
    ./snapshots.nix
    ./llama-cpp.nix
    ./browser.nix
    ./cloudflared.nix
    ./caddy.nix
    ./apps-runner
    ./state # declared state + audit (impermanence prep)
    ./vector.nix
    ./hermes
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

  # sudo keeps asking for a password, and alex is not a nix trusted-user (that
  # would be root-equivalent too). Agents will be running on this box, so root
  # takes a human typing a password: `just ai-box-deploy` prompts for it.

  # master is the source of truth: apply whatever is merged there, hourly.
  # (The agent can also apply it immediately with `ai-box-switch`.) Anything
  # deployed by hand with `just ai-box-deploy` is replaced on the next run.
  system.autoUpgrade = {
    enable = true;
    flake = "github:apockill/nix-config#ai-box";
    dates = "hourly";
    randomizedDelaySec = "5min";
    allowReboot = false;
  };

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
