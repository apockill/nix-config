{
  inputs,
  pkgs,
  ...
}: {


  environment.systemPackages = with pkgs; [
    (pkgs.jetbrains.plugins.addPlugins pkgs.jetbrains.pycharm-professional ["github-copilot"])
  ];
}
