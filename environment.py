"""Explicit deterministic pit-loss scenarios; no inferred rain/compliance exemption.

Use RaceConfig(pit_loss_overrides={25: 12.0}) for known reduced-loss laps.
Weather-driven wet tyre models and stochastic safety-car processes are not implemented.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LapEnvironment:
    lap: int
    is_wet: bool = False
    safety_car_active: bool = False
    pit_loss_override: float | None = None


def get_effective_pit_loss(lap, base_pit_loss=24.0, *, overrides=None):
    import _compat  # noqa: F401
    from f1_strategy_optimizer.config import finite_number, positive_int

    positive_int(lap, "lap")
    finite_number(base_pit_loss, "base_pit_loss", 0)
    value = (overrides or {}).get(lap, base_pit_loss)
    finite_number(value, "pit_loss", 0)
    return value
