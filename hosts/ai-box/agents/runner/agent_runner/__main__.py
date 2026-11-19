"""`agent`: the service (`agent serve`) or the CLI for it, by the first argument."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import cli
from .server import SettingMissing, Settings, serve


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prog = Path(sys.argv[0]).name if argv is None else "agent"
    if args[:1] == ["serve"]:
        if len(args) > 1:
            print(f"{prog}: serve takes no arguments", file=sys.stderr)
            return 2
        try:
            settings = Settings.from_env(os.environ)
        except SettingMissing as e:
            print(f"{prog}: {e}", file=sys.stderr)
            return 1
        return asyncio.run(serve(settings))
    return cli.main(args, dict(os.environ), prog)


if __name__ == "__main__":
    sys.exit(main())
