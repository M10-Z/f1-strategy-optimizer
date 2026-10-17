"""Shared local JSON exports and reproducibility metadata, without plotting imports."""

import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _versions() -> dict:
    result = {"python": platform.python_version()}
    for name in ("f1-strategy-optimizer", "numpy", "pandas", "matplotlib", "fastf1"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not installed"
    return result


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
