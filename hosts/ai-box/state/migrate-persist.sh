#!/usr/bin/env bash
# ONE-TIME MIGRATION (see ./migrate-persist.nix): copy every persisted path
# from @root into a new @persist. Runs in the initrd, before wipe-root.
#
# Usage: migrate-persist.sh DEVICE LIST
#   DEVICE  the btrfs partition
#   LIST    one "dir PATH" or "file PATH" per line
#
# Exits 0 if @persist already exists or the copy worked. On any failure it
# makes @persist a snapshot of @root instead (so /persist mounts with all the
# data) and exits 1, which skips wipe-root.
set -euo pipefail

device=$1
list=$2
top=/migrate-persist # where the btrfs top level (subvolid=5) is mounted

mkdir -p "$top"
mount -o subvolid=5 "$device" "$top"
trap 'cd / && umount "$top"' EXIT

if [[ -e $top/@persist ]]; then
    echo "@persist exists; nothing to migrate"
    exit 0
fi

# Copy into @persist-new with shared extents; --parents gives the parent
# directories their owner and mode from @root. set -e is off inside a function
# called from `if`, so every step checks its own result.
copy() {
    local kind path
    if [[ -e $top/@persist-new ]]; then # left by an interrupted boot
        btrfs subvolume delete "$top/@persist-new" || return 1
    fi
    btrfs subvolume create "$top/@persist-new" || return 1
    cd "$top/@root" || return 1
    while read -r kind path; do
        if [[ ! -e .$path && ! -L .$path ]]; then
            echo "not on @root, skipped: $path"
            continue
        fi
        if [[ -L .$path || ($kind == dir && ! -d .$path) || ($kind == file && ! -f .$path) ]]; then
            echo "$path is declared as a $kind but isn't one" >&2
            return 1
        fi
        cp -a --reflink=always --parents ".$path" "$top/@persist-new/" || return 1
        echo "copied: $path"
    done <"$list"
}

if copy && mv "$top/@persist-new" "$top/@persist"; then
    echo "migrated: @persist created"
else
    echo "migration failed: @persist is a snapshot of @root, and the root is not wiped this boot" >&2
    cd /
    btrfs subvolume delete "$top/@persist-new" || true
    btrfs subvolume snapshot "$top/@root" "$top/@persist"
    exit 1
fi
