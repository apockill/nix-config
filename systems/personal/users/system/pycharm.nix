{
  inputs,
  pkgs,
  ...
}: {


  environment.systemPackages = with pkgs; [
    jetbrains.pycharm-professional
    (pkgs.jetbrains.plugins.addPlugins pkgs.jetbrains.pycharm-professional ["github-copilot"])
  ];
}
