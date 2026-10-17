"""Exploration requires explicit assumptions and never receives future outcomes."""

import json
from copy import deepcopy

import pytest

from f1_strategy_optimizer import strategy_exploration as exploration
from f1_strategy_optimizer.event_replay import digest


@pytest.fixture
def inputs():
    names = ["ego", "mate", "rival", "other"]
    cutoff = "2023-03-05T15:18:00+00:00"
    state = {
        "cutoff": cutoff,
        "session": {"year": 2023},
        "cars": [
            {
                "id": driver,
                "team": "A" if i < 2 else "B",
                "completed_laps": {"value": 7 if i % 2 else 8, "status": "inferred"},
                "gap_seconds": {"value": i * 0.5, "status": "stale"},
                "compound": {"value": "SOFT", "status": "inferred"},
                "estimated_completed_tyre_age": {"value": 8, "status": "inferred"},
                "tyre_inventory": {"value": None, "status": "unknown"},
            }
            for i, driver in enumerate(names)
        ],
        "track_status": {"value": None, "status": "unknown"},
        "surface_condition": {"value": None, "status": "unknown"},
        "weather_observation": {"value": {"track_temperature": 31}},
    }
    frozen = {
        "schema_version": 1,
        "cutoff": cutoff,
        "state": state,
        "strategy": {"recommendation": None},
    }
    frozen["decision_sha256"] = digest(frozen)
    assumptions = {
        "schema_version": 1,
        "acknowledgement": {key: True for key in exploration.ACKNOWLEDGEMENTS},
        "action_boundary": {
            "kind": "abstract_next_pit_entry_boundary",
            "effective_at": None,
            "after_lap": 8,
            "rationale": "Synthetic same-lap boundary; UTC unknown",
        },
        "field_assumptions": {
            key: {
                "source": "Hand-entered synthetic study",
                "rationale": f"Explicit illustrative {key}; not an observation",
            }
            for key in exploration.ASSUMPTION_GROUPS
        },
        "inventory_policy": {"kind": "unknown_unlimited_model", "acknowledged": True},
        "planning": {
            "source": "Synthetic exploration with no historical action or outcome data",
            "ego": "ego",
            "state": {
                "season": 2023,
                "event": "SYNTHETIC-EXPLORATION",
                "completed_laps": 8,
                "total_laps": 14,
                "track_status": "GREEN",
                "weather": "DRY",
                "track_temp": 35,
                "cars": [
                    {
                        "driver": driver,
                        "team": "A" if i < 2 else "B",
                        "base_lap_time": 90.0 if i == 0 else 100.0,
                        "compound": "SOFT" if i == 0 else "HARD",
                        "tyre_age": 20 if i == 0 else 0,
                        "gap_seconds": i * 0.5,
                        "tyre_inventory": None,
                        "used_compounds": ["SOFT"],
                        "pit_stops": 0,
                    }
                    for i, driver in enumerate(names)
                ],
            },
            "physics": {"reference_lap_time": 100, "pit_loss": 0},
            "tyres": {
                "SOFT": {"base_time": 100, "degradation": 8},
                "HARD": {"base_time": 100, "degradation": 0},
            },
            "opponents": {driver: {"kind": "fixed", "stops": []} for driver in names[1:]},
            "scenarios": [
                {"name": "synthetic-green", "weight": 1, "available_at_lap": 8, "events": []}
            ],
            "candidates": {
                "pit_laps": [8, 9, 10],
                "compounds": ["HARD"],
                "max_stops": 1,
                "max_candidates": 10,
                "max_rollouts": 10,
            },
            "rules": {},
            "objective": {"mode": "driver_position"},
        },
        "sensitivity": [
            {
                "name": "large-pit-cost",
                "path": "physics.pit_loss",
                "value": 1000,
                "rationale": "Synthetic extreme perturbation to reveal ranking reversal",
            }
        ],
        "max_total_rollouts": 20,
    }
    return frozen, assumptions


def test_explicit_exploration_preserves_inputs_and_marks_all_assumptions(inputs):
    frozen, assumptions = inputs
    original = deepcopy(inputs)
    result = exploration.propose_exploration(frozen, assumptions)
    assert inputs == original
    assert result["claim"].startswith("Exploratory simulation")
    assert result["model_scope"]["modeled_driver_count"] == 4
    assert result["model_horizon"] == {"after_lap": 8, "through_lap": 14, "modeled_laps": 6}
    assert "MODEL HORIZON-END" in result["position_semantics"]
    assert {
        "strategy_exploration.py",
        "competition.py",
        "race_planner.py",
        "config.py",
        "race_constraints.py",
    } <= set(result["engine_source_sha256"])
    assert "NOT INVENTORY FEASIBILITY" in result["inventory_feasibility"]
    assert result["action_boundary"]["effective_at"] is None
    assert result["stay_out"]["status"] == "feasible"
    assert len(result["top3"]) == 3
    overrides = {row["path"]: row for row in result["field_overrides"]}
    assert overrides["state.cars.0.tyre_age"]["original"]["value"] == 8
    assert overrides["state.cars.0.tyre_age"]["assumed_value"] == 20
    assert overrides["physics.passing_cost"]["origin"] == "model_default"
    assert overrides["state.track_status"]["original"]["status"] == "unknown"
    assert overrides["state.track_status"]["assumed_value"] == "GREEN"
    assert result["budget"]["preflight_rollout_upper_bound"] == 8
    for entry in result["input_freezes"]:
        assert digest(entry["resolved_input"]) == entry["sha256"]


def test_sensitivity_can_reveal_reversal_without_changing_baseline(inputs):
    frozen, assumptions = inputs
    result = exploration.propose_exploration(frozen, assumptions)
    without = deepcopy(assumptions)
    without["sensitivity"] = []
    base_only = exploration.propose_exploration(frozen, without)
    assert result["top3"] == base_only["top3"]
    assert result["input_freezes"][0] == base_only["input_freezes"][0]
    case = result["sensitivity"]["cases"][0]
    assert case["winner_changed"]
    assert case["winner"] == "stay-out"
    assert "does not establish robustness" in result["sensitivity"]["notice"]


def test_stay_out_retained_even_when_outside_top_three(inputs):
    frozen, assumptions = inputs
    # Deliberately extreme synthetic pace makes every tested stop beat old tyres.
    assumptions["planning"]["tyres"]["SOFT"]["degradation"] = 100
    assumptions["planning"]["state"]["cars"][0]["gap_seconds"] = 0
    for i, car in enumerate(assumptions["planning"]["state"]["cars"][1:], 1):
        car["gap_seconds"] = i * 10_000
    assumptions["sensitivity"] = []
    result = exploration.propose_exploration(frozen, assumptions)
    assert all(row["label"] != "stay-out" for row in result["top3"])
    assert result["stay_out"]["candidate"]["label"] == "stay-out"


def test_teammate_deltas_are_scenario_matched_and_proxy_is_simulated(inputs):
    result = exploration.propose_exploration(*inputs)
    winner = result["top3"][0]
    detail = winner["simulation_details"][0]
    proxy = detail["first_post_stop_lap_proxy"]
    assert proxy["kind"] == "simulated_first_post_stop_lap_proxy_not_exact_pit_exit"
    reference = result["stay_out"]["candidate"]["outcomes"][0]
    expected = (
        winner["outcomes"][0]["driver_elapsed_seconds"]["mate"]
        - reference["driver_elapsed_seconds"]["mate"]
    )
    assert (
        detail["simulated_teammate_costs"]["mate"][
            "elapsed_delta_vs_same_scenario_stay_out_seconds"
        ]
        == expected
    )


def test_infeasible_stay_out_retains_rejection_and_null_teammate_reference(inputs):
    frozen, assumptions = inputs
    assumptions["planning"]["rules"] = {
        "season": 2023,
        "event": "SYNTHETIC-EXPLORATION",
        "min_stops": 1,
    }
    for policy in assumptions["planning"]["opponents"].values():
        policy["stops"] = [{"after_lap": 9, "compound": "HARD"}]
    assumptions["sensitivity"] = []
    result = exploration.propose_exploration(frozen, assumptions)
    assert result["stay_out"]["status"] == "infeasible"
    assert result["stay_out"]["rejection"]["first_failure"]["reason"]
    assert result["top3"][0]["simulation_details"][0]["simulated_teammate_costs"]["mate"] is None


def test_finite_stocks_reject_unavailable_spares(inputs):
    frozen, assumptions = inputs
    assumptions["inventory_policy"] = {"kind": "finite", "acknowledged": True}
    for car in assumptions["planning"]["state"]["cars"]:
        car["tyre_inventory"] = {"HARD": 0}
    assumptions["sensitivity"] = []
    result = exploration.propose_exploration(frozen, assumptions)
    assert len(result["top3"]) == 1
    assert result["top3"][0]["label"] == "stay-out"
    assert len(result["rejected_candidates"]) == 3


def test_reduced_field_requires_explicit_subset_and_rank_warning(inputs):
    frozen, assumptions = inputs
    assumptions["planning"]["state"]["cars"].pop()
    assumptions["planning"]["opponents"].pop("other")
    with pytest.raises(ValueError, match="model_subset"):
        exploration.propose_exploration(frozen, assumptions)
    assumptions["model_subset"] = {
        "drivers": ["ego", "mate", "rival"],
        "acknowledged": True,
        "rationale": "Three-car model excludes one synthetic driver",
    }
    result = exploration.propose_exploration(frozen, assumptions)
    assert result["model_scope"]["excluded_drivers"] == ["other"]
    assert "WITHIN MODEL SUBSET ONLY" in result["model_scope"]["rank_semantics"]


@pytest.mark.parametrize(
    "failure",
    [
        "gap",
        "pace",
        "weather",
        "inventory",
        "ack",
        "boundary",
        "past_time",
        "scenario_future",
        "outcome",
        "rolling",
    ],
)
def test_missing_or_inconsistent_assumptions_rejected_before_planning(inputs, monkeypatch, failure):
    frozen, assumptions = inputs
    if failure in {"gap", "pace", "inventory"}:
        key = {"gap": "gap_seconds", "pace": "base_lap_time", "inventory": "tyre_inventory"}[
            failure
        ]
        assumptions["planning"]["state"]["cars"][0].pop(key)
    elif failure == "weather":
        assumptions["planning"]["state"].pop("weather")
    elif failure == "ack":
        assumptions["acknowledgement"]["asynchronous_gap_projection"] = False
    elif failure == "boundary":
        assumptions["action_boundary"]["after_lap"] = 9
    elif failure == "past_time":
        assumptions["action_boundary"]["effective_at"] = "2023-03-05T15:17:59Z"
    elif failure == "scenario_future":
        assumptions["planning"]["scenarios"][0]["available_at_lap"] = 9
    elif failure == "outcome":
        assumptions["outcome"] = {"winner": "ego"}
    else:
        assumptions["planning"]["rolling"] = {}
    monkeypatch.setattr(exploration, "plan_from_document", lambda _: pytest.fail("planner called"))
    with pytest.raises(ValueError):
        exploration.propose_exploration(frozen, assumptions)


def test_tampered_freeze_and_cumulative_budget_fail_before_rollouts(inputs, monkeypatch):
    frozen, assumptions = inputs
    monkeypatch.setattr(exploration, "plan_from_document", lambda _: pytest.fail("planner called"))
    altered = deepcopy(frozen)
    altered["state"]["cars"][0]["team"] = "tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        exploration.propose_exploration(altered, assumptions)
    assumptions["max_total_rollouts"] = 7
    with pytest.raises(ValueError, match="cumulative"):
        exploration.propose_exploration(frozen, assumptions)


def test_all_variant_inputs_are_frozen_before_first_planner_call(inputs, monkeypatch):
    real_digest, real_plan = exploration.digest, exploration.plan_from_document
    events = []

    def record_digest(value):
        if "planning" in value and "assumption_context" in value:
            events.append("freeze")
        return real_digest(value)

    def record_plan(document):
        events.append("plan")
        return real_plan(document)

    monkeypatch.setattr(exploration, "digest", record_digest)
    monkeypatch.setattr(exploration, "plan_from_document", record_plan)
    exploration.propose_exploration(*inputs)
    assert events == ["freeze", "freeze", "plan", "plan"]


@pytest.mark.parametrize(
    "path", ["state.cars.0.gap_seconds", "scenarios.0.weight", "physics.missing"]
)
def test_sensitivity_is_one_existing_numeric_model_parameter(inputs, path):
    frozen, assumptions = inputs
    assumptions["sensitivity"][0]["path"] = path
    with pytest.raises(ValueError, match="Sensitivity"):
        exploration.propose_exploration(frozen, assumptions)


def test_cli_selects_one_cutoff_and_refuses_overwrite(inputs, tmp_path):
    frozen, assumptions = inputs
    other = deepcopy(frozen)
    other["cutoff"] = other["state"]["cutoff"] = "2023-03-05T15:19:00Z"
    other.pop("decision_sha256")
    other["decision_sha256"] = digest(other)
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([frozen, other]))
    assumption_file = tmp_path / "assumptions.json"
    assumption_file.write_text(json.dumps(assumptions))
    output = tmp_path / "result"
    args = [
        "--decision-file",
        str(decisions),
        "--cutoff",
        frozen["cutoff"],
        "--assumptions",
        str(assumption_file),
        "--output-dir",
        str(output),
    ]
    assert exploration.main(args) == 0
    report = json.loads((output / "exploration.json").read_text())
    assert report["decision_sha256"] == frozen["decision_sha256"]
    assert (output / "resolved-inputs.json").is_file()
    assert (output / "exploration.md").is_file()
    with pytest.raises(SystemExit) as exc:
        exploration.main(args)
    assert exc.value.code == 2
    with pytest.raises(ValueError, match="--cutoff"):
        exploration._select([frozen, other], None)
