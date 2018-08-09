import os
import shutil
import subprocess
from pathlib import Path
from argparse import ArgumentParser


def try_symlink(source, dest):
    try:
        os.symlink(source, dest)
        print("Symlinked", source, "to", dest)
    except FileExistsError:
        print("Skipping symlink-", dest, "already exists!")


def try_patching(existing_file, patchfile):
    if not existing_file.exists():
        print("ERROR: Cannot find", existing_file, ", unable to patch!")
        return
    assert patchfile.exists()
    print("AYY", "sudo patch " + str(existing_file) + " " + str(patchfile))
    subprocess.check_call(["sudo", "patch",
                           str(existing_file), str(patchfile)])


def main():
    home = Path("/home/alex/").resolve()
    dotfiles = Path(".").resolve()
    config = Path(".config")
    awesome = config / "awesome/"
    compton = config / "compton.conf"
    remote_desktop = Path("/opt/google/chrome-remote-desktop") / \
                     "chrome-remote-desktop"
    remote_desktop_patch = Path(
        "./patches/chrome-remote-desktop.patch").resolve()

    # Copy awesome configs
    try_symlink(dotfiles / awesome, home / awesome)

    # Copy compton config
    try_symlink(dotfiles / compton, home / compton)

    # Try patching chrome remote desktop file
    try_patching(remote_desktop, remote_desktop_patch)


if __name__ == "__main__":
    parser = ArgumentParser()
    args = parser.parse_args()

    main()
