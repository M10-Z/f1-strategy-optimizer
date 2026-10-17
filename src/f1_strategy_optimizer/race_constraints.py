"""Explicit race-specific constraint subsets; never automatic FIA rule selection."""

from dataclasses import dataclass, field

from .config import positive_int


class InfeasibleRacePlan(ValueError):
    """A supplied action or complete rollout violates a configured constraint."""


def nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class CompetitionRules:
    season: int | None = None
    event: str = "unspecified"
    version: str = "research-v1"
    source: str = "User-configured assumptions; no automatic regulation selection"
    source_status: str = "configurable_assumption"
    min_dry_compounds: int = 0
    min_stops: int = 0
    allowed_compounds: tuple[str, ...] = ()
    mandatory_dry_compounds: tuple[str, ...] = ()  # At least one, when dry requirements apply.
    wet_compounds: tuple[str, ...] = ("INTERMEDIATE", "WET")
    wet_waives_dry_requirement: bool = False
    max_tyre_age: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        nonnegative_int(self.min_dry_compounds, "min_dry_compounds")
        nonnegative_int(self.min_stops, "min_stops")
        if self.season is not None:
            positive_int(self.season, "rule season")
        if self.source_status not in {"configurable_assumption", "source_checked_subset"}:
            raise ValueError("Rule source status must describe assumptions or a checked subset")
        if not all(
            isinstance(s, str) and s.strip() for s in (self.event, self.version, self.source)
        ):
            raise ValueError("Rules need event, version and source metadata")
        if not isinstance(self.wet_waives_dry_requirement, bool):
            raise ValueError("wet_waives_dry_requirement must be boolean")
        for name in ("allowed_compounds", "mandatory_dry_compounds", "wet_compounds"):
            values = tuple(getattr(self, name))
            if any(not isinstance(c, str) or not c for c in values) or len(set(values)) != len(
                values
            ):
                raise ValueError(f"{name} must contain unique compound names")
            object.__setattr__(self, name, values)
        if set(self.mandatory_dry_compounds) & set(self.wet_compounds):
            raise ValueError("Mandatory dry compounds cannot be wet compounds")
        for compound, age in self.max_tyre_age.items():
            if not isinstance(compound, str) or not compound:
                raise ValueError("Age limits need compound names")
            positive_int(age, "maximum tyre age")
        if self.active and (self.season is None or self.event == "unspecified"):
            raise ValueError("Active constraints require an explicit season and event")

    @property
    def active(self):
        return bool(
            self.min_dry_compounds
            or self.min_stops
            or self.allowed_compounds
            or self.mandatory_dry_compounds
            or self.max_tyre_age
        )

    def check_scope(self, state):
        if self.active and (self.season != state.season or self.event != state.event):
            raise ValueError("Rule season/event does not match the race snapshot")

    def check_lap(self, car, next_age):
        if self.allowed_compounds and car.compound not in self.allowed_compounds:
            raise InfeasibleRacePlan(f"{car.driver}: compound {car.compound} is not permitted")
        if car.compound in self.max_tyre_age and next_age > self.max_tyre_age[car.compound]:
            raise InfeasibleRacePlan(f"{car.driver}: tyre age exceeds configured limit")

    def check_finish(self, car):
        if car.pit_stops < self.min_stops:
            raise InfeasibleRacePlan(f"{car.driver}: fewer than {self.min_stops} required stops")
        used = set(car.used_compounds)
        if self.allowed_compounds and used - set(self.allowed_compounds):
            raise InfeasibleRacePlan(f"{car.driver}: prior use of a non-permitted compound")
        waived = self.wet_waives_dry_requirement and bool(used & set(self.wet_compounds))
        if not waived:
            if len(used - set(self.wet_compounds)) < self.min_dry_compounds:
                raise InfeasibleRacePlan(f"{car.driver}: insufficient distinct dry compounds")
            if self.mandatory_dry_compounds and not used.intersection(self.mandatory_dry_compounds):
                raise InfeasibleRacePlan(f"{car.driver}: no configured mandatory dry compound used")
