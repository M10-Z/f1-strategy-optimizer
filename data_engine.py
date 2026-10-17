"""Compatibility import. Cache initialization occurs only when fetching data."""

import _compat  # noqa: F401
from f1_strategy_optimizer.data import fetch_cycle_data

__all__ = ["fetch_cycle_data"]
