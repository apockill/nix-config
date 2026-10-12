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

> **Untested draft.** Written before the first install; will be corrected
> against what actually happens.

This installs onto the NVMe from whatever Linux is already running on the Jetson
(e.g. NVIDIA's stock L4T Ubuntu on the eMMC), then flashes matching firmware over
USB. The firmware's boot order is NVMe first, so it boots straight into NixOS.

**Wipes the NVMe.** Back up anything on it first.

### 1. Build the firmware flash script (on an x86_64 machine)

```shell
nix build .#ai-box-flash-script   # -> ./result/bin/initrd-flash-orin-agx-devkit
```

### 2. Install NixOS onto the NVMe (on the Jetson, over SSH)

```shell
# Nix itself, if the running OS doesn't have it
sh <(curl -L https://nixos.org/nix/install) --daemon

# Nothing may be using the NVMe: stop services using it, unmount it,
# and remove it from /etc/fstab.

# Partition, format, and mount at /mnt according to hosts/ai-box/disko.nix
sudo nix --experimental-features 'nix-command flakes' run github:nix-community/disko -- \
  --mode destroy,format,mount --flake github:apockill/nix-config#ai-box

# Build (natively, on the Jetson) and install
sudo nix --experimental-features 'nix-command flakes' run nixpkgs#nixos-install-tools -- \
  nixos-install --flake github:apockill/nix-config#ai-box --root /mnt --no-root-passwd

# Carry over state that doesn't belong in git
sudo mkdir -p /mnt/etc/NetworkManager/system-connections /mnt/etc/ssh
sudo cp -a /etc/NetworkManager/system-connections/*.nmconnection /mnt/etc/NetworkManager/system-connections/
sudo cp -a /etc/ssh/ssh_host_*_key* /mnt/etc/ssh/   # keeps the host's SSH fingerprint
```

### 3. Flash firmware (USB recovery mode)

1. Connect the Jetson's USB-C flashing port (next to the 40-pin header) to the
   x86_64 machine with a USB-C **data** cable.
2. With the Jetson powered on, hold the middle (recovery) button, tap reset (right
   button), release.
3. `lsusb | grep 0955:7023` should show `NVIDIA Corp. APX`.
4. `just ai-box-flash` (builds the script if needed, then runs it with sudo)

When it finishes, the Jetson reboots into NixOS: `ssh alex@ai-box.local`.

Then **immediately run `passwd`**. alex's initial password is `password` (it's in
this public repo), and it's also what sudo asks for.

### If it doesn't come up

- The micro-USB port on the devkit is a serial console. Plug it into another
  machine and use `tio /dev/ttyACM0` (try ACM0-3) to watch the boot.
- A failed flash can always be retried: recovery mode lives in the SoC's boot ROM.
- HDMI/DP doesn't show the Linux console on Orin; don't rely on a monitor.
