from argparse import ArgumentParser
from pathlib import Path
import shutil
import os


def copy_dir(source, dest, overwrite_existing_files=False):
    dest.mkdir(parents=True, exist_ok=True)
    print("Creating", source, dest)

    for path in Path(source).iterdir():
        # Make sure all directories exist
        if path.is_dir():
            copy_dir(path, dest / path.name, overwrite_existing_files)

        if path.is_file():
            if (dest / path.name).exists():
                if overwrite_existing_files:
                    os.remove(dest / path.name)
                    shutil.copy(str(path), str(dest / path.name))
                    print("Overwriting", str(dest / path.name))
                else:
                    print(str(path), "already exists! Skipping copy...")
            else:
                shutil.copy(str(path),
                            str(dest / path.name))


def main():
    home = Path("/home/alex/").resolve()
    dotfiles = Path(".").resolve()
    config = Path(".config")
    awesome = config / "awesome/"

    # Copy awesome configs
    os.symlink(dotfiles / awesome, home / awesome)


if __name__ == "__main__":
    parser = ArgumentParser()
    args = parser.parse_args()

    main()
