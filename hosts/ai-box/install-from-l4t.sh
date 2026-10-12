#!/usr/bin/env bash
# Install NixOS onto ai-box's NVMe from the L4T Ubuntu running on its eMMC.
# WIPES THE NVMe. Run on the Jetson as root, with a copy of this repo:
#
#   sudo bash install-from-l4t.sh /home/alex/nix-config
#
# Then flash firmware from an x86_64 machine (`just ai-box-flash`).
# See hosts/ai-box/README.md.
set -euo pipefail
SRC=$(realpath "${1:?usage: $0 <path to nix-config checkout>}")
FLAKE="path:$SRC#ai-box"
log() { echo "[$(date +%T)] $*"; }

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
if ! command -v nix >/dev/null; then
  [ -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ] ||
    sh <(curl -L https://nixos.org/nix/install) --daemon --yes
  . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi
nixx() { nix --extra-experimental-features 'nix-command flakes' "$@"; }

NVME=$(nixx eval --raw "path:$SRC#nixosConfigurations.ai-box.config.disko.devices.disk.nvme.device")
[ -e "$NVME" ] || { echo "NVMe $NVME not found"; exit 1; }

log "1/6 release the NVMe (stop docker, unmount, drop from fstab)"
systemctl disable --now docker.socket docker.service containerd.service 2>/dev/null || true
for m in $(lsblk -nrpo MOUNTPOINT "$(realpath "$NVME")" | grep -v '^$'); do umount -R "$m"; done
cp /etc/fstab /etc/fstab.pre-nixos
for uuid in $(lsblk -nro UUID "$(realpath "$NVME")" | grep -v '^$'); do
  sed -i "s|^\(UUID=$uuid .*\)|# removed for NixOS install: \1|" /etc/fstab
done

log "2/6 partition + format + mount at /mnt (disko, same rev as flake.lock)"
DISKO_REV=$(nixx eval --raw --impure --expr \
  "(builtins.fromJSON (builtins.readFile $SRC/flake.lock)).nodes.disko.locked.rev")
nixx run "github:nix-community/disko/$DISKO_REV" -- \
  --mode destroy,format,mount --yes-wipe-all-disks --flake "$FLAKE"
findmnt -R /mnt
mkdir -p /mnt/var/tmp

log "3/6 nixos-install (builds natively onto the NVMe; ~1h, mostly NVIDIA modules)"
INSTALL=$(nixx build --no-link --print-out-paths \
  "path:$SRC#nixosConfigurations.ai-box.config.system.build.nixos-install")
TMPDIR=/mnt/var/tmp "$INSTALL/bin/nixos-install" \
  --flake "$FLAKE" --root /mnt --no-root-passwd --no-channel-copy

log "4/6 carry over Wi-Fi profiles and SSH host keys"
# L4T names the card wlan0; NixOS calls it wlP1p1s0. Unpin profiles from
# interface names or NetworkManager silently ignores them.
install -d -m 700 /mnt/etc/NetworkManager/system-connections
for f in /etc/NetworkManager/system-connections/*.nmconnection; do
  [ -e "$f" ] || continue
  sed '/^interface-name=/d' "$f" > "/mnt/etc/NetworkManager/system-connections/$(basename "$f")"
  chmod 600 "/mnt/etc/NetworkManager/system-connections/$(basename "$f")"
done
install -d -m 755 /mnt/etc/ssh
for k in ed25519 rsa; do
  install -m 600 /etc/ssh/ssh_host_${k}_key /mnt/etc/ssh/
  install -m 644 /etc/ssh/ssh_host_${k}_key.pub /mnt/etc/ssh/
done

log "5/6 drop the firmware capsule nixos-install staged"
# firmware.autoUpdate sees the old JetPack 5 firmware, stages a JetPack 6 capsule
# on the ESP, and sets OsIndications on the *old* firmware. Any reboot before the
# USB flash would then self-update without the NVMe-first boot order. The USB
# flash installs the right firmware anyway.
rm -rf /mnt/boot/EFI/UpdateCapsule

log "6/6 unmount; ready for the firmware flash"
rm -rf /mnt/var/tmp/nix-*
df -h /mnt /mnt/boot
sync
umount -R /mnt
log "done. Next: put the Jetson in recovery mode and run \`just ai-box-flash\`."
