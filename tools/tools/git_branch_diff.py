import difflib
from argparse import ArgumentParser
from subprocess import check_output


def git_branch_diff() -> None:
    parser = ArgumentParser(
        description="Diff branches on remote and local. Make sure to run `git fetch` "
        "beforehand, for best results!"
    )
    # No arguments, but still handle --help and reject unknown ones.
    parser.parse_args()

    # Get remote branches
    remote_branches = check_output(["git", "branch", "-r"]).decode("ascii")

    local_branches = check_output(["git", "branch"]).decode("ascii")

    diff = "".join(
        difflib.Differ().compare(
            a=remote_branches.splitlines(True), b=local_branches.splitlines(True)
        )
    )
    print(diff, end="")
