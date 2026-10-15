"""State audit: what on the root filesystem would be lost by a root wipe?

Walks the root subvolume (other subvolumes and mounts are skipped by device
id) and compares it with the declared state list (aiBox.state.paths). Anything
not covered by a declared path is "unexplained": today it survives, but it
would be lost once the root is wiped on boot (impermanence stage 3).

Symlinks into /nix/store, /etc/static, /etc/zoneinfo, /proc or /run are
system-managed (recreated at boot or activation) and ignored. Empty
directories are ignored (systemd-tmpfiles recreates them).

Usage:
  audit.py <declared.json> <out-dir>   write report.json + summary.txt
  audit.py --check <declared.json>     exit 1 if anything is unexplained
"""

import json
import os
import stat
import sys
import time

MAX_LIST = 200
LARGE_EPHEMERAL = 500e6  # flag "ephemeral" paths this big: are they really disposable?
MANAGED_LINK_TARGETS = ("/nix/store/", "/etc/static/", "/etc/zoneinfo/", "/proc/",
                        "/run/", "../run")


def load_declared(path):
    with open(path) as f:
        return json.load(f)  # {path: {"backup": ..., "why": ..., "repo": ...}}


def covered(path, declared):
    """Is `path` itself declared, or inside a declared path?"""
    p = path
    while p and p != "/":
        if p in declared:
            return True
        p = os.path.dirname(p)
    return False


def has_declared_below(path, declared_sorted):
    prefix = path.rstrip("/") + "/"
    return any(d.startswith(prefix) for d in declared_sorted)


def managed_symlink(path):
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return target.startswith(MANAGED_LINK_TARGETS)


def summarize(path, dev):
    """(bytes, files, newest_mtime) of a tree on one device."""
    size = files = 0
    newest = 0.0
    for dp, dns, fns in os.walk(path, onerror=lambda e: None):
        kept = []
        for d in dns:
            full = os.path.join(dp, d)
            try:
                s = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISDIR(s.st_mode) and s.st_dev == dev:
                kept.append(d)
        dns[:] = kept
        for f in fns:
            full = os.path.join(dp, f)
            try:
                s = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(s.st_mode) and managed_symlink(full):
                continue
            size += s.st_size if stat.S_ISREG(s.st_mode) else 0
            files += 1
            newest = max(newest, s.st_mtime)
    return size, files, newest


def audit(declared):
    root_dev = os.stat("/").st_dev
    declared_sorted = sorted(declared)
    unexplained = []

    def visit(path):
        try:
            s = os.lstat(path)
        except OSError:
            return
        if s.st_dev != root_dev:
            return  # another subvolume or a mount (/nix, /home, /proc, ...)
        if covered(path, declared):
            return
        if stat.S_ISLNK(s.st_mode):
            if not managed_symlink(path):
                unexplained.append({"path": path, "bytes": 0, "files": 1,
                                    "newest": s.st_mtime, "kind": "symlink"})
            return
        if not stat.S_ISDIR(s.st_mode):
            unexplained.append({"path": path, "bytes": s.st_size, "files": 1,
                                "newest": s.st_mtime, "kind": "file"})
            return
        if has_declared_below(path, declared_sorted):
            try:
                children = sorted(os.listdir(path))
            except OSError:
                return
            for c in children:
                visit(os.path.join(path, c))
            return
        size, files, newest = summarize(path, root_dev)
        if files:
            unexplained.append({"path": path, "bytes": size, "files": files,
                                "newest": newest, "kind": "dir"})

    visit("/")
    return unexplained


def declared_status(declared):
    """Per declared path: size of what it covers itself, i.e. minus nested
    declared paths (which may have a different backup class)."""
    totals = {}
    for p in declared:
        size = files = 0
        if os.path.isdir(p) and not os.path.islink(p):
            size, files, _ = summarize(p, os.stat(p).st_dev)
        elif os.path.lexists(p):
            size, files = os.lstat(p).st_size, 1
        totals[p] = (size, files)

    def parent_decl(p):
        q = os.path.dirname(p)
        while q and q != "/":
            if q in declared:
                return q
            q = os.path.dirname(q)
        return None

    own = dict(totals)
    for p in declared:
        parent = parent_decl(p)
        if parent:
            ps, pf = own[parent]
            own[parent] = (ps - totals[p][0], pf - totals[p][1])
    return [{"path": p, **d, "exists": os.path.lexists(p),
             "bytes": max(0, own[p][0]), "files": max(0, own[p][1])}
            for p, d in sorted(declared.items())]


def main():
    if sys.argv[1] == "--check":
        unexplained = audit(load_declared(sys.argv[2]))
        for u in unexplained[:MAX_LIST]:
            print(f"  {u['path']}  ({u['files']} files, {u['bytes'] / 1e6:.1f} MB)")
        sys.exit(1 if unexplained else 0)

    declared = load_declared(sys.argv[1])
    out_dir = sys.argv[2]
    unexplained = audit(declared)
    report = {
        "generated": round(time.time(), 1),
        "unexplained": unexplained,
        "declared": declared_status(declared),
    }
    tmp = os.path.join(out_dir, "report.json.tmp")
    with open(tmp, "w") as f:
        json.dump(report, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "report.json"))

    # Stable summary for the cron monitor: paths only, no sizes or times.
    parts = []
    lines = [u["path"] for u in unexplained][:MAX_LIST]
    if lines:
        parts.append("UNEXPLAINED STATE (would be lost on a root wipe):\n" + "\n".join(lines))
    large = [d["path"] for d in report["declared"]
             if d["backup"] == "ephemeral" and d["bytes"] > LARGE_EPHEMERAL]
    if large:
        parts.append("LARGE EPHEMERAL (over 500 MB, declared disposable; is that right?):\n"
                     + "\n".join(large))
    summary = "\n".join(parts) or "OK: all state on the root filesystem is declared"
    tmp = os.path.join(out_dir, "summary.txt.tmp")
    with open(tmp, "w") as f:
        f.write(summary + "\n")
    os.replace(tmp, os.path.join(out_dir, "summary.txt"))
    print(summary)


if __name__ == "__main__":
    main()
