"""Source-tree CLI. Prefer the installed `f1-strategy` command."""

import sys

import _compat  # noqa: F401
from f1_strategy_optimizer.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    # Preserve explicitly requested historical data arguments from the original CLI.
    if (
        argv
        and argv[0].startswith("--")
        and any(flag in argv for flag in ("--track", "--start", "--end"))
    ):
        argv.insert(0, "optimize")
    raise SystemExit(main(argv))
