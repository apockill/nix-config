from argparse import ArgumentParser
from pathlib import Path
import shutil
import os


def try_symlink(source, dest):
    try:
        os.symlink(source, dest)
        print("Symlinked", source, "to", dest)
    except FileExistsError:
        print("Skipping symlink-", dest, "already exists!")


def main():
    home = Path("/home/alex/").resolve()
    dotfiles = Path(".").resolve()
    config = Path(".config")
    awesome = config / "awesome/"
    compton = config / "compton.conf"

    # Copy awesome configs
    try_symlink(dotfiles / awesome, home / awesome)

    # Copy compton config
    try_symlink(dotfiles / compton, home / compton)


if __name__ == "__main__":
    parser = ArgumentParser()
    args = parser.parse_args()

    main()
