# All non home-manager scoped options go in the system/ directory
{ ... }: {
  imports = [
    ./bash.nix
    ./docker.nix
    ./jetbrains.nix
    ./nautilus.nix
    ./virtualbox.nix
    # Seems to break flake updates super often
    #    ./vscode.nix
  ];
}
