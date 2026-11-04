"""Deterministic pairwise UI parameter checks, not empirical prediction validation.

Only the bundled, already-observed Bahrain development case is opened. Modified
plans are explicit test fixtures, never a silent adjustment to a user's strategy.
"""

from copy import deepcopy
from itertools import combinations, product

import pytest

from f1_strategy_optimizer.event_replay import digest
from f1_strategy_optimizer.strategy_exploration import propose_exploration
from f1_strategy_optimizer.workbench import Workbench

DOMAINS = {
    "risk": ("conservative", "mean_position"),
    "track": ("GREEN", "VSC", "SC"),
    "weather": ("DRY", "WET"),
    "pit_loss": (0.0, 18.5, 40.0),
    "future_laps": (1, 6, 30),
    "target_rank": (1, 5),
    "compound": ("SOFT", "MEDIUM", "HARD"),
    "opponent": ("stay", "fixed", "cover_undercut", "overcut"),
    "inventory": ("unknown_unlimited_model", "finite"),
    "max_stops": (0, 1, 2),
}


def pairs(row):
    return {(i, row[i], j, row[j]) for i, j in combinations(range(len(row)), 2)}


def covering_rows():
    """Greedy deterministic strength-2 covering array with audited coverage."""
    rows = list(product(*DOMAINS.values()))
    uncovered = set().union(*(pairs(row) for row in rows))
    selected = []
    while uncovered:
        row = max(rows, key=lambda candidate: len(pairs(candidate) & uncovered))
        selected.append(row)
        uncovered.difference_update(pairs(row))
        rows.remove(row)
    return selected


PAIRWISE_ROWS = covering_rows()


@pytest.fixture(scope="module")
def baseline():
    app = Workbench()
    assert set(app.races) == {"bahrain-2023"}
    assert all(race["partition"] == "development" for race in app.races.values())
    original = app._data

    def prefix_only(name):
        assert "reveal" not in name and "evidence" not in name
        return original(name)

    app._data = prefix_only
    case = next(iter(app.cases))
    assumptions = app.assumptions(case, "leclerc")
    assert len(assumptions["planning"]["state"]["cars"]) == 5
    return app.cases[case][1], assumptions


def configured(baseline, values):
    frozen, base = baseline
    a = deepcopy(base)
    p = a["planning"]
    start = p["state"]["completed_laps"]
    end = start + values["future_laps"]
    p["state"].update(total_laps=end, track_status=values["track"], weather=values["weather"])
    p["physics"]["pit_loss"] = values["pit_loss"]
    # Explicit arbitrary wet penalties, not calibrated or fetched from outcomes.
    p["physics"]["wet_penalties"] = dict.fromkeys(p["tyres"], 5.0)
    p["risk_top_k"] = values["target_rank"]
    a["selection_preference"] = {"mode": values["risk"]}
    a["inventory_policy"]["kind"] = values["inventory"]
    for car in p["state"]["cars"]:
        car["tyre_inventory"] = (
            dict.fromkeys(p["tyres"], 2) if values["inventory"] == "finite" else None
        )
    p["candidates"].update(
        pit_laps=sorted({start, min(start + 2, end - 1)}),
        compounds=[values["compound"]],
        max_stops=values["max_stops"],
    )
    # Each fixture explicitly declares a consistent event horizon; no real future data.
    p["scenarios"] = [
        {
            "name": "explicit-matrix-hypothesis",
            "weight": 1,
            "available_at_lap": start,
            "kind": "hypothetical",
            "events": [],
        }
    ]
    a["sensitivity"] = []
    rival = next(iter(p["opponents"]))
    policy = values["opponent"]
    if policy == "fixed":
        p["opponents"][rival] = {
            "kind": "fixed",
            "stops": [{"after_lap": start, "compound": values["compound"]}],
        }
    elif policy != "stay":
        p["opponents"][rival] = {
            "kind": "reactive",
            "mode": policy,
            "rival": p["ego"],
            "compound": values["compound"],
            "planned_lap": start,
            "window_start": start,
            "window_end": end - 1,
            "response_gap": 12,
            "overcut_laps": 1,
        }
    return frozen, a


def test_pairwise_array_covers_every_declared_pair():
    required = {
        (i, a, j, b)
        for i, j in combinations(range(len(DOMAINS)), 2)
        for a in tuple(DOMAINS.values())[i]
        for b in tuple(DOMAINS.values())[j]
    }
    observed = set().union(*(pairs(row) for row in PAIRWISE_ROWS))
    assert observed == required


@pytest.mark.parametrize("row", PAIRWISE_ROWS, ids=lambda row: "-".join(map(str, row)))
def test_pairwise_explicit_scenarios_preserve_inputs_and_scope(baseline, row):
    frozen, assumptions = configured(baseline, dict(zip(DOMAINS, row)))
    original = deepcopy((frozen, assumptions))
    result = propose_exploration(frozen, assumptions)
    assert (frozen, assumptions) == original
    assert result["assumptions_sha256"] == digest(assumptions)
    assert result["model_horizon"]["modeled_laps"] == dict(zip(DOMAINS, row))["future_laps"]
    assert result["model_scope"]["modeled_driver_count"] == 5
    assert result["budget"]["rollouts_executed"] <= assumptions["max_total_rollouts"]
    for candidate in result["top3"]:
        assert 1 <= candidate["expected_finish_position"] <= 5
        assert 1 <= candidate["worst_finish_position"] <= 5
    assert "actual" not in result


DEFAULT = {key: values[0] for key, values in DOMAINS.items()}
BOUNDARIES = [
    ("pit_loss", -1),
    ("pit_loss", None),
    ("pit_loss", float("nan")),
    ("pit_loss", float("inf")),
    ("future_laps", 0),
    ("future_laps", 31),
    ("future_laps", 1.5),
    ("target_rank", 0),
    ("target_rank", 6),
    ("target_rank", 1.5),
    ("track", "UNKNOWN"),
    ("weather", "UNKNOWN"),
    ("compound", "NOT_A_TYRE"),
]


@pytest.mark.parametrize("field,value", BOUNDARIES)
def test_invalid_parameter_boundaries_are_rejected(baseline, field, value):
    values = DEFAULT | {"max_stops": 1, field: value}
    with pytest.raises((ValueError, TypeError)):
        frozen, assumptions = configured(baseline, values)
        propose_exploration(frozen, assumptions)


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_lap_time", 0),
        ("base_lap_time", None),
        ("base_lap_time", float("inf")),
        ("gap_seconds", -1),
        ("gap_seconds", None),
        ("tyre_age", -1),
        ("tyre_age", 0.5),
        ("tyre_age", None),
    ],
)
def test_invalid_car_numeric_boundaries_are_rejected(baseline, field, value):
    frozen, assumptions = configured(baseline, DEFAULT)
    assumptions["planning"]["state"]["cars"][0][field] = value
    with pytest.raises((ValueError, TypeError)):
        propose_exploration(frozen, assumptions)


PHYSICS_NUMBERS = (
    "reference_lap_time",
    "pit_loss",
    "following_gap",
    "passing_advantage",
    "passing_cost",
    "sc_pace_factor",
    "vsc_pace_factor",
    "sc_pit_factor",
    "vsc_pit_factor",
    "sc_gap",
    "sc_catchup_per_lap",
    "pit_service_time",
)


@pytest.mark.parametrize("field", PHYSICS_NUMBERS)
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_every_physics_scalar_rejects_negative_and_nonfinite(field, value):
    from f1_strategy_optimizer.competition import Physics

    with pytest.raises(ValueError):
        Physics(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_stops", -1),
        ("max_stops", 3),
        ("max_candidates", 0),
        ("max_candidates", 1),
        ("max_rollouts", 0),
        ("max_rollouts", 1),
    ],
)
def test_candidate_budget_boundaries_are_rejected(baseline, field, value):
    frozen, assumptions = configured(baseline, DEFAULT | {"max_stops": 1})
    assumptions["planning"]["candidates"][field] = value
    with pytest.raises(ValueError):
        propose_exploration(frozen, assumptions)


@pytest.mark.parametrize("value", [0, 1, 10_001])
def test_total_rollout_budget_boundaries_are_rejected(baseline, value):
    frozen, assumptions = configured(baseline, DEFAULT | {"max_stops": 1})
    assumptions["max_total_rollouts"] = value
    with pytest.raises(ValueError):
        propose_exploration(frozen, assumptions)


def test_wet_scenario_requires_explicit_penalties(baseline):
    frozen, assumptions = configured(baseline, DEFAULT | {"weather": "WET"})
    assumptions["planning"]["physics"]["wet_penalties"] = {}
    with pytest.raises(ValueError, match="explicit penalties"):
        propose_exploration(frozen, assumptions)
