# NVIDIA Jetson AGX Orin 64GB developer kit, via anduril/jetpack-nixos.
{ inputs, ... }:
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

  # Needed even for CUDA and containers
  hardware.graphics.enable = true;
  hardware.enableRedistributableFirmware = true;

  # GPU passthrough to containers: `docker run --device=nvidia.com/gpu=all ...`
  hardware.nvidia-container-toolkit.enable = true;
  virtualisation.docker.daemon.settings.features.cdi = true;
}
