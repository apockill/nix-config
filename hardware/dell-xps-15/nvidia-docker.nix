# Configure docker to use nvidia

{ config, lib, pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
    nvidia-container-toolkit
    nvidia-docker
  ];

  # Set up the default runtime
  virtualisation.docker = {
    # This option is marked as deprectaed, but without it I get an exception on the
    # docker.service startup, so it stays for now!
    enableNvidia = true;

    daemon.settings = {
        default-runtime = "nvidia";
    };
  };

  hardware.nvidia-container-toolkit.enable = true;

}