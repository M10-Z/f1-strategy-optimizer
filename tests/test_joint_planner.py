import json
from pathlib import Path

import pandas as pd
import pytest

from f1_strategy_optimizer.competition import (
    CarState,
    FixedPolicy,
    Physics,
    PitAction,
    PitPlan,
    PitRecord,
    PlanningObjective,
    RaceState,
    Scenario,
    candidate_actions,
)
from f1_strategy_optimizer.joint_planner import plan_joint_positions
from f1_strategy_optimizer.models import validate_laps
from f1_strategy_optimizer.race_constraints import CompetitionRules
from f1_strategy_optimizer.race_planner import (
    ExplicitTyrePace,
    ScenarioTyreModel,
    main,
    plan_from_document,
)


def model():
    return ScenarioTyreModel(
        {
            "SOFT": ExplicitTyrePace(100, 0.5),
            "HARD": ExplicitTyrePace(101, 0.1),
        }
    )


def document():
    source = Path(__file__).resolve().parents[1] / "examples" / "competition-joint.json"
    return json.loads(source.read_text())


def test_default_joint_objective_protects_ego_and_cooperation_discloses_cost():
    supplied = document()
    cooperative = plan_from_document(supplied)
    supplied.pop("objective")
    individual = plan_from_document(supplied)
    own = individual["recommended_per_driver"]
    team = cooperative["recommended_per_driver"]
    assert individual["objective_config"]["mode"] == "driver_position"
    assert own["E"]["expected_finish_position"] == 2
    assert own["M"]["expected_finish_position"] == 4
    assert own["E"]["rank_cost_vs_individual_best_evaluated"] == 0
    assert team["E"]["expected_finish_position"] == 3
    assert team["M"]["expected_finish_position"] == 1
    assert team["E"]["rank_cost_vs_individual_best_evaluated"] == 1
    assert cooperative["ranking"][0]["expected_objective"] == 4
    assert cooperative["recommended_joint_stops"] != individual["recommended_joint_stops"]
    assert cooperative["search"]["full_pair_count"] == 36
    assert cooperative["search"]["omitted_pair_count"] == 0
    # Both schedules really execute in the same simulator; S reacts after seeing E's stop.
    trace = cooperative["ranking"][0]["outcomes"][0]["trace"]
    assert trace[0]["pit_actions"] == {"E": "HARD", "M": "HARD"}
    assert "S" not in trace[0]["pit_actions"]
    assert trace[1]["pit_actions"]["S"] == "HARD"


def test_joint_search_avoids_double_stack_when_it_harms_teammate_rank():
    initial = RaceState(
        0,
        4,
        (
            CarState("E", 97, "SOFT", 8, team="T"),
            CarState("M", 99, "SOFT", 8, 0.2, team="T"),
            CarState("R", 100, "HARD", 1, 1.2),
        ),
    )
    actions = candidate_actions(initial, ("HARD",), (0, 1, 2, 3))
    report = plan_joint_positions(
        model(),
        initial,
        Physics(pit_loss=3, pit_service_time=3),
        "E",
        "M",
        {"R": FixedPolicy()},
        {"E": actions, "M": actions},
        (Scenario("dry", 1, 0),),
        objective=PlanningObjective("team_rank_sum", "T"),
    )
    best = report["ranking"][0]
    assert best["joint_stops"]["E"][0]["after_lap"] == 1
    assert best["joint_stops"]["M"][0]["after_lap"] == 0
    double = next(r for r in report["ranking"] if r["pair_indices"] == [1, 1])
    assert best["expected_objective"] == 3 < double["expected_objective"]
    assert double["per_driver"]["M"]["expected_queue_seconds"] == pytest.approx(2.8)
    assert all(m["expected_queue_seconds"] == 0 for m in best["per_driver"].values())


def test_joint_plan_covers_observed_rival_stop_with_one_car_and_extends_other():
    initial = RaceState(
        1,
        6,
        (
            CarState("E", 100, "SOFT", 12, team="T"),
            CarState("M", 99, "SOFT", 4, 0.5, team="T"),
            CarState("R", 99, "HARD", 1, 8, pit_stops=1),
        ),
    )
    actions = candidate_actions(initial, ("HARD",), (1, 2, 3, 4, 5))
    report = plan_joint_positions(
        model(),
        initial,
        Physics(pit_loss=8, pit_service_time=3),
        "E",
        "M",
        {"R": FixedPolicy()},
        {"E": actions, "M": actions},
        (Scenario("dry", 1, 1),),
        observed_pits=(PitRecord("R", 0, "HARD"),),
        objective=PlanningObjective("team_rank_sum", "T"),
    )
    assert report["recommended_joint_stops"]["E"][0]["after_lap"] == 1
    assert report["recommended_joint_stops"]["M"][0]["after_lap"] == 5
    outcome = report["ranking"][0]["outcomes"][0]
    assert outcome["pit_history"][0] == {"driver": "R", "after_lap": 0, "compound": "HARD"}
    assert outcome["trace"][0]["pit_actions"] == {"E": "HARD"}


def test_inventory_is_independent_and_no_infeasible_pair_is_reweighted():
    initial = RaceState(
        0,
        2,
        (
            CarState("E", 100, "SOFT", 2, team="T", tyre_inventory={"HARD": 1}),
            CarState("M", 100, "SOFT", 2, 1, team="T", tyre_inventory={}),
        ),
    )
    plans = (PitAction(), PitAction(0, "HARD"))
    report = plan_joint_positions(
        model(),
        initial,
        Physics(),
        "E",
        "M",
        {},
        {"E": plans, "M": plans},
        (Scenario("dry", 1, 0), Scenario("second", 3, 0)),
    )
    assert len(report["ranking"]) == 2
    assert len(report["rejected_candidates"]) == 2
    assert all("M: no spare" in r["first_failure"]["reason"] for r in report["rejected_candidates"])
    assert all(len(r["outcomes"]) == 2 for r in report["ranking"])
    assert dict(initial.car("E").tyre_inventory) == {"HARD": 1}


def test_budget_reports_exact_omitted_prefix_ranges_and_bounds_rollouts():
    supplied = document()
    supplied["joint"]["max_joint_candidates"] = 10
    supplied["candidates"]["max_rollouts"] = 8
    supplied["scenarios"].append({"name": "second", "weight": 1, "available_at_lap": 0})
    report = plan_from_document(supplied)
    search = report["search"]
    assert search["candidate_count"] == 4
    assert search["full_pair_count"] == 36
    assert search["omitted_pair_count"] == 32
    assert search["rollouts_executed"] <= 8
    omitted = {
        (row["ego_index"], j)
        for row in search["omitted_half_open_ranges"]
        for j in range(*row["teammate_index_range"])
    }
    evaluated = {
        tuple(row["pair_indices"]) for row in report["ranking"] + report["rejected_candidates"]
    }
    assert not omitted & evaluated
    assert omitted | evaluated == {(i, j) for i in range(6) for j in range(6)}
    assert report["recommended_per_driver"]["E"]["rank_cost_vs_individual_best_evaluated"] >= 0


@pytest.mark.parametrize("bad", ["other_team", "duplicate_policy", "rolling", "budget"])
def test_joint_configuration_rejects_ambiguous_or_unsupported_control(bad):
    supplied = document()
    if bad == "other_team":
        supplied["state"]["cars"][1]["team"] = "Other"
    elif bad == "duplicate_policy":
        supplied["opponents"]["M"] = {"kind": "fixed", "stops": []}
    elif bad == "rolling":
        supplied["rolling"] = {}
    else:
        supplied["candidates"]["max_rollouts"] = 0
    with pytest.raises(ValueError):
        plan_from_document(supplied)


def test_joint_cli_exports_both_plans_and_individual_tradeoffs(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "competition-joint.json"
    output = tmp_path / "joint"
    assert main(["--scenario", str(source), "--output-dir", str(output)]) == 0
    report = json.loads((output / "race-plan.json").read_text())
    assert report["schema_version"] == 3
    assert set(report["recommended_joint_stops"]) == {"E", "M"}
    assert "per-driver costs" in (output / "race-plan.md").read_text()
    assert json.loads((output / "manifest.json").read_text())["input"] == document()


def test_both_cars_execute_two_stops_with_separate_stock_and_rules():
    initial = RaceState(
        0,
        3,
        tuple(
            CarState(d, 100, "SOFT", 1, i, team="T", tyre_inventory={"HARD": 2})
            for i, d in enumerate(("E", "M"))
        ),
        season=2026,
        event="SYNTHETIC",
    )
    actions = (PitPlan(), PitPlan((PitAction(0, "HARD"), PitAction(2, "HARD"))))
    args = (
        model(),
        initial,
        Physics(),
        "E",
        "M",
        {},
        {"E": actions, "M": actions},
        (Scenario("dry", 1, 0),),
    )
    report = plan_joint_positions(
        *args,
        rules=CompetitionRules(season=2026, event="SYNTHETIC", min_stops=2),
    )
    assert len(report["ranking"]) == 1
    assert report["comparison_reference"]["feasible"] is False
    for metrics in report["recommended_per_driver"].values():
        assert metrics["rank_delta_vs_reference"] is None
    resources = report["ranking"][0]["outcomes"][0]["final_resources"]
    assert resources["E"]["inventory"] == resources["M"]["inventory"] == {"HARD": 0}
    impossible = plan_joint_positions(
        *args,
        rules=CompetitionRules(season=2026, event="SYNTHETIC", min_stops=3),
    )
    assert impossible["status"] == "no_feasible_candidate"
    assert impossible["recommended_joint_stops"] is None
    assert impossible["recommended_per_driver"] is None


def test_joint_search_rejects_future_assumptions_and_future_observed_pits():
    supplied = document()
    supplied["scenarios"][0]["available_at_lap"] = 1
    with pytest.raises(ValueError, match="not available"):
        plan_from_document(supplied)
    supplied = document()
    supplied["observed_pits"] = [{"driver": "R", "after_lap": 0, "compound": "HARD"}]
    with pytest.raises(ValueError, match="precede the decision"):
        plan_from_document(supplied)


def test_normalized_import_rejects_blank_event_and_whitespace_duplicate_driver():
    row = dict(
        Compound="HARD",
        TyreLife=2,
        LapTimeSeconds=100,
        LapNumber=2,
        Year=2024,
        Driver="E",
        Stint=1,
        Event="Bahrain",
    )
    with pytest.raises(ValueError, match="nonempty event"):
        validate_laps(pd.DataFrame([{**row, "Event": "  "}]))
    with pytest.raises(ValueError, match="Duplicate driver laps"):
        validate_laps(pd.DataFrame([row, {**row, "Driver": " E "}]))
    valid = validate_laps(pd.DataFrame([{**row, "Driver": " E ", "Event": " Bahrain "}]))
    assert valid.iloc[0].Driver == "E"
    assert valid.iloc[0].Event == "Bahrain"
