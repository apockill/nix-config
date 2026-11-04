# The root wipe, booted: a VM with this state module (paths, users, persist)
# and ../snapshots.nix, on a btrfs disk laid out like ai-box's. It boots five
# times and checks that kept data survives at its real path, that everything
# else is retired to old_roots/, how old roots are pruned (including with the
# clock behind), and what the audit reports. The `persist` check; it needs the
# kvm and nixos-test system features, so only `just test-all` runs it.
#
# It uses the flake's plain nixpkgs: ai-box's own pkgs builds with CUDA, which
# the module logic under test doesn't touch.
{ inputs, pkgs }:
let
  testPkgs = inputs.nixpkgs.legacyPackages.${pkgs.stdenv.hostPlatform.system};
  inherit (testPkgs) lib;

  # The VM's disk, all one btrfs filesystem like ai-box's NVMe partition.
  device = "/dev/disk/by-label/ai-box";
  # Mount options as in ../disko.nix.
  subvol = name: [
    "compress=zstd"
    "noatime"
    "subvol=${name}"
  ];
  # hermes's ids in the image; the VM's users must match.
  hermesUid = 993;
  hermesGid = 991;
  # alex's password hash in the image (yescrypt of "test").
  alexHash = "$y$j9T$Y6Rm1y5x3qJ6pX4hYn8Fh/$kO0iT0p8fbr6qH.RQ5yYbqJj9b8mEoQH0vJ1E5wqD/6";

  # Kept data on @persist before the first boot, by real path: owner and mode
  # as `stat -c '%u:%g %a'` prints them, and a file's text (dirs have none).
  # Sorted by path, so each directory comes before what's inside it.
  kept = {
    "/etc/machine-id" = {
      stat = "0:0 444";
      text = "0123456789abcdef0123456789abcdef";
    };
    "/etc/ssh/ssh_host_ed25519_key" = {
      stat = "0:0 600";
      text = "PRIVATE-ED25519";
    };
    "/var/lib/hermes" = {
      stat = "${toString hermesUid}:${toString hermesGid} 700";
    };
    "/var/lib/hermes/.bash_history" = {
      stat = "${toString hermesUid}:${toString hermesGid} 600";
      text = "ls -la";
    };
    "/var/lib/hermes/.hermes" = {
      stat = "${toString hermesUid}:${toString hermesGid} 2770";
    };
    "/var/lib/hermes/.hermes/state.db" = {
      stat = "${toString hermesUid}:${toString hermesGid} 660";
      text = "HERMES-DB";
    };
    "/var/lib/private" = {
      stat = "0:0 700";
    };
    # A DynamicUser service's state, owned by an id with no user.
    "/var/lib/private/llama-cpp" = {
      stat = "61234:61234 755";
    };
    "/var/lib/private/llama-cpp/state" = {
      stat = "61234:61234 644";
      text = "LLAMA-STATE";
    };
    "/var/lib/user-passwords" = {
      stat = "0:0 700";
    };
    "/var/lib/user-passwords/alex" = {
      stat = "0:0 600";
      text = alexHash;
    };
  };
  # The kept paths above that are declared themselves (state/paths.nix), so
  # each is bind-mounted from /persist; the rest come along with a parent.
  mounts = [
    "/etc/machine-id"
    "/etc/ssh/ssh_host_ed25519_key"
    "/var/lib/hermes/.bash_history"
    "/var/lib/hermes/.hermes"
    "/var/lib/private/llama-cpp"
    "/var/lib/user-passwords"
  ];
  # Hermes-owned data on @root before the first boot, in a path declared
  # ephemeral (state/paths.nix): the first boot retires it with the old root.
  stray = "/var/lib/hermes/.config/junk";

  # Writes one entry of `kept` (or `stray`) under the directory $1.
  put =
    path:
    {
      stat,
      text ? null,
    }:
    let
      parts = lib.splitString " " stat;
      owner = lib.elemAt parts 0;
      mode = lib.elemAt parts 1;
      dest = ''"$1"${lib.escapeShellArg path}'';
    in
    (
      if text == null then
        "mkdir -p ${dest}"
      else
        "mkdir -p \"$(dirname ${dest})\"; printf '%s\\n' ${lib.escapeShellArg text} > ${dest}"
    )
    + "; chown ${owner} ${dest}; chmod ${mode} ${dest}";

  # vmTools' default kernel modules, plus btrfs.
  vmTools = testPkgs.vmTools.override {
    rootModules = [
      "virtio_pci"
      "virtio_mmio"
      "virtio_blk"
      "virtio_balloon"
      "virtio_rng"
      "ext4"
      "virtiofs"
      "crc32c"
      "btrfs"
    ];
  };
  # The disk before the first boot. Built as root in a throwaway VM, since
  # the files need real owners.
  image = vmTools.runInLinuxVM (
    testPkgs.runCommand "ai-box-disk"
      {
        nativeBuildInputs = [
          testPkgs.btrfs-progs
          testPkgs.util-linux
        ];
        memSize = 1024; # MiB
        preVM = vmTools.createEmptyImage {
          size = 1024; # MiB, room for the five boots' roots
          fullName = "ai-box-disk";
        };
      }
      ''
        mkfs.btrfs -q -L ai-box /dev/vda
        mkdir /mnt
        mount /dev/vda /mnt
        for sub in @root @persist @snapshots; do btrfs subvolume create /mnt/$sub; done
        persist() { ${lib.concatStringsSep "\n" (lib.mapAttrsToList put kept)}
        }
        persist /mnt/@persist
        root() { ${
          put stray {
            stat = "${toString hermesUid}:${toString hermesGid} 644";
            text = "JUNK";
          }
        }
        }
        root /mnt/@root
        umount /mnt
      ''
  );
in
testPkgs.testers.runNixOSTest {
  name = "ai-box-persist";
  node.specialArgs = { inherit inputs; };

  nodes.box =
    { lib, ... }:
    {
      imports = [
        ./.
        ../snapshots.nix
        ../checks.nix
      ];
      # Declared by ../hermes/cron-jobs.nix on ai-box; the audit's job is unused here.
      options.aiBox.hermesCron = lib.mkOption {
        type = lib.types.attrsOf lib.types.anything;
        default = { };
      };
      config = {
        boot.initrd.systemd.enable = true;
        # These replace the VM's whole fileSystems, so /persist's
        # neededForBoot from ./persist.nix is set again here.
        virtualisation = {
          useDefaultFilesystems = false;
          memorySize = 2048; # MiB
          fileSystems = {
            "/" = {
              inherit device;
              fsType = "btrfs";
              options = subvol "@root";
            };
            "/persist" = {
              inherit device;
              fsType = "btrfs";
              options = subvol "@persist";
              neededForBoot = true;
            };
            "/persist/.snapshots" = {
              inherit device;
              fsType = "btrfs";
              options = subvol "@snapshots";
            };
          };
        };
        users.groups.hermes.gid = hermesGid;
        users.users.hermes = {
          isSystemUser = true;
          uid = hermesUid;
          group = "hermes";
          home = "/var/lib/hermes";
        };
        users.users.alex.isNormalUser = true;
        environment.systemPackages = [ testPkgs.btrfs-progs ];
      };
    };

  testScript =
    { nodes, ... }:
    ''
      import json, os, shutil

      KEPT = json.loads(${builtins.toJSON (builtins.toJSON kept)})
      MOUNTS = json.loads(${builtins.toJSON (builtins.toJSON mounts)})
      STRAY = "${stray}"
      AUDIT = ${builtins.toJSON nodes.box.aiBox.state.checkCommand}

      # The VM's disk: a writable copy of the image, where qemu-vm looks for it.
      shutil.copy("${image}/disk-image.qcow2", box.state_dir / "box.qcow2")
      os.chmod(box.state_dir / "box.qcow2", 0o644)


      def top(cmd):
          """Runs `cmd` with the btrfs top level mounted at /mnt."""
          box.succeed("mkdir -p /mnt; mountpoint -q /mnt || mount -o subvolid=5 ${device} /mnt")
          return box.succeed(cmd)


      def old_roots():
          return top("ls /mnt/old_roots").split()


      def boot(label):
          box.start()
          box.wait_for_unit("multi-user.target")
          print(f"===== {label}: {box.succeed('date -Is').strip()}, old roots: {old_roots()}")


      def check_kept():
          """Kept data is at its real path, with its owner and mode, mounted from /persist."""
          for path, want in KEPT.items():
              got = box.succeed(f"stat -c '%u:%g %a' {path}").strip()
              assert got == want["stat"], f"{path}: {got}, expected {want['stat']}"
              if "text" in want:
                  assert box.succeed(f"cat {path}").strip() == want["text"], path
          for path in MOUNTS:
              source = box.succeed(f"findmnt -n -o SOURCE --mountpoint {path}").strip()
              assert source.endswith(f"[/@persist{path}]"), f"{path} mounted from {source}"
          # Read during activation, in the initrd: only there if the initrd
          # bind mounts work.
          shadow = box.succeed("getent shadow alex | cut -d: -f2").strip()
          assert shadow == KEPT["/var/lib/user-passwords/alex"]["text"], f"alex's hash in /etc/shadow: {shadow!r}"


      with subtest("boot 1: kept data is in place, the old root is retired"):
          boot("boot 1")
          check_kept()
          box.fail(f"test -e {STRAY}")
          [first] = old_roots()
          assert top(f"stat -c '%u %a' /mnt/old_roots/{first}{STRAY}").strip() == "${toString hermesUid} 644"
          box.succeed("snapper -c persist create -d vm-test && snapper -c persist list | grep vm-test")

      with subtest("the audit reports a stray file, not the kept paths"):
          box.succeed("touch /etc/stray; echo kept > /var/lib/hermes/.hermes/written")
          status, out = box.execute(f"{AUDIT} 2>&1")
          print(out)
          assert status == 1 and "/etc/stray" in out, out
          for path in MOUNTS + ["/persist", "/var/lib/hermes/.hermes/written"]:
              assert path not in out, f"audit reported {path}"
          box.shutdown()

      with subtest("boot 2: a file written outside kept paths is gone, and in old_roots/"):
          boot("boot 2")
          check_kept()
          box.fail("test -e /etc/stray")
          box.succeed("grep kept /var/lib/hermes/.hermes/written")
          roots = old_roots()
          assert len(roots) == 2, roots
          top("test -e /mnt/old_roots/*/etc/stray")

          # For boot 3: an expired old root with a nested subvolume, a recent
          # one, an old_roots/ that looks expired itself, and a current root
          # whose timestamp is already taken.
          top(
              "btrfs subvolume create /mnt/old_roots/fake-40d"
              " && btrfs subvolume create /mnt/old_roots/fake-40d/nested"
              " && touch -d '40 days ago' /mnt/old_roots/fake-40d"
              " && btrfs subvolume create /mnt/old_roots/fake-10d"
              " && touch -d '10 days ago' /mnt/old_roots/fake-10d"
              " && touch -d '40 days ago' /mnt/old_roots"
          )
          taken = roots[0]
          top(f"touch -d '{taken.replace('_', ' ')}' /mnt/@root")
          box.shutdown()

      with subtest("boot 3: expired roots are pruned, a taken name gets a suffix"):
          boot("boot 3")
          names = old_roots()
          assert "fake-40d" not in names and "fake-10d" in names, names
          assert taken in names and f"{taken}.1" in names, names
          box.shutdown()

      with subtest("boot 4, clock behind (no RTC battery): nothing is pruned"):
          # The RTC at 1970, as after a power cut: systemd then starts the
          # clock at its own build date, months behind.
          os.environ["QEMU_OPTS"] = "-rtc base=1970-01-01T00:00:00"
          boot("boot 4")
          names4 = old_roots()
          assert set(names) < set(names4) and len(names4) == len(names) + 1, (names, names4)
          box.shutdown()
          del os.environ["QEMU_OPTS"]

      with subtest("boot 5, clock right again: still nothing pruned"):
          boot("boot 5")
          names5 = old_roots()
          assert set(names4) < set(names5), (names4, names5)
          check_kept()
          box.shutdown()
    '';
}
