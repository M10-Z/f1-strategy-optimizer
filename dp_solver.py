"""Legacy argument names with explicit model injection. See docs/migration.md."""

import _compat  # noqa: F401
from f1_strategy_optimizer import RaceConfig, RuleSet
from f1_strategy_optimizer.solver import PitStrategy
from f1_strategy_optimizer.solver import solve as _solve

__all__ = ["PitStrategy", "solve"]


def solve(
    total_laps,
    pit_loss_time=24.0,
    track_temp=None,
    starting_compound=None,
    max_tyre_age=50,
    *,
    model=None,
    rules=None,
    pit_loss_overrides=None,
):
    if model is None:
        raise ValueError("Pass model=fit_tyre_degradation(df); global fitted models were removed")
    return _solve(
        model,
        RaceConfig(
            total_laps=total_laps,
            pit_loss=pit_loss_time,
            track_temp=35.0 if track_temp is None else track_temp,
            starting_compound=starting_compound.upper() if starting_compound else None,
            max_tyre_age=max_tyre_age,
            rules=rules or RuleSet(),
            pit_loss_overrides=pit_loss_overrides or {},
        ),
    )
