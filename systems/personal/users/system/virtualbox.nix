{ inputs, pkgs, ... }: {
  environment.systemPackages = with pkgs; [ virtualbox ];

  virtualisation.virtualbox.host.enableExtensionPack = true;
}
