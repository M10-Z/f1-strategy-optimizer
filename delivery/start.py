"""Launch the bundled offline workbench from any working directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from f1_strategy_optimizer.workbench import main

if __name__ == "__main__":
    raise SystemExit(main())
