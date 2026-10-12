# ai-box

NVIDIA Jetson AGX Orin 64GB devkit, running NixOS via
[jetpack-nixos](https://github.com/anduril/jetpack-nixos) (JetPack 6) with its root
filesystem on the 1TB NVMe (btrfs). The built-in 64GB eMMC is unused.

## Day to day

```shell
just ai-box-deploy   # copy config over, build + switch on ai-box (asks for sudo password)
ssh ai-box.local
```

### Snapshots (undoing an agent's mess)

The NVMe is btrfs. snapper snapshots `/` and `/home` hourly (24 hourly, 7 daily,
4 weekly kept). `/nix`, `/var/log`, and `/var/lib/docker` are separate subvolumes
that are never snapshotted, so a rollback can't erase logs of what happened.

```shell
snapper -c home list                          # what's there
snapper -c home status 41..42                 # what changed between two snapshots
snapper -c home undochange 41..0              # undo everything since #41
cp /home/.snapshots/41/snapshot/alex/file .   # or grab one file back
```

Firmware capsule updates are applied automatically on switch
(`hardware.nvidia-jetpack.firmware.autoUpdate`). Check with `ota-check-firmware`.

## Installing from scratch (no monitor needed)

Tested 2026-10-11. This installs onto the NVMe from NVIDIA's stock L4T Ubuntu
running on the eMMC, then flashes matching firmware over USB. The firmware's
boot order is NVMe first, so it boots straight into NixOS.

**Wipes the NVMe.** Back up anything on it first.

### 1. Install NixOS onto the NVMe (on the Jetson, over SSH)

```shell
# from agilite: copy the committed config over
git archive HEAD | ssh <jetson> 'mkdir -p nix-config && tar -x -C nix-config'

# on the Jetson (~1h: NVIDIA's out-of-tree kernel modules compile locally)
sudo bash nix-config/hosts/ai-box/install-from-l4t.sh ~/nix-config
```

[`install-from-l4t.sh`](install-from-l4t.sh) installs Nix if needed, releases the
NVMe, partitions it with disko, runs `nixos-install`, and carries over the Wi-Fi
profiles and SSH host keys (so the host fingerprint doesn't change). Run it as a
single `sudo` so a long build can't outlive sudo's credential cache.

### 2. Flash firmware (USB recovery mode)

Leave the Jetson's power adapter plugged in; the USB cable is data only.

1. Connect a USB-C **data** cable from agilite to the Jetson's USB-C port next to
   the 40-pin GPIO header. (Not the port the power adapter uses.)
2. Enter recovery mode: hold the **middle** button (Force Recovery), press and
   release the **right** button (Reset), keep holding the middle one ~2s, release.
   Power-cycling alone does not enter recovery mode, and until it's in recovery
   the Jetson doesn't show up on USB at all.
3. Check it's visible: `grep -l 0955 /sys/bus/usb/devices/*/idVendor` (agilite has
   no `lsusb`), or `lsusb | grep 0955:7023` where available.
4. `just ai-box-flash` and wait for `Device reported flashing succeeded`.

The Jetson reboots into NixOS within about a minute: `ssh alex@ai-box.local`.

Then **immediately run `passwd`**. alex's initial password is `password` (it's in
this public repo), and it's also what sudo asks for.

### Gotchas this hit

- **btrfs `block-group-tree`**: recent btrfs-progs enable it by default, but it
  needs Linux 6.1+. Both L4T's 5.10 and JetPack 6's 5.15 kernels refuse to mount it
  read-write, so `disko.nix` disables it.
- **Wi-Fi interface name**: L4T calls it `wlan0`, NixOS `wlP1p1s0`. Copied
  NetworkManager profiles must not pin `interface-name`.
- **Staged firmware capsule**: `nixos-install` (with `firmware.autoUpdate`) stages
  a JetPack 6 capsule and sets `OsIndications` on the old firmware. The install
  script deletes it, since the USB flash installs the right firmware anyway.
- **Keep the NVMe build off the eMMC**: the eMMC is only 64GB, and an earlier
  attempt to pre-build into its Nix store filled it. Building straight into
  `/mnt` (as the script does) avoids that.

### If it doesn't come up

- The micro-USB port on the devkit is a serial console. Plug it into another
  machine and use `tio /dev/ttyACM0` (try ACM0-3) to watch the boot.
- A failed flash can always be retried: recovery mode lives in the SoC's boot ROM.
- HDMI/DP doesn't show the Linux console on Orin; don't rely on a monitor.
