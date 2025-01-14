{...}: {
  # This "Fixes" the annoying red warning banner that warp throws because it's unable
  # to perform auto updates
  # https://github.com/warpdotdev/Warp/issues/1991#issuecomment-2379297729
  # WARNING! This means that when updating your system you may run into issues.
  # Copied from the link:
  #   You will have issues doing a nixos-rebuild with this workaround.
  #   To perform rebuild successfully while updating your system, you need to comment
  #   both extraHosts line and the warp-terminal package in the systemPackages,
  #   home-manager or wherever you installed warp terminal. After the update/rebuild
  #   upgrade is complete, you can uncomment these lines back and rebuild again to
  #   install warp terminal back then keep blocking requests to Warp servers.

  networking.extraHosts =
  ''
    127.0.0.1 releases.warp.dev
    127.0.0.1 app.warp.dev
  '';


}
