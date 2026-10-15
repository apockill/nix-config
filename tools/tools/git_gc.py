from argparse import ArgumentParser
from collections.abc import Iterator
from pathlib import Path
from subprocess import check_call


def iter_git_repos(root_path: Path) -> Iterator[Path]:
    for path in Path(root_path).iterdir():
        if path.is_dir():
            if (path / ".git").is_dir():
                yield path
                continue

            yield from iter_git_repos(path)


def git_gc() -> None:
    parser = ArgumentParser(description="Recursively finds git repos and runs 'git gc'")
    parser.add_argument("root_dir", type=Path, nargs="?", default=Path("."))
    args = parser.parse_args()

    for git_dir in iter_git_repos(args.root_dir):
        print(f"Clearing {git_dir}")
        try:
            check_call(["git", "gc"], cwd=str(git_dir.resolve()))
        except Exception as ex:
            print(f"Unable to run gc on {git_dir}: {ex}")
