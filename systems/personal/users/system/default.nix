# All non home-manager scoped options go in the system/ directory
{ ... }: {
  imports = [
    ./nautilus.nix
    ./docker.nix
    ./warp.nix
    ./bash.nix
  ];
}
