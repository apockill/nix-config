# The root wipe (see ./default.nix): the kept paths in aiBox.state.paths live
# on @persist and impermanence bind-mounts them into place, while the initrd
# swaps in an empty @root on every boot (impermanence's README recipe).
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
  # Users whose home holds kept paths. impermanence gives their entries, and
  # the directories it creates inside the home, the user's ownership.
  homeOwners = [
    "root"
    config.services.hermes-agent.user
  ];

  declared = config.aiBox.state.paths;
  kept = lib.attrNames (lib.filterAttrs (_: p: p.backup != "ephemeral") declared);
  # Is `path` strictly inside `ancestor`? A `*` segment in `ancestor` matches
  # any name.
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

  # The README's rollback, with four changes: it prunes before retiring the
  # current root, so that one always survives a boot; it counts age from
  # retirement (touch), unless the clock is behind the root's own last change
  # (no RTC battery: after a power cut the initrd's clock starts at systemd's
  # build date); it never reuses a name; and it never prunes old_roots/ itself
  # (-mindepth 1).
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
