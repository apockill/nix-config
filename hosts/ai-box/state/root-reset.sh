# root-reset DEVICE TOP PLAN: replace the root subvolume with a fresh one that
# holds only the declared state. Runs in the initrd before the root is
# mounted (root-reset.nix); the layout is described in ./default.nix.
#
#   1. Mount DEVICE's btrfs top level (subvolid=5) on TOP.
#   2. Build @root-new from @root with root-reset-apply-plan and PLAN.
#   3. Swap @root and @root-new in one atomic rename (mv --exchange), then
#      move the old root to @root-old/<N>, N one more than the highest there.
#   4. Delete all but the newest $KEEP old roots.
#
# Fail-safe: until the swap, @root is untouched. If anything fails before it,
# @root-new is deleted and the box boots the old root as it was. A @root-new
# left by an interrupted reset (power cut, timeout) is kept as an old root,
# since after the swap it holds the previous root.
#
# Every step is logged to stdout (the journal and console) and saved to
# /var/lib/root-reset/initrd.log in the root that boots, with a summary in
# /var/lib/root-reset/info, which the post-boot report reads.
#
# Packaged by root-reset.nix (writeShellApplication adds the shebang, strict
# mode and root-reset-apply-plan on PATH). test_root_reset.py runs it on
# plain directories with stand-ins for mount and btrfs.

if [ $# -ne 3 ]; then
  echo "usage: root-reset DEVICE TOP PLAN" >&2
  exit 2
fi
device=$1
top=$2
plan=$3

# How many old roots to keep.
KEEP=5
# Where this reset's log and summary go, relative to the root that boots.
REPORT_DIR=var/lib/root-reset

old_roots=$top/@root-old
building=$top/@root-new
log_buffer=$(mktemp -p "${TMPDIR:-/run}" root-reset.XXXXXX)
# The clock may read 1970 after a power cut (no RTC battery), so it's only
# recorded, never used to name anything.
clock=$(date -u +%Y-%m-%dT%H:%M:%SZ)
boot_id=$(cat /proc/sys/kernel/random/boot_id)
# The number of the old root this boot retired, once it has.
retired=

log() {
  printf '%s\n' "$*" | tee -a "$log_buffer"
}

# The old root numbers, oldest first.
old_root_numbers() {
  local entry name
  for entry in "$old_roots"/*; do
    name=${entry##*/}
    if [[ $name =~ ^[0-9]+$ ]]; then
      echo "$name"
    fi
  done | sort -n
}

# One more than the highest old root number.
next_number() {
  local highest
  highest=$(old_root_numbers | tail -n 1)
  echo $((${highest:-0} + 1))
}

# Delete subvolume `path` and any subvolumes nested in it, deepest first.
# `subvolume list -o` prints paths relative to the top level.
delete_subvolume() {
  local path=$1 line
  while IFS= read -r line; do
    delete_subvolume "$top/${line#* path }"
  done < <(btrfs subvolume list -o "$path")
  btrfs subvolume delete "$path" >/dev/null
}

# Move subvolume `path` to the next @root-old/<N> with an info file next to
# it, and set `retired` to N. Moves nothing if it fails.
retire() {
  local path=$1 why=$2 n
  n=$(next_number)
  mv -T "$path" "$old_roots/$n" || return 1
  retired=$n
  printf 'n=%s\nwhy=%s\nboot_id=%s\nclock=%s\n' "$n" "$why" "$boot_id" "$clock" \
    >"$old_roots/$n.info" || true
  log "kept ${path#"$top"/} as @root-old/$n ($why)"
}

# Save the log and a summary into the root that boots (@root by now).
save_report() {
  local result=$1 dir=$top/@root/$REPORT_DIR
  mkdir -p "$dir"
  cp "$log_buffer" "$dir/initrd.log"
  printf 'result=%s\nold_root=%s\nboot_id=%s\nclock=%s\n' \
    "$result" "$retired" "$boot_id" "$clock" >"$dir/info"
}

# Give up before the swap: delete @root-new, so @root boots as it was.
give_up() {
  log "ERROR: $1; booting the current root unchanged"
  if [ -e "$building" ]; then
    delete_subvolume "$building" || log "ERROR: couldn't delete @root-new"
  fi
  retired=
  save_report failed
  exit 1
}

trap 'umount "$top" 2>/dev/null || true; rm -f "$log_buffer"' EXIT

log "root-reset: boot $boot_id, clock $clock"
mkdir -p "$top"
mount -t btrfs -o subvolid=5 "$device" "$top"
mkdir -p "$old_roots"

if [ -e "$building" ]; then
  retire "$building" "@root-new left by an interrupted reset" ||
    give_up "couldn't move away the @root-new left by an interrupted reset"
fi

log "building @root-new from the declared state in @root"
if ! btrfs subvolume create "$building" >/dev/null ||
  ! root-reset-apply-plan "$top/@root" "$building" "$plan" 2>&1 | tee -a "$log_buffer" ||
  ! btrfs filesystem sync "$top" >/dev/null; then
  give_up "building the new root failed"
fi

# The swap: afterwards @root is the new root and @root-new holds the old one.
if ! mv -T --exchange "$building" "$top/@root"; then
  give_up "couldn't swap in the new root"
fi
log "swapped in the new root"

status=0
if ! retire "$building" "the root until boot $boot_id"; then
  log "ERROR: couldn't move the old root to @root-old; the next boot keeps it"
  status=1
fi

while read -r n; do
  if delete_subvolume "$old_roots/$n"; then
    rm -f "$old_roots/$n.info"
    log "deleted @root-old/$n (keeping the newest $KEEP)"
  else
    log "ERROR: couldn't delete @root-old/$n"
    status=1
  fi
done < <(old_root_numbers | head -n -"$KEEP")

save_report reset
exit "$status"
