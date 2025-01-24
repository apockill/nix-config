{...}: {
  # The users are added to the "docker" group in their users/USER/default.nix
  # nvidia-container-toolkit is set up under hardware
  virtualisation.docker = {
    enable = true;
  };

}
