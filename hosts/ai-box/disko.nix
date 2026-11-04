# The 1TB NVMe is the only disk NixOS uses; the built-in 64GB eMMC is left alone.
#
# btrfs subvolumes are split by what survives a boot and whether rolling them
# back makes sense (see snapshots.nix):
#   @root     /, wiped on every boot: the initrd moves it to old_roots/ on the
#             top level and creates an empty one (state/persist.nix)
#   @persist  the declared state, bind-mounted into place; snapshotted
#   @home     snapshotted
#   @nix, @log, @docker  kept as they are, never snapshotted
{ ... }:
let
  opts = [
    "compress=zstd"
    "noatime"
  ];
in
{
  disko.devices.disk.nvme = {
    type = "disk";
    device = "/dev/disk/by-id/nvme-KXG80ZNV1T02_NVMe_KIOXIA_1024GB_233FC061F01K";
    content = {
      type = "gpt";
      partitions = {
        ESP = {
          size = "1G";
          type = "EF00";
          content = {
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          size = "100%";
          content = {
            type = "btrfs";
            extraArgs = [
              "-f"
              # btrfs-progs enables block-group-tree by default, but it needs
              # Linux 6.1+ and the JetPack 6 kernel is 5.15: the root fs would
              # refuse to mount read-write.
              "-O"
              "^block-group-tree"
            ];
            subvolumes = {
              "@root" = {
                mountpoint = "/";
                mountOptions = opts;
              };
              # Every declared path that survives a boot (state/paths.nix)
              "@persist" = {
                mountpoint = "/persist";
                mountOptions = opts;
              };
              "@home" = {
                mountpoint = "/home";
                mountOptions = opts;
              };
              # Reproducible; NixOS generations already cover rollback
              "@nix" = {
                mountpoint = "/nix";
                mountOptions = opts;
              };
              # Kept out of snapshots so a rollback never erases the record of
              # what happened
              "@log" = {
                mountpoint = "/var/log";
                mountOptions = opts;
              };
              # Re-pullable image layers that churn constantly
              "@docker" = {
                mountpoint = "/var/lib/docker";
                mountOptions = opts;
              };
              # Where snapper keeps snapshots of /persist and /home
              "@snapshots" = {
                mountpoint = "/persist/.snapshots";
                mountOptions = opts;
              };
              "@home-snapshots" = {
                mountpoint = "/home/.snapshots";
                mountOptions = opts;
              };
            };
          };
        };
      };
    };
  };
}
