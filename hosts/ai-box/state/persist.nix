# The root wipe (see ./default.nix for what is kept and why). How it works:
#
# 1. Every boot, before / is mounted, the initrd service `wipe-root` moves the
#    old root subvolume (@root) to old_roots/<timestamp> on the btrfs top level
#    and creates an empty @root in its place. Old roots are deleted 30 days
#    after they were retired.
# 2. Everything that must survive lives on the @persist subvolume, mounted at
#    /persist, at the same path it has on / (e.g. /persist/etc/machine-id).
#    The nix-community impermanence module bind-mounts each of those paths
#    from /persist to its real place, so programs never see /persist.
# 3. This file tells impermanence which paths those are. It derives the list
#    from aiBox.state.paths: every path whose backup class isn't `ephemeral`,
#    minus those inside another kept path (they come along with their parent).
#    Paths in a user's home are given to impermanence per user, so the
#    directories it creates there belong to that user.
# 4. NixOS activation runs in the initrd and already reads kept paths there
#    (alex's password file, hermes's config), so the kept directories are
#    bind-mounted in the initrd too, not only after it.
{
  config,
  lib,
  pkgs,
  inputs,
  utils,
  ...
}:
let
  persist = "/persist";
  # The btrfs partition holding every subvolume (../disko.nix).
  device = config.fileSystems.${persist}.device;
  deviceUnit = "${utils.escapeSystemdPath device}.device";
  # How long an old root is kept after it is retired (the README's choice).
  keepOldRootsDays = 30;
  declared = config.aiBox.state.paths;
  ephemeral = lib.attrNames (lib.filterAttrs (_: p: p.backup == "ephemeral") declared);
  kept = lib.attrNames (lib.filterAttrs (_: p: p.backup != "ephemeral") declared);
  # Is `path` strictly inside `ancestor`? Compares the two paths segment by
  # segment: `path` must be longer, and each of `ancestor`'s segments must
  # equal `path`'s segment at the same position, or be `*`, which matches any
  # name (as in "${sites}/*/state"). So "/a/b" is inside "/a" and "/*", but
  # not inside "/a/b" itself or "/ab".
  isInside =
    ancestor: path:
    let
      a = lib.splitString "/" ancestor;
      p = lib.splitString "/" path;
    in
    lib.length p > lib.length a && lib.all (x: x.fst == "*" || x.fst == x.snd) (lib.zipLists a p);
  # Only these get a bind mount; kept paths inside them come along.
  outermost = lib.filter (path: !lib.any (other: isInside other path) kept) kept;

  homeOf = user: config.users.users.${user}.home;
  inHome = user: lib.hasPrefix "${homeOf user}/";
  # Users with a kept path inside their home (root and hermes).
  homeOwners = lib.filter (user: lib.any (inHome user) outermost) (lib.attrNames config.users.users);
  # Splits paths into impermanence's two lists, by the `file` flag.
  entries = paths: {
    directories = lib.filter (p: !declared.${p}.file) paths;
    files = lib.filter (p: declared.${p}.file) paths;
  };
  # systemd wants the parents of DynamicUser state (/var/lib/private/<name>)
  # to be 0700; impermanence would create them 0755 on a fresh install.
  privateParents = lib.intersectLists [ "/var/lib/private" "/var/cache/private" ] (
    map dirOf outermost
  );
in
{
  imports = [ inputs.impermanence.nixosModules.impermanence ];

  fileSystems.${persist}.neededForBoot = true;

  environment.persistence.${persist} =
    entries (lib.filter (p: !lib.any (u: inHome u p) homeOwners) outermost)
    // {
      users = lib.genAttrs homeOwners (
        user:
        lib.mapAttrs (_: map (lib.removePrefix "${homeOf user}/")) (
          entries (lib.filter (inHome user) outermost)
        )
      );
    };

  assertions = [
    {
      assertion = lib.all (p: !lib.any (k: isInside k p) kept) ephemeral;
      message = "aiBox.state.paths: an ephemeral path can't sit inside a kept path (it would be kept with its parent, not wiped). Declare it `cache` to keep it out of backups: ${
        toString (lib.filter (p: lib.any (k: isInside k p) kept) ephemeral)
      }";
    }
    {
      assertion = lib.all (p: !lib.hasInfix "*" p) outermost;
      message = "aiBox.state.paths: a path with a `*` segment must sit inside a kept path (impermanence needs real paths): ${toString (lib.filter (lib.hasInfix "*") outermost)}";
    }
  ];

  # NixOS activation runs in the initrd (systemd stage 1), before
  # impermanence's bind mounts in stage 2, and it uses kept paths: alex's
  # hashedPasswordFile, hermes's config.yaml and skills. So every kept
  # directory is also bind-mounted in the initrd, as impermanence itself does
  # for /var/lib/nixos; its stage 2 units then find them mounted.
  boot.initrd.systemd.mounts =
    let
      persistence = config.environment.persistence.${persist};
      dirs =
        persistence.directories ++ lib.concatMap (u: u.directories) (lib.attrValues persistence.users);
    in
    map (d: {
      wantedBy = [ "initrd.target" ];
      before = [ "initrd-nixos-activation.service" ];
      what = "/sysroot${persist}${d.dirPath}";
      where = "/sysroot${d.dirPath}";
      type = "none";
      options = "bind";
      unitConfig = {
        DefaultDependencies = false;
        # A newly declared path has no source yet; stage 2 mounts it.
        ConditionPathIsDirectory = "/sysroot${persist}${d.dirPath}";
      };
    }) (lib.filter (d: !lib.elem d.dirPath utils.pathsNeededForBoot) dirs);

  systemd.tmpfiles.rules = lib.concatMap (d: [
    "d ${d} 0700 root root -"
    "d ${persist}${d} 0700 root root -"
  ]) privateParents;

  # wipe-root: retire the old root and create an empty one (step 1 above).
  # This is the rollback script from impermanence's README ("BTRFS
  # subvolumes" section), with four changes:
  # - it deletes expired old roots *before* retiring the current one, so the
  #   root of the previous boot always survives at least one boot;
  # - an old root's age counts from when it was retired (the `touch`). The
  #   touch is skipped when the clock is behind the root's own last change:
  #   this box has no RTC battery, so after a power cut the initrd's clock
  #   starts at systemd's build date, and a touch would make the root look old;
  # - it adds a .1, .2, ... suffix rather than reuse a taken name;
  # - `find -mindepth 1` never lists old_roots/ itself (the README's version
  #   would try to delete it once it's 30 days old, failing the whole wipe).
  boot.initrd.systemd.extraBin.find = "${pkgs.findutils}/bin/find"; # for wipe-root
  boot.initrd.systemd.services.wipe-root = {
    description = "Retire the old root and create an empty one";
    unitConfig.DefaultDependencies = false;
    serviceConfig.Type = "oneshot";
    wantedBy = [ "initrd.target" ];
    before = [ "sysroot.mount" ];
    requires = [ deviceUnit ];
    after = [
      deviceUnit
      "local-fs-pre.target"
    ];
    script = ''
      mkdir /btrfs_tmp
      mount -o subvolid=5 ${device} /btrfs_tmp
      trap 'umount /btrfs_tmp' EXIT
      mkdir -p /btrfs_tmp/old_roots

      for i in $(find /btrfs_tmp/old_roots/ -mindepth 1 -maxdepth 1 -mtime +${toString keepOldRootsDays}); do
          btrfs subvolume delete --recursive "$i"
      done

      if [[ -e /btrfs_tmp/@root ]]; then
          timestamp=$(date --date="@$(stat -c %Y /btrfs_tmp/@root)" "+%Y-%m-%-d_%H:%M:%S")
          dest="/btrfs_tmp/old_roots/$timestamp"
          n=0
          while [[ -e $dest ]]; do
              n=$((n + 1))
              dest="/btrfs_tmp/old_roots/$timestamp.$n"
          done
          mv /btrfs_tmp/@root "$dest"
          if (( $(date +%s) > $(stat -c %Y "$dest") )); then
              touch "$dest"
          fi
      fi

      btrfs subvolume create /btrfs_tmp/@root
    '';
  };
}
