"""Forward DP with terminal settlement and complete path reconstruction."""

from dataclasses import asdict, dataclass
from math import inf
from typing import Protocol

from .config import RaceConfig, finite_number, positive_int


class LapTimeModel(Protocol):
    @property
    def compounds(self) -> tuple[str, ...]: ...

    def predict(self, compound: str, age: int, track_temp: float = 35.0) -> float: ...


class InfeasibleStrategyError(ValueError):
    """No complete, positive-length strategy satisfies the configured constraints."""


@dataclass
class PitStrategy:
    total_time: float
    pit_laps: list[int]
    compounds_used: list[str]
    stint_lengths: list[int]

    @property
    def compounds_set(self) -> set[str]:
        return set(self.compounds_used)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "compounds_set": sorted(self.compounds_set),
            "claim": "Optimal only under the supplied deterministic model and constraints",
        }

    def __str__(self) -> str:
        stints = " -> ".join(f"{c} x {n}" for c, n in zip(self.compounds_used, self.stint_lengths))
        return (
            f"Model-relative optimum: {self.total_time:.3f} s\n{stints}\n"
            f"Pit after laps: {self.pit_laps or 'none (zero stops)'}"
        )


def _compounds(model: LapTimeModel, config: RaceConfig) -> tuple[str, ...]:
    compounds = tuple(model.compounds)
    if not compounds or len(set(compounds)) != len(compounds):
        raise ValueError("Model must expose nonempty, unique compounds")
    if any(not isinstance(c, str) or not c for c in compounds):
        raise ValueError("Compound names must be nonempty strings")
    if config.starting_compound is not None and config.starting_compound not in compounds:
        raise ValueError("starting_compound is not available in the model")
    if set(config.compound_age_limits) - set(compounds):
        raise ValueError("Age limits refer to compounds absent from the model")
    if (
        config.rules.min_compounds > min(len(compounds), config.total_laps)
        or config.rules.min_stints > config.total_laps
    ):
        raise InfeasibleStrategyError("Not enough compounds or laps for the requested rules")
    return compounds


def solve(model: LapTimeModel, config: RaceConfig | None = None) -> PitStrategy:
    """Minimize time. State: compound, age, used-mask, capped stint count.

    Precompute all C*A lap costs once. No terminal pit transition exists.
    Cost tables use O(S) memory; parent pointers require O(N*S).
    """
    config = config or RaceConfig()
    compounds = _compounds(model, config)
    bits = {c: 1 << i for i, c in enumerate(compounds)}
    costs = {}
    for c in compounds:
        for age in range(1, min(config.total_laps, config.age_limit(c)) + 1):
            value = model.predict(c, age, config.track_temp)
            finite_number(value, "predicted lap time", 0)
            if value == 0:
                raise ValueError("Predicted lap time must be positive")
            costs[c, age] = float(value)
    starts = (config.starting_compound,) if config.starting_compound else compounds
    current = {(c, 1, bits[c], 1): 0.0 for c in starts}
    parents = {}
    best_state, best_cost = None, inf
    for lap in range(1, config.total_laps + 1):
        following = {}
        for state, elapsed in current.items():
            c, age, mask, stints = state
            completed_cost = elapsed + costs[c, age]
            if lap == config.total_laps:
                if mask.bit_count() >= config.rules.min_compounds:
                    if stints >= config.rules.min_stints and completed_cost < best_cost:
                        best_state, best_cost = state, completed_cost
                continue
            transitions = []
            if age < config.age_limit(c):
                transitions.append(((c, age + 1, mask, stints), completed_cost, False))
            for new_c in compounds:
                next_state = (
                    new_c,
                    1,
                    mask | bits[new_c],
                    min(stints + 1, config.rules.min_stints),
                )
                transitions.append((next_state, completed_cost + config.loss_at(lap), True))
            for target, value, did_pit in transitions:
                if value < following.get(target, inf):
                    following[target] = value
                    parents[lap + 1, target] = (state, did_pit)
        current = following
    if best_state is None:
        raise InfeasibleStrategyError("No strategy satisfies the configured constraints")
    # Each entry is a compound actually driven, plus whether a pit preceded it.
    path = [(best_state[0], False)]
    state = best_state
    for lap in range(config.total_laps, 1, -1):
        previous, did_pit = parents[lap, state]
        path[-1] = (state[0], did_pit)
        path.append((previous[0], False))
        state = previous
    path.reverse()
    sequence, lengths, pit_laps = [path[0][0]], [1], []
    for lap, (compound, did_pit) in enumerate(path[1:], start=2):
        if did_pit:
            pit_laps.append(lap - 1)
            sequence.append(compound)
            lengths.append(1)
        else:
            lengths[-1] += 1
    result = PitStrategy(best_cost, pit_laps, sequence, lengths)
    # Independently sum the returned schedule, catching reconstruction drift.
    checked = evaluate_strategy(model, config, sequence, lengths)
    if abs(checked.total_time - result.total_time) > 1e-7 * max(1, result.total_time):
        raise RuntimeError("Reconstructed strategy cost does not match DP optimum")
    return result


def evaluate_strategy(
    model: LapTimeModel, config: RaceConfig, compounds: list[str], lengths: list[int]
) -> PitStrategy:
    """Validate and price a specified schedule in the SAME model as the optimizer."""
    available = _compounds(model, config)
    if not compounds or len(compounds) != len(lengths):
        raise ValueError("Each stint needs one compound and one positive length")
    for length in lengths:
        positive_int(length, "stint length")
    if sum(lengths) != config.total_laps:
        raise ValueError("Stint lengths must sum to total_laps")
    if len(set(compounds)) < config.rules.min_compounds or len(lengths) < config.rules.min_stints:
        raise InfeasibleStrategyError("Schedule fails minimum compound/stint requirements")
    if config.starting_compound and compounds[0] != config.starting_compound:
        raise ValueError("Schedule disagrees with starting_compound")
    total, completed, pit_laps = 0.0, 0, []
    for i, (compound, length) in enumerate(zip(compounds, lengths)):
        if compound not in available or length > config.age_limit(compound):
            raise ValueError("Unavailable compound or excessive stint length")
        for age in range(1, length + 1):
            value = model.predict(compound, age, config.track_temp)
            finite_number(value, "predicted lap time", 0)
            if value == 0:
                raise ValueError("Predicted lap time must be positive")
            total += value
        completed += length
        if i < len(lengths) - 1:
            pit_laps.append(completed)
            total += config.loss_at(completed)
    return PitStrategy(total, pit_laps, list(compounds), list(lengths))
