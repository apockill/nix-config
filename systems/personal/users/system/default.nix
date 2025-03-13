# All non home-manager scoped options go in the system/ directory
{...}: {
  imports = [
    ./bash.nix
    ./docker.nix
    ./pycharm.nix
    ./nautilus.nix
    ./vscode.nix
    ./virtualbox.nix
  ];
}
