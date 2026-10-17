import json
from dataclasses import replace
from pathlib import Path

import pytest

from f1_strategy_optimizer.competition import (
    CarState,
    FixedPolicy,
    Physics,
    PitAction,
    PitRecord,
    RaceEvent,
    RaceState,
    ReactivePolicy,
    Scenario,
    candidate_actions,
    plan_positions,
    simulate,
)
from f1_strategy_optimizer.models import ModelParameters, TyreCurve, TyreModel
from f1_strategy_optimizer.race_planner import (
    ExplicitTyrePace,
    ScenarioTyreModel,
    main,
    plan_from_document,
)


def model():
    return ScenarioTyreModel(
        {
            "SOFT": ExplicitTyrePace(100, 1),
            "HARD": ExplicitTyrePace(102, 0.5),
            "INTERMEDIATE": ExplicitTyrePace(104, 0),
        }
    )


def flat_model():
    return ScenarioTyreModel(
        {"SOFT": ExplicitTyrePace(100, 0), "INTERMEDIATE": ExplicitTyrePace(104, 0)}
    )


def scenario(**kwargs):
    return Scenario("test", 1, 0, **kwargs)


def test_single_car_stint_cost_and_age_reset_are_independently_summed():
    state = RaceState(0, 3, (CarState("A", 100, "SOFT", 5),))
    result = simulate(
        model(),
        state,
        Physics(pit_loss=10),
        {
            "A": FixedPolicy((PitAction(1, "HARD"),)),
        },
        scenario(),
    )
    assert result.final_state.car("A").elapsed == pytest.approx(105 + 10 + 102 + 102.5)
    assert result.final_state.car("A").tyre_age == 2
    assert result.pit_history == (PitRecord("A", 1, "HARD"),)
    assert state.car("A").tyre_age == 5  # Input snapshot is not mutated.


def test_fast_car_is_blocked_without_sufficient_passing_advantage():
    state = RaceState(0, 1, (CarState("A", 100, "SOFT", 0), CarState("B", 98, "SOFT", 0, 0.1)))
    policies = {driver: FixedPolicy() for driver in state.order}
    blocked = simulate(flat_model(), state, Physics(passing_advantage=3), policies, scenario())
    assert blocked.final_state.order == ("A", "B")
    assert blocked.final_state.gaps()["B"] == pytest.approx(0.2)
    assert blocked.trace[0]["traffic_adjustment_seconds"]["B"] > 2
    passed = simulate(flat_model(), state, Physics(passing_advantage=0.8), policies, scenario())
    assert passed.final_state.order == ("B", "A")
    assert passed.trace[0]["passes"] == [{"driver": "B", "passed": "A"}]


@pytest.mark.parametrize("status", ["SC", "VSC"])
def test_neutralization_forbids_track_passes_but_allows_pit_order_changes(status):
    state = RaceState(
        0,
        1,
        (CarState("A", 100, "SOFT", 0), CarState("B", 95, "SOFT", 0, 0.1)),
        track_status=status,
    )
    policies = {"A": FixedPolicy(), "B": FixedPolicy()}
    result = simulate(flat_model(), state, Physics(), policies, scenario())
    assert result.final_state.order == ("A", "B")
    assert not result.trace[0]["passes"]
    policies["A"] = FixedPolicy((PitAction(0, "SOFT"),))
    result = simulate(flat_model(), state, Physics(), policies, scenario())
    assert result.final_state.order == ("B", "A")
    assert not result.trace[0]["passes"]


def test_sc_closes_gaps_gradually_while_vsc_preserves_equal_pace_gaps():
    state = RaceState(
        0, 2, (CarState("A", 100, "SOFT", 0), CarState("B", 100, "SOFT", 0, 20)), track_status="SC"
    )
    policies = {driver: FixedPolicy() for driver in state.order}
    sc = simulate(flat_model(), state, Physics(sc_catchup_per_lap=5), policies, scenario())
    assert [row["gaps_seconds"]["B"] for row in sc.trace] == pytest.approx([15, 10])
    vsc = simulate(
        flat_model(), replace(state, track_status="VSC"), Physics(), policies, scenario()
    )
    assert vsc.final_state.gaps()["B"] == pytest.approx(20)


@pytest.mark.parametrize("mode,expected_lap", [("cover_undercut", 1), ("overcut", 4)])
def test_reactive_opponent_changes_fixed_plan_only_after_observing_stop(mode, expected_lap):
    state = RaceState(0, 5, (CarState("EGO", 100, "SOFT", 0), CarState("R", 100, "SOFT", 0, 1)))
    ego = FixedPolicy((PitAction(0, "SOFT"),))
    physics = Physics(pit_loss=2)
    fixed = simulate(
        flat_model(),
        state,
        physics,
        {"EGO": ego, "R": FixedPolicy((PitAction(3, "SOFT"),))},
        scenario(),
    )
    reactive = ReactivePolicy("EGO", "SOFT", 3, 0, 4, mode=mode, overcut_laps=3)
    response = simulate(flat_model(), state, physics, {"EGO": ego, "R": reactive}, scenario())
    assert next(p.after_lap for p in fixed.pit_history if p.driver == "R") == 3
    assert next(p.after_lap for p in response.pit_history if p.driver == "R") == expected_lap
    assert response.trace[0]["pit_actions"] == {"EGO": "SOFT"}


def test_weather_reaction_sees_only_revealed_conditions_and_pays_current_pit_loss():
    class VisibleWeatherPolicy:
        def choose(self, observation, driver):
            assert not hasattr(observation, "events")
            assert all(
                p.after_lap < observation.state.completed_laps for p in observation.pit_history
            )
            if (
                observation.state.weather == "WET"
                and observation.state.car(driver).compound != "INTERMEDIATE"
            ):
                return "INTERMEDIATE"
            return None

    state = RaceState(0, 3, (CarState("A", 100, "SOFT", 0),))
    event = RaceEvent(2, track_status="SC", weather="WET")
    physics = Physics(wet_penalties={"SOFT": 10, "INTERMEDIATE": 0})
    result = simulate(
        flat_model(), state, physics, {"A": VisibleWeatherPolicy()}, scenario(events=(event,))
    )
    assert [row["pit_actions"] for row in result.trace] == [{}, {}, {"A": "INTERMEDIATE"}]
    assert result.trace[1]["decision_weather"] == "DRY"
    assert result.trace[1]["weather"] == "WET"
    # 100 dry + 110*1.4 wet-SC + known SC pit cost 10 + intermediate 104*1.4.
    assert result.final_state.car("A").elapsed == pytest.approx(100 + 154 + 10 + 145.6)
    # A scheduled stop immediately before an unrevealed SC still pays the green pit cost.
    early = simulate(
        flat_model(),
        state,
        physics,
        {"A": FixedPolicy((PitAction(1, "INTERMEDIATE"),))},
        scenario(events=(event,)),
    )
    assert early.final_state.car("A").elapsed == pytest.approx(100 + 20 + 145.6 * 2)


def test_forecast_and_historical_pit_timestamps_cannot_reveal_the_future():
    state = RaceState(0, 2, (CarState("A", 100, "SOFT", 0),))
    policies = {"A": FixedPolicy()}
    with pytest.raises(ValueError, match="not available"):
        simulate(flat_model(), state, Physics(), policies, Scenario("future", 1, 1))
    with pytest.raises(ValueError, match="no future replay"):
        Scenario("leak", 1, 0, kind="historical_future")
    with pytest.raises(ValueError, match="precede the decision"):
        simulate(flat_model(), state, Physics(), policies, scenario(), (PitRecord("A", 0, "SOFT"),))


def test_visible_prior_stop_can_trigger_replanning_without_hindsight():
    state = RaceState(1, 5, (CarState("A", 100, "SOFT", 0), CarState("R", 100, "SOFT", 2, 1)))
    policies = {"A": FixedPolicy(), "R": ReactivePolicy("A", "SOFT", 3, 1, 4)}
    result = simulate(
        flat_model(),
        state,
        Physics(),
        policies,
        Scenario("current", 1, 1),
        (PitRecord("A", 0, "SOFT"),),
    )
    assert result.trace[0]["pit_actions"] == {"R": "SOFT"}


def test_rank_distribution_is_weighted_and_independent_of_scenario_iteration_order():
    state = RaceState(
        0, 2, (CarState("A", 100, "SOFT", 0), CarState("B", 100, "INTERMEDIATE", 0, 1))
    )
    physics = Physics(wet_penalties={"SOFT": 10, "INTERMEDIATE": 0})
    cases = (Scenario("dry", 3, 0), Scenario("rain", 1, 0, (RaceEvent(1, weather="WET"),)))
    report = plan_positions(
        flat_model(), state, physics, "A", {"B": FixedPolicy()}, (PitAction(),), cases, risk_top_k=1
    )
    row = report["ranking"][0]
    assert row["position_distribution"] == {"1": 0.75, "2": 0.25}
    assert row["expected_finish_position"] == 1.25
    assert row["worst_finish_position"] == 2
    assert row["weighted_share_outside_top_k"] == 0.25
    assert row["position_std"] == pytest.approx((0.75 * 0.25) ** 0.5)
    reordered = plan_positions(
        flat_model(), state, physics, "A", {"B": FixedPolicy()}, (PitAction(),), cases[::-1]
    )
    assert reordered["ranking"][0]["position_distribution"] == row["position_distribution"]


def test_planner_prefers_stay_when_faster_pit_plan_does_not_improve_position():
    state = RaceState(0, 1, (CarState("A", 100, "SOFT", 10), CarState("B", 100, "SOFT", 0, 100)))
    actions = (PitAction(0, "SOFT"), PitAction())
    physics = Physics(pit_loss=5)
    report = plan_positions(
        model(), state, physics, "A", {"B": FixedPolicy()}, actions, (scenario(),)
    )
    assert report["recommended_action"] == {"after_lap": None, "compound": None}
    stay = simulate(model(), state, physics, {"A": FixedPolicy(), "B": FixedPolicy()}, scenario())
    pit = simulate(
        model(), state, physics, {"A": FixedPolicy((actions[0],)), "B": FixedPolicy()}, scenario()
    )
    assert pit.final_state.car("A").elapsed < stay.final_state.car("A").elapsed
    assert stay.final_state.order == pit.final_state.order == ("A", "B")


def test_existing_fitted_dry_model_interface_is_reused():
    fitted = TyreModel({"SOFT": TyreCurve(100, 0.1)}, ModelParameters(min_degradation={}))
    state = RaceState(0, 2, (CarState("A", 99, "SOFT", 0),))
    result = simulate(fitted, state, Physics(), {"A": FixedPolicy()}, scenario())
    assert result.final_state.car("A").elapsed == pytest.approx(99 + 99.1)


@pytest.mark.parametrize("lap", [-1, 2, True])
def test_candidate_generation_rejects_past_terminal_and_noninteger_pits(lap):
    state = RaceState(0, 2, (CarState("A", 100, "SOFT", 0),))
    with pytest.raises(ValueError):
        candidate_actions(state, ("SOFT",), (lap,))


def test_wet_simulation_requires_explicit_compound_assumptions():
    state = RaceState(0, 1, (CarState("A", 100, "SOFT", 0),), weather="WET")
    with pytest.raises(ValueError, match="explicit penalties"):
        simulate(flat_model(), state, Physics(), {"A": FixedPolicy()}, scenario())


def test_demo_cli_records_reproducible_input_responses_and_refuses_overwrite(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "competition.json"
    output = tmp_path / "名次规划"
    assert main(["--scenario", str(source), "--output-dir", str(output)]) == 0
    report = json.loads((output / "race-plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(report["ranking"]) == 13
    assert len(report["ranking"][0]["outcomes"]) == 4
    assert "synthetic" in report["source"]
    assert len(manifest["input_sha256"]) == 64
    assert manifest["input"] == json.loads(source.read_text())
    assert (output / "race-plan.md").stat().st_size > 500
    for row in report["ranking"]:
        assert sum(row["position_distribution"].values()) == pytest.approx(1)
        for outcome in row["outcomes"]:
            assert sorted(outcome["finish_order"]) == ["EGO", "FAST", "LEADER", "TRAFFIC"]
            assert len(outcome["trace"]) == 8
            for lap in outcome["trace"]:
                assert min(lap["gaps_seconds"].values()) == 0
    before = (output / "race-plan.json").read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["--scenario", str(source), "--output-dir", str(output)])
    assert exc.value.code == 2
    assert (output / "race-plan.json").read_bytes() == before


def test_cli_document_rejects_future_scenario_assumptions():
    source = Path(__file__).resolve().parents[1] / "examples" / "competition.json"
    document = json.loads(source.read_text())
    document["scenarios"][0]["available_at_lap"] = 46
    with pytest.raises(ValueError, match="not available"):
        plan_from_document(document)


def test_opponent_response_changes_position_outcomes_not_just_reported_stop_time():
    from copy import deepcopy

    source = Path(__file__).resolve().parents[1] / "examples" / "competition.json"
    document = json.loads(source.read_text())
    reactive = plan_from_document(document)
    fixed_document = deepcopy(document)
    for driver, policy in document["opponents"].items():
        if policy["kind"] == "reactive":
            fixed_document["opponents"][driver] = {
                "kind": "fixed",
                "stops": [{"after_lap": policy["planned_lap"], "compound": policy["compound"]}],
            }
    fixed = plan_from_document(fixed_document)
    reactive_row = next(row for row in reactive["ranking"] if row["label"] == "pit-after-45-MEDIUM")
    fixed_row = next(row for row in fixed["ranking"] if row["label"] == "pit-after-45-MEDIUM")
    assert fixed_row["expected_finish_position"] == 1
    assert reactive_row["expected_finish_position"] == 2.75
    assert reactive["recommended_action"] != fixed["recommended_action"]
