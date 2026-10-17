import json
from dataclasses import asdict, replace
from math import comb
from pathlib import Path

import pytest

from f1_strategy_optimizer.competition import (
    CarState,
    FixedPolicy,
    Physics,
    PitAction,
    PitPlan,
    PlanningObjective,
    RaceEvent,
    RaceState,
    ReactivePolicy,
    Scenario,
    candidate_actions,
    candidate_plans,
    plan_positions,
    simulate,
)
from f1_strategy_optimizer.race_constraints import CompetitionRules, InfeasibleRacePlan
from f1_strategy_optimizer.race_planner import ExplicitTyrePace, ScenarioTyreModel, main
from f1_strategy_optimizer.rolling import rolling_plan


def model():
    return ScenarioTyreModel(
        {
            "SOFT": ExplicitTyrePace(100, 0.5),
            "HARD": ExplicitTyrePace(101, 0.15),
            "INTERMEDIATE": ExplicitTyrePace(104, 0),
        }
    )


def test_resources_cli_preserves_rules_inventory_and_rolling_evidence(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "competition-resources.json"
    output = tmp_path / "resources"
    assert main(["--scenario", str(source), "--output-dir", str(output)]) == 0
    report = json.loads((output / "race-plan.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert report["schema_version"] == 2
    assert report["search"]["candidate_count"] == 67
    assert report["search"]["scenario_count"] == 4
    assert report["search"]["rollouts_executed"] <= 67 * 4
    assert report["search"]["elapsed_seconds"] >= 0
    assert report["rules"] == manifest["input"]["rules"]
    assert report["objective_config"]["mode"] == "team_rank_sum"
    assert any(len(row["stops"]) == 2 for row in report["ranking"])
    rolling = report["rolling_simulation"]
    assert rolling["status"] == "finished"
    assert len(rolling["decisions"]) == 8
    assert rolling["rollouts_executed"] <= 2000
    assert rolling["final_state"]["completed_laps"] == 53
    assert all(c["pit_stops"] >= 2 for c in rolling["final_state"]["cars"])
    for car in rolling["final_state"]["cars"]:
        assert all(count >= 0 for _, count in car["tyre_inventory"])
    assert "Rolling simulation" in (output / "race-plan.md").read_text()


@pytest.mark.parametrize("failure", ["inventory", "budget"])
def test_cli_exports_infeasible_or_unfinished_result_with_nonzero_exit(tmp_path, failure):
    source = Path(__file__).resolve().parents[1] / "examples" / "competition-resources.json"
    document = json.loads(source.read_text())
    if failure == "inventory":
        document["state"]["cars"][0]["tyre_inventory"] = {}
    else:
        document["rolling"]["total_rollout_budget"] = 1
    supplied = tmp_path / "scenario.json"
    supplied.write_text(json.dumps(document))
    output = tmp_path / "report"
    assert main(["--scenario", str(supplied), "--output-dir", str(output)]) == 2
    report = json.loads((output / "race-plan.json").read_text())
    if failure == "inventory":
        assert report["status"] == "no_feasible_candidate"
        assert report["recommended_action"] is None
        assert report["rejected_candidates"]
    else:
        assert report["status"] == "feasible"
        assert report["rolling_simulation"]["status"] == "rollout_budget_exhausted"
        assert report["rolling_simulation"]["final_state"]["completed_laps"] == 45


def case(name="synthetic", events=()):
    return Scenario(name, 1, 0, events)


def state(cars, total=4, **kwargs):
    return RaceState(0, total, tuple(cars), season=2026, event="SYNTHETIC", **kwargs)


def rules(**kwargs):
    return CompetitionRules(
        season=2026,
        event="SYNTHETIC",
        source="Original test assumptions, not an event regulation",
        **kwargs,
    )


def test_inventory_consumes_fresh_sets_without_replenishing_removed_tyres():
    initial = state([CarState("E", 100, "SOFT", 2, tyre_inventory={"HARD": 1})])
    policy = FixedPolicy((PitAction(0, "HARD"),))
    result = simulate(model(), initial, Physics(), {"E": policy}, case())
    assert dict(result.final_state.car("E").tyre_inventory) == {"HARD": 0}
    assert dict(initial.car("E").tyre_inventory) == {"HARD": 1}
    assert result.final_state.car("E").pit_stops == 1
    assert set(result.final_state.car("E").used_compounds) == {"SOFT", "HARD"}
    with pytest.raises(InfeasibleRacePlan, match="no spare HARD"):
        simulate(
            model(),
            initial,
            Physics(),
            {"E": FixedPolicy((PitAction(0, "HARD"), PitAction(2, "HARD")))},
            case(),
        )


def test_missing_inventory_key_means_zero_not_unlimited():
    initial = state([CarState("E", 100, "SOFT", 1, tyre_inventory={})])
    report = plan_positions(
        model(), initial, Physics(), "E", {}, (PitAction(), PitAction(0, "HARD")), (case(),)
    )
    assert report["recommended_action"] == {"after_lap": None, "compound": None}
    assert len(report["rejected_candidates"]) == 1
    assert "no spare HARD" in report["rejected_candidates"][0]["first_failure"]["reason"]
    assert report["inventory_scope"]["E"] == "finite_fresh_spares"


def test_two_stop_plan_is_selected_when_required_and_inventory_permits():
    initial = state([CarState("E", 100, "SOFT", 1, tyre_inventory={"SOFT": 1, "HARD": 1})])
    constraint = rules(min_stops=2, min_dry_compounds=2, max_tyre_age={"SOFT": 2, "HARD": 2})
    plans = candidate_plans(initial, ("SOFT", "HARD"), (0, 1, 2, 3))
    assert len(plans) == 1 + 4 * 2 + comb(4, 2) * 2**2
    report = plan_positions(
        model(), initial, Physics(pit_loss=1), "E", {}, plans, (case(),), rules=constraint
    )
    assert report["status"] == "feasible"
    assert len(report["recommended_stops"]) == 2
    assert all(len(row["stops"]) == 2 for row in report["ranking"])
    resource = report["ranking"][0]["outcomes"][0]["final_resources"]["E"]
    assert resource["inventory"] == {"HARD": 0, "SOFT": 0}
    assert resource["pit_stops"] == 2


def test_insufficient_inventory_yields_no_recommendation_not_a_rule_relaxation():
    initial = state([CarState("E", 100, "SOFT", 1, tyre_inventory={"HARD": 1})])
    plans = candidate_plans(initial, ("HARD",), (0, 1, 2))
    report = plan_positions(
        model(), initial, Physics(), "E", {}, plans, (case(),), rules=rules(min_stops=2)
    )
    assert report["status"] == "no_feasible_candidate"
    assert report["ranking"] == []
    assert report["recommended_action"] is None
    assert len(report["rejected_candidates"]) == len(plans)


def test_rule_scope_and_source_are_explicit():
    with pytest.raises(ValueError, match="explicit season and event"):
        CompetitionRules(min_stops=1)
    initial = state([CarState("E", 100, "SOFT", 1)])
    with pytest.raises(ValueError, match="does not match"):
        plan_positions(
            model(),
            replace(initial, season=2025),
            Physics(),
            "E",
            {},
            (PitAction(),),
            (case(),),
            rules=rules(min_stops=1),
        )
    report = plan_positions(
        model(),
        initial,
        Physics(),
        "E",
        {},
        (PitAction(),),
        (case(),),
        rules=rules(min_dry_compounds=1),
    )
    assert report["rules"]["source_status"] == "configurable_assumption"
    assert report["rules"]["event"] == "SYNTHETIC"
    assert report["weight_interpretation"].startswith("user_supplied")
    with pytest.raises(ValueError, match="no empirical probabilities"):
        Scenario("false-calibration", 1, 0, weight_kind="empirical")


def test_rain_does_not_waive_requirements_without_wet_tyre_use():
    initial = state(
        [CarState("E", 100, "SOFT", 1, tyre_inventory={"INTERMEDIATE": 1})], total=1, weather="WET"
    )
    constraint = rules(
        min_dry_compounds=2, mandatory_dry_compounds=("HARD",), wet_waives_dry_requirement=True
    )
    physics = Physics(wet_penalties={"SOFT": 10, "HARD": 12, "INTERMEDIATE": 0})
    report = plan_positions(
        model(),
        initial,
        physics,
        "E",
        {},
        (PitAction(), PitAction(0, "INTERMEDIATE")),
        (case(),),
        rules=constraint,
    )
    assert report["recommended_action"]["compound"] == "INTERMEDIATE"
    assert report["rejected_candidates"][0]["label"] == "stay-out"
    # A separate minimum-stop requirement is not implicitly waived by wet-tyre use.
    report = plan_positions(
        model(),
        initial,
        physics,
        "E",
        {},
        (PitAction(0, "INTERMEDIATE"),),
        (case(),),
        rules=replace(constraint, min_stops=2),
    )
    assert report["status"] == "no_feasible_candidate"


def test_prior_wet_usage_and_prior_stops_persist_in_snapshot():
    initial = state(
        [CarState("E", 100, "SOFT", 1, used_compounds=("INTERMEDIATE",), pit_stops=2)], total=1
    )
    result = simulate(
        model(),
        initial,
        Physics(),
        {"E": FixedPolicy()},
        case(),
        rules=rules(min_dry_compounds=2, min_stops=2, wet_waives_dry_requirement=True),
    )
    assert result.final_state.car("E").pit_stops == 2


def test_prior_forbidden_compound_and_driven_age_limit_are_checked():
    initial = state([CarState("E", 100, "SOFT", 2, used_compounds=("HARD",))], total=1)
    with pytest.raises(InfeasibleRacePlan, match="prior use"):
        simulate(
            model(),
            initial,
            Physics(),
            {"E": FixedPolicy()},
            case(),
            rules=rules(allowed_compounds=("SOFT",)),
        )
    with pytest.raises(InfeasibleRacePlan, match="tyre age"):
        simulate(
            model(),
            initial,
            Physics(),
            {"E": FixedPolicy()},
            case(),
            rules=rules(max_tyre_age={"SOFT": 2}),
        )


def test_same_team_queue_uses_arrival_gaps_and_does_not_double_charge_service():
    flat = ScenarioTyreModel({"SOFT": ExplicitTyrePace(100, 0)})
    initial = state(
        [CarState("A", 100, "SOFT", 0, team="T"), CarState("B", 100, "SOFT", 0, 0.5, team="T")],
        total=1,
    )
    policies = {d: FixedPolicy((PitAction(0, "SOFT"),)) for d in initial.order}
    result = simulate(flat, initial, Physics(pit_loss=10, pit_service_time=3), policies, case())
    assert result.trace[0]["pit_queue_wait_seconds"] == {"A": 0, "B": 2.5}
    assert result.final_state.car("A").elapsed == 110
    assert result.final_state.car("B").elapsed == 113
    independent = replace(initial, cars=(initial.cars[0], replace(initial.cars[1], team="Other")))
    result = simulate(flat, independent, Physics(pit_loss=10, pit_service_time=3), policies, case())
    assert result.trace[0]["pit_queue_wait_seconds"]["B"] == 0


def test_cooperative_objective_avoids_double_stack_to_protect_teammate_rank():
    pace = ScenarioTyreModel(
        {"SOFT": ExplicitTyrePace(100, 0.5), "HARD": ExplicitTyrePace(101, 0.1)}
    )
    initial = state(
        [
            CarState("E", 97, "SOFT", 8, team="T"),
            CarState("M", 99, "SOFT", 8, 0.2, team="T"),
            CarState("R", 100, "HARD", 1, 1.2),
        ]
    )
    physics = Physics(pit_loss=3, pit_service_time=3)
    opponents = {"M": FixedPolicy((PitAction(0, "HARD"),)), "R": FixedPolicy()}
    actions = candidate_actions(initial, ("HARD",), (0, 1, 2, 3))
    own = plan_positions(pace, initial, physics, "E", opponents, actions, (case(),))
    team = plan_positions(
        pace,
        initial,
        physics,
        "E",
        opponents,
        actions,
        (case(),),
        objective=PlanningObjective("team_rank_sum", "T"),
    )
    assert own["recommended_action"]["after_lap"] == 0
    assert team["recommended_action"]["after_lap"] == 1
    assert team["ranking"][0]["outcomes"][0]["finish_order"] == ["E", "M", "R"]
    assert own["ranking"][0]["outcomes"][0]["finish_order"] == ["E", "R", "M"]
    assert team["ranking"][0]["expected_objective"] == 3


def test_faster_elapsed_time_can_lose_rank_after_opponent_countermove():
    initial = state([CarState("E", 100, "SOFT", 8), CarState("R", 99, "SOFT", 8, 0.2)])
    opponent = ReactivePolicy("E", "HARD", 2, 0, 3, response_gap=30)
    actions = (PitAction(0, "HARD"), PitAction(1, "HARD"))
    report = plan_positions(
        model(), initial, Physics(pit_loss=5), "E", {"R": opponent}, actions, (case(),)
    )
    rows = {row["label"]: row for row in report["ranking"]}
    fast, slower = rows["pit-after-0-HARD"], rows["pit-after-1-HARD"]
    assert fast["expected_elapsed_seconds"] == pytest.approx(409.9)
    assert slower["expected_elapsed_seconds"] == pytest.approx(412.45)
    assert fast["expected_finish_position"] == 2
    assert slower["expected_finish_position"] == 1
    assert report["recommended_action"]["after_lap"] == 1


def test_low_performance_car_keeps_track_position_when_overtaking_is_restricted():
    pace = ScenarioTyreModel({"SOFT": ExplicitTyrePace(100, 0)})
    initial = state(
        [CarState("SLOW", 101, "SOFT", 0), CarState("FAST", 100, "SOFT", 0, 0.1)], total=3
    )
    report = plan_positions(
        pace,
        initial,
        Physics(passing_advantage=2, pit_loss=5),
        "SLOW",
        {"FAST": FixedPolicy()},
        (PitAction(), PitAction(0, "SOFT")),
        (case(),),
    )
    assert report["recommended_action"]["after_lap"] is None
    assert report["ranking"][0]["expected_finish_position"] == 1
    assert report["ranking"][1]["expected_finish_position"] == 2


def test_one_infeasible_case_rejects_candidate_without_renormalizing_weights():
    class WetStop:
        def choose(self, observation, driver):
            return "HARD" if observation.state.weather == "WET" else None

    initial = state(
        [CarState("E", 100, "SOFT", 0), CarState("R", 100, "SOFT", 0, 1, tyre_inventory={})],
        total=2,
    )
    cases = (case("dry"), case("rain", (RaceEvent(1, weather="WET"),)))
    report = plan_positions(
        model(),
        initial,
        Physics(wet_penalties={"SOFT": 10, "HARD": 10, "INTERMEDIATE": 0}),
        "E",
        {"R": WetStop()},
        (PitAction(),),
        cases,
    )
    assert report["ranking"] == []
    assert report["rejected_candidates"][0]["first_failure"]["scenario"] == "rain"


def test_bounded_grid_and_rollout_budget_fail_before_search():
    initial = state([CarState("E", 100, "SOFT", 0)], total=10)
    with pytest.raises(ValueError, match="exceeding budget"):
        candidate_plans(initial, ("SOFT", "HARD"), tuple(range(10)), max_candidates=10)
    with pytest.raises(ValueError, match="at most two"):
        candidate_plans(initial, ("SOFT",), (0, 1, 2), max_stops=3)
    with pytest.raises(ValueError, match="rollout budget"):
        plan_positions(
            model(),
            initial,
            Physics(),
            "E",
            {},
            (PitAction(), PitAction(0, "HARD")),
            (case(),),
            max_rollouts=1,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        PitPlan((PitAction(2, "HARD"), PitAction(1, "SOFT")))


def test_rolling_replanning_preserves_consumed_inventory_and_completed_stops():
    initial = state([CarState("E", 100, "SOFT", 1, tyre_inventory={"SOFT": 1, "HARD": 1})])
    constraint = rules(min_stops=2, min_dry_compounds=2, max_tyre_age={"SOFT": 2, "HARD": 2})
    observed = []

    def beliefs(view):
        observed.append(view)
        return (Scenario("current-assumption", 1, view.state.completed_laps),)

    result = rolling_plan(
        model(),
        initial,
        Physics(pit_loss=1),
        "E",
        {},
        beliefs,
        case(),
        ("SOFT", "HARD"),
        pit_offsets=(0, 1, 2, 3),
        rules=constraint,
    )
    assert result.status == "finished"
    assert result.final_state.car("E").pit_stops == 2
    assert dict(result.final_state.car("E").tyre_inventory) == {"HARD": 0, "SOFT": 0}
    assert len(result.pit_history) == 2
    assert len(result.decisions) == 4
    for view in observed:
        assert all(p.after_lap < view.state.completed_laps for p in view.pit_history)
    assert sum(observed[-1].state.car("E").tyre_inventory[i][1] for i in range(2)) == 0


def test_unrevealed_realization_changes_cannot_change_earlier_rolling_actions():
    initial = state([CarState("E", 100, "SOFT", 4, tyre_inventory={"HARD": 2})])

    def beliefs(view):
        assert not hasattr(view, "events")
        return (Scenario("visible-only", 1, view.state.completed_laps),)

    common = dict(
        model=model(),
        initial=initial,
        physics=Physics(),
        ego="E",
        opponents={},
        belief_provider=beliefs,
        compounds=("HARD",),
        pit_offsets=(0, 1),
        max_decisions=4,
    )
    dry = rolling_plan(realization=case(), **common)
    sc = rolling_plan(realization=case(events=(RaceEvent(3, track_status="SC"),)), **common)
    for a, b in zip(dry.decisions[:3], sc.decisions[:3]):
        assert a["recommended_stops"] == b["recommended_stops"]
        assert a["visible_track_status"] == b["visible_track_status"] == "GREEN"
    assert sc.decisions[3]["visible_track_status"] == "SC"
    assert dry.decisions[3]["visible_track_status"] == "GREEN"


def test_rolling_total_budget_reports_partial_status_without_inventing_finish():
    initial = state([CarState("E", 100, "SOFT", 0)])
    result = rolling_plan(
        model(),
        initial,
        Physics(),
        "E",
        {},
        lambda view: (case(),),
        case(),
        ("HARD",),
        pit_offsets=(0,),
        total_rollout_budget=1,
    )
    assert result.status == "rollout_budget_exhausted"
    assert result.final_state.completed_laps == 0
    assert result.decisions == []
    assert result.rollouts_executed == 0


def test_snapshot_inventory_roundtrip_is_immutable_and_preserves_values():
    car = CarState(
        "E", 100, "SOFT", 3, tyre_inventory={"HARD": 2}, used_compounds=("MEDIUM",), pit_stops=1
    )
    assert CarState(**asdict(car)) == car
    assert isinstance(car.tyre_inventory, tuple)
    with pytest.raises(ValueError):
        replace(car, tyre_inventory={"HARD": -1})
