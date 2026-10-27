# NVIDIA Jetson AGX Orin 64GB developer kit, via anduril/jetpack-nixos.
{ inputs, lib, pkgs, ... }:
{
  imports = [ inputs.jetpack-nixos.nixosModules.default ];

  nixpkgs.hostPlatform = "aarch64-linux";

  hardware.nvidia-jetpack = {
    enable = true;
    som = "orin-agx";
    carrierBoard = "devkit";
    # Pinned so a jetpack-nixos bump can't silently move us to a JetPack whose
    # firmware is incompatible with the one flashed on the board.
    majorVersion = "6";

    # Only applied by a fresh firmware flash. NVMe first means we never need a
    # monitor to pick a boot device; USB stays as a rescue path.
    firmware.initialBootOrder = [
      "nvme"
      "usb"
      "emmc"
      "shell"
    ];

    # Apply firmware capsule updates on `nixos-rebuild switch` so firmware
    # stays in lockstep with the kernel/rootfs after a `nix flake update`.
    firmware.autoUpdate = true;
  };

  # Power mode: MAXN (nvpmodel profile 0). NVIDIA's shipped default is
  # MODE_30W, which caps the GPU at 612 MHz and switches 4 of the 12 CPU cores
  # off; local Gemma ran at ~9.5 tokens/s under it.
  #
  # Switching from 30 W to MAXN needs a reboot: plain `nvpmodel -m 0` asks for
  # confirmation, fails without a terminal, and the unit restart-loops (seen
  # live; it hung nixos-rebuild). --force makes nvpmodel reboot by itself the
  # one time the mode changes; once in MAXN, later boots need no reboot.
  services.nvpmodel.profileNumber = 0;
  systemd.services.nvpmodel.serviceConfig.ExecStart =
    lib.mkForce "${pkgs.nvidia-jetpack.l4t-nvpmodel}/bin/nvpmodel -f /etc/nvpmodel.conf -m 0 --force";

  # Needed even for CUDA and containers
  hardware.graphics.enable = true;
  hardware.enableRedistributableFirmware = true;

  # GPU passthrough to containers: `docker run --device=nvidia.com/gpu=all ...`
  hardware.nvidia-container-toolkit.enable = true;
  virtualisation.docker.daemon.settings.features.cdi = true;
}
