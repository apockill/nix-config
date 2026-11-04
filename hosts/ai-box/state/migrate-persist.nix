# ONE-TIME MIGRATION for ai-box's first boot with the root wipe. Delete this
# file, ./migrate-persist.sh and their import in ./default.nix in a follow-up
# PR once the box has booted with @persist.
#
# Before that boot, all data is on @root and there is no @persist. In the
# initrd, before wipe-root, ./migrate-persist.sh copies every path in
# environment.persistence from @root into a new @persist. If that fails,
# @persist becomes a snapshot of the whole @root and wipe-root is skipped, so
# the box boots its untouched old root with all data still in place.
#
# Live switches are refused until then: on the old root /persist isn't
# mounted, and impermanence would create empty directories there and chmod
# the live ones to match. `nixos-rebuild boot` works (ai-box-switch falls back
# to it), then reboot.
{
  config,
  lib,
  pkgs,
  utils,
  ...
}:
let
  persistence = config.environment.persistence."/persist";
  homes = lib.attrValues persistence.users;
  # One "dir PATH" or "file PATH" per line, from the generated config.
  list = pkgs.writeText "persisted-paths" (
    lib.concatLines (
      map (d: "dir ${d.dirPath}") (persistence.directories ++ lib.concatMap (u: u.directories) homes)
      ++ map (f: "file ${f.filePath}") (persistence.files ++ lib.concatMap (u: u.files) homes)
    )
  );
  device = config.fileSystems."/persist".device;
  deviceUnit = "${utils.escapeSystemdPath device}.device";
in
{
  boot.initrd.systemd.services.migrate-persist = {
    description = "One-time copy of the persisted paths from @root to a new @persist";
    unitConfig.DefaultDependencies = false;
    serviceConfig = {
      Type = "oneshot";
      TimeoutSec = "infinity"; # a reflink copy is quick, but never cut it off
    };
    # wipe-root requires this, so it doesn't run if the migration fails.
    requiredBy = [ "wipe-root.service" ];
    before = [
      "wipe-root.service"
      "sysroot.mount"
    ];
    requires = [ deviceUnit ];
    after = [
      deviceUnit
      "local-fs-pre.target"
    ];
    script = "bash ${./migrate-persist.sh} ${device} ${list}";
  };
  # Only the unit's own script is copied into the initrd, not what it names.
  boot.initrd.systemd.storePaths = [
    "${./migrate-persist.sh}"
    "${list}"
  ];

  system.preSwitchChecks.persistMounted = ''
    case "$2" in boot | dry-activate) exit 0 ;; esac
    if ! ${pkgs.util-linux}/bin/mountpoint -q /persist; then
      echo "/persist isn't mounted (the root wipe isn't on yet): use 'nixos-rebuild boot' and reboot."
      exit 1
    fi
  '';
}
