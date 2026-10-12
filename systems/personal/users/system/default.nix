# All non home-manager scoped options go in the system/ directory
{ ... }: {
  imports = [
    ./1password.nix
    ./bash.nix
    ./docker.nix
    ./nautilus.nix
    ./virtualbox.nix
  ];
}
