import itertools
import math
import random

import pytest

from f1_strategy_optimizer import (
    InfeasibleStrategyError,
    ModelParameters,
    RaceConfig,
    RuleSet,
    TyreCurve,
    TyreModel,
    evaluate_strategy,
    solve,
)


def model(**times):
    return TyreModel(
        {c: TyreCurve(t, 0) for c, t in times.items()}, ModelParameters(min_degradation={})
    )


def test_terminal_pit_cannot_satisfy_two_compounds():
    result = solve(model(SOFT=1, MEDIUM=100), RaceConfig(total_laps=3))
    assert result.total_time == 126
    assert result.stint_lengths == [2, 1] or result.stint_lengths == [1, 2]
    assert set(result.compounds_used) == {"SOFT", "MEDIUM"}
    assert all(lap < 3 for lap in result.pit_laps)


def test_finish_at_age_limit_without_pit():
    result = solve(
        model(SOFT=1), RaceConfig(total_laps=3, max_tyre_age=3, rules=RuleSet(min_compounds=1))
    )
    assert result.total_time == 3
    assert result.pit_laps == []
    assert result.stint_lengths == [3]


def test_same_compound_reset_and_minimum_stints():
    result = solve(
        model(SOFT=1),
        RaceConfig(total_laps=3, max_tyre_age=1, rules=RuleSet(min_compounds=1, min_stints=3)),
    )
    assert result.stint_lengths == [1, 1, 1]
    assert result.compounds_used == ["SOFT"] * 3
    assert result.pit_laps == [1, 2]
    assert result.total_time == 51


def test_known_pit_loss_override():
    result = solve(model(SOFT=1, HARD=1), RaceConfig(total_laps=5, pit_loss_overrides={3: 0}))
    assert result.pit_laps == [3]
    assert result.total_time == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_laps": 0},
        {"total_laps": -1},
        {"total_laps": 1.5},
        {"total_laps": True},
        {"pit_loss": -1},
        {"pit_loss": math.nan},
        {"pit_loss": math.inf},
        {"track_temp": math.nan},
        {"max_tyre_age": 0},
        {"pit_loss_overrides": {57: 1}},
        {"compound_age_limits": {"SOFT": 0}},
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        RaceConfig(**kwargs)


def test_infeasible_and_unknown_compound():
    with pytest.raises(InfeasibleStrategyError):
        solve(model(SOFT=1), RaceConfig())
    with pytest.raises(InfeasibleStrategyError):
        solve(model(SOFT=1, HARD=2), RaceConfig(total_laps=1))
    with pytest.raises(ValueError, match="starting_compound"):
        solve(model(SOFT=1, HARD=2), RaceConfig(starting_compound="MEDIUM"))


def test_one_lap_single_compound():
    result = solve(
        model(SOFT=1), RaceConfig(total_laps=1, max_tyre_age=1, rules=RuleSet(min_compounds=1))
    )
    assert result.stint_lengths == [1] and result.total_time == 1


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -1, 0])
def test_invalid_external_model_cost(cost):
    class BadModel:
        compounds = ("SOFT", "HARD")

        def predict(self, *args):
            return cost

    with pytest.raises(ValueError):
        solve(BadModel(), RaceConfig(total_laps=3))


def brute_force(m, config):
    """Independent oracle: enumerate all partitions and all stint assignments."""
    optimum = math.inf
    n = config.total_laps
    for separators in itertools.product((False, True), repeat=n - 1):
        endpoints = [i + 1 for i, stop in enumerate(separators) if stop] + [n]
        lengths = [b - a for a, b in zip([0] + endpoints, endpoints)]
        if len(lengths) < config.rules.min_stints:
            continue
        for compounds in itertools.product(m.compounds, repeat=len(lengths)):
            if len(set(compounds)) < config.rules.min_compounds:
                continue
            if config.starting_compound and compounds[0] != config.starting_compound:
                continue
            if any(length > config.age_limit(c) for c, length in zip(compounds, lengths)):
                continue
            total = sum(
                m.predict(c, age, config.track_temp)
                for c, length in zip(compounds, lengths)
                for age in range(1, length + 1)
            )
            total += sum(config.loss_at(lap) for lap in endpoints[:-1])
            optimum = min(optimum, total)
    return optimum


@pytest.mark.parametrize("seed", range(20))
def test_random_small_races_match_exhaustive_oracle(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 6)
    m = TyreModel(
        {
            c: TyreCurve(rng.uniform(1, 10), rng.uniform(0, 1), rng.uniform(0, 0.2))
            for c in ("SOFT", "HARD")
        },
        ModelParameters(min_degradation={}),
    )
    config = RaceConfig(
        total_laps=n,
        pit_loss=rng.uniform(0, 8),
        max_tyre_age=rng.randint(1, n),
        rules=RuleSet(min_compounds=rng.randint(1, 2), min_stints=rng.randint(1, n)),
        pit_loss_overrides={1: rng.uniform(0, 4)},
        starting_compound=rng.choice([None, "SOFT", "HARD"]),
    )
    result = solve(m, config)
    assert result.total_time == pytest.approx(brute_force(m, config))
    assert sum(result.stint_lengths) == n and min(result.stint_lengths) >= 1
    replay = evaluate_strategy(m, config, result.compounds_used, result.stint_lengths)
    assert replay.total_time == pytest.approx(result.total_time)
    assert replay.pit_laps == result.pit_laps


def test_compound_age_limit_and_unknown_limit():
    config = RaceConfig(total_laps=5, compound_age_limits={"SOFT": 1})
    result = solve(model(SOFT=1, HARD=2), config)
    assert all(n <= 1 for c, n in zip(result.compounds_used, result.stint_lengths) if c == "SOFT")
    with pytest.raises(ValueError, match="absent"):
        solve(model(SOFT=1, HARD=2), RaceConfig(compound_age_limits={"MEDIUM": 1}))
