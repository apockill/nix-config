# root-reset-apply-plan OLD NEW PLAN: build a fresh root at NEW from the
# declared state in OLD, following PLAN (./reset-plan.nix). One step per line:
#
#   copy /path    copy it from OLD to NEW, with its parent directories
#   delete /path  delete it from NEW (an ephemeral path inside a copied one)
#
# A `*` segment matches any one name: in OLD for a copy, in NEW for a delete.
# Paths that don't exist are skipped. A path is also skipped (with a warning)
# when one of its parent directories is a symlink, which could lead out of the
# tree; the path itself may be a symlink, and is copied as one.
#
# Never writes to OLD. Exits non-zero on the first failed copy or delete, and
# NEW is then incomplete: the caller discards it.
#
# Packaged by root-reset.nix (writeShellApplication adds the shebang and strict
# mode). Plain directories are enough, so it's testable without btrfs
# (test_apply_plan.py).

if [ $# -ne 3 ]; then
  echo "usage: root-reset-apply-plan OLD NEW PLAN" >&2
  exit 2
fi
old=$1
new=$2
plan=$3

if [ ! -d "$old" ] || [ ! -d "$new" ]; then
  echo "root-reset-apply-plan: $old and $new must be directories" >&2
  exit 1
fi

# nullglob: a pattern with no matches names nothing. dotglob: `*` matches
# names starting with ".", as in the audit.
shopt -s nullglob dotglob

# The existing paths `path` names under `base`, one per line, relative to it.
# Only `path` is expanded (IFS is empty so it isn't split); `base` is quoted.
expand() {
  local base=$1 path=$2 match
  local IFS=
  for match in "$base"$path; do
    if [ -e "$match" ] || [ -L "$match" ]; then
      printf '%s\n' "${match#"$base"/}"
    fi
  done
}

# Are all directories between `base` and `base/rel` real directories, not
# symlinks? `rel` itself may be anything.
parents_are_real() {
  local dir=$1 rel=$2 part
  local -a parts
  IFS=/ read -ra parts <<<"$rel"
  for part in "${parts[@]:0:${#parts[@]}-1}"; do
    dir=$dir/$part
    if [ -L "$dir" ] || [ ! -d "$dir" ]; then
      return 1
    fi
  done
}

while read -r action path; do
  case "$action" in
    copy) base=$old ;;
    delete) base=$new ;;
    *)
      echo "root-reset-apply-plan: bad plan line: $action $path" >&2
      exit 1
      ;;
  esac
  while IFS= read -r rel; do
    if ! parents_are_real "$base" "$rel"; then
      echo "warning: skipped /$rel: a parent directory is a symlink"
      continue
    fi
    echo "$action /$rel"
    if [ "$action" = copy ]; then
      # --parents recreates the parent directories with their owner, mode
      # and timestamps (-a). --reflink shares the data on btrfs.
      (cd "$old" && cp -a --reflink=auto --parents -- "$rel" "$new/")
    else
      rm -rf --one-file-system -- "${new:?}/$rel"
    fi
  done < <(expand "$base" "$path")
done <"$plan"
