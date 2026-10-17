"""Explicit scenario constraints; these are not a complete FIA compliance engine."""

from dataclasses import dataclass, field
from math import isfinite
from numbers import Real


def positive_int(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def finite_number(value, name: str, minimum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


@dataclass(frozen=True)
class RuleSet:
    name: str = "simplified-dry"
    season: int | None = None
    event: str = "unspecified"
    version: str = "research-v1"
    source: str = "User-configured constraints; not full FIA compliance"
    min_compounds: int = 2
    min_stints: int = 1

    def __post_init__(self):
        positive_int(self.min_compounds, "min_compounds")
        positive_int(self.min_stints, "min_stints")
        if self.season is not None:
            positive_int(self.season, "season")


@dataclass(frozen=True)
class RaceConfig:
    total_laps: int = 57
    pit_loss: float = 24.0
    track_temp: float = 35.0
    max_tyre_age: int = 50
    starting_compound: str | None = None
    rules: RuleSet = field(default_factory=RuleSet)
    # Known, exogenous net pit-loss scenarios, keyed by lap END.
    pit_loss_overrides: dict[int, float] = field(default_factory=dict)
    compound_age_limits: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        positive_int(self.total_laps, "total_laps")
        positive_int(self.max_tyre_age, "max_tyre_age")
        finite_number(self.pit_loss, "pit_loss", 0)
        finite_number(self.track_temp, "track_temp")
        if not isinstance(self.rules, RuleSet):
            raise ValueError("rules must be a RuleSet")
        if not isinstance(self.pit_loss_overrides, dict):
            raise ValueError("pit_loss_overrides must be a dictionary")
        if not isinstance(self.compound_age_limits, dict):
            raise ValueError("compound_age_limits must be a dictionary")
        for lap, loss in self.pit_loss_overrides.items():
            positive_int(lap, "override lap")
            if lap >= self.total_laps:
                raise ValueError("Pit-loss override must precede the finish")
            finite_number(loss, "pit-loss override", 0)
        for compound, limit in self.compound_age_limits.items():
            if not isinstance(compound, str) or not compound:
                raise ValueError("Age-limit keys must be compound names")
            positive_int(limit, "compound age limit")

    def age_limit(self, compound: str) -> int:
        return min(self.max_tyre_age, self.compound_age_limits.get(compound, self.max_tyre_age))

    def loss_at(self, lap: int) -> float:
        return self.pit_loss_overrides.get(lap, self.pit_loss)
