# Configure docker to use nvidia
{
  config,
  lib,
  pkgs,
  ...
}:
{
  environment.systemPackages = with pkgs; [
    nvidia-container-toolkit
  ];

  virtualisation.docker = {
    daemon.settings = {
      features = {
        cdi = true;
      };
    };
  };

  hardware.nvidia-container-toolkit.enable = true;
}
