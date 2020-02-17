import os
import shutil
import subprocess
from pathlib import Path
from argparse import ArgumentParser

from .dependencies import install_dependencies


def try_symlink(source, dest, with_permission=False):
    try:
        os.symlink(source, dest)
        print("Symlinked", source, "to", dest)
    except FileExistsError:
        print("Skipping symlink-", dest, "already exists!")


def main():
    parser = ArgumentParser()
    parser.add_argument("--skip-dependency-install", action="store-true")
    args = parser.parse_args()

    if not args.skip_dependency_install:
        install_dependencies()

    home = Path("/home/alex/").resolve()
    dotfiles = Path(".").resolve()
    config = Path(".config")
    compton = config / "compton.conf"

    # Symlink dotfiles to the home directory if it's not placed there by default
    try_symlink(dotfiles, home / "dotfiles")

    # Copy compton config
    try_symlink(dotfiles / compton, home / compton)

    # Set gnome-tweak-tools to enable the material-shell
    subprocess.check_call(
        ["gnome-shell-extension-tool", "-e", "material-shell@papyelgringo"])


if __name__ == "__main__":
    main()
