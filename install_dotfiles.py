import os
import shutil
import subprocess
from pathlib import Path
from argparse import ArgumentParser


def try_symlink(source, dest, with_permission=False):
    try:
        os.symlink(source, dest)
        print("Symlinked", source, "to", dest)
    except FileExistsError:
        print("Skipping symlink-", dest, "already exists!")

def main():
    home = Path("/home/alex/").resolve()
    dotfiles = Path(".").resolve()
    builds = dotfiles / "builds"
    config = Path(".config")
    desktop = Path("Desktop")
    nautilus_desktop = "nautilus.desktop"
    awesome = config / "awesome/"
    compton = config / "compton.conf"
    i3lock_color_run_script = config / "custom_run_i3lock_color.sh"
    i3lock_color_build_script = builds / "i3lock" / "build_i3lock.sh"
 
    # Symlink dotfiles to the home directory if it's not placed there by default
    try_symlink(dotfiles, home / "dotfiles")
    # Copy awesome configs
    try_symlink(dotfiles / awesome, home / awesome)

    # Copy compton config
    try_symlink(dotfiles / compton, home / compton)

    # Copy i3lock-color custom run file
    try_symlink(dotfiles / i3lock_color_run_script,
                home / i3lock_color_run_script)

    print("Installing i3lock-color")
    subprocess.check_call(["bash", str(i3lock_color_build_script)])


if __name__ == "__main__":
    parser = ArgumentParser()
    args = parser.parse_args()

    main()
