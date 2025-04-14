{ inputs, pkgs, ... }: {

  environment.systemPackages = with pkgs; [
    jetbrains.clion
    jetbrains.pycharm-professional
    (pkgs.jetbrains.plugins.addPlugins pkgs.jetbrains.pycharm-professional
      [ "github-copilot" ])
  ];
}
