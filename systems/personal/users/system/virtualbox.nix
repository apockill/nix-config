{ inputs, pkgs, ... }: {
  users.extraGroups.vboxusers.members = [ "alex" ];
  virtualisation = {
    virtualbox.host.enable = true;
    # If USB is not needed, comment this out. It may cause frequent recompilations.
    virtualbox.host.enableExtensionPack = true;
  };
}
