from copy import deepcopy

import pytest
from test_event_replay import archive, at

from f1_strategy_optimizer.action_evaluation import score_prediction
from f1_strategy_optimizer.action_model import confirm_action, fit_pit_prior, predict
from f1_strategy_optimizer.event_replay import freeze_decision
from f1_strategy_optimizer.prefix_quality import assess_prefix, make_context

PRIOR = {
    "in_seconds": 4.0,
    "out_seconds": 16.0,
    "sample_count": 10,
    "training_events": ["synthetic_training"],
}


def forecast(a, when=450, candidate="shrunk_local_trend"):
    f = freeze_decision(a, at(when))
    ctx = make_context(a, f)
    return f, ctx, predict(f, ctx, candidate, PRIOR)


def test_actual_future_pits_weather_and_current_unfinished_duration_do_not_change_forecast():
    a = archive()
    before = forecast(a)[2]
    for lap in a["laps"]:
        if lap["lap_number"] >= 5:
            lap.update(lap_duration=900, is_pit_out_lap=True)
    a["pitstops"] = [{"driverId": "1", "lap": 6, "duration_seconds": 500}]
    a["weather"].append({"date": at(460), "rainfall": 1})
    assert forecast(a)[2] == before


def test_future_action_and_completed_pit_without_effective_time_rejected():
    with pytest.raises(ValueError, match="Future"):
        confirm_action({"kind": "planned_pit", "decided_at": at(451)}, at(450))
    with pytest.raises(ValueError, match="requires"):
        confirm_action({"kind": "post_completed_pit", "decided_at": at(440)}, at(450))
    with pytest.raises(ValueError, match="before"):
        confirm_action(
            {"kind": "planned_pit", "decided_at": at(440), "effective_at": at(430)}, at(450)
        )


def test_fresh_one_lap_transition_fallback_retains_coverage_and_unknown_surface():
    a = archive()
    a["weather"].append({"date": at(440), "rainfall": 1})
    _, _, prediction = forecast(a)
    assert prediction["surface_state"] == "UNKNOWN"
    assert all(r["stay_seconds"] is not None for r in prediction["drivers"])
    assert all("fallback" in r["fallback"] for r in prediction["drivers"])


def test_control_and_stale_evidence_do_not_get_a_fallback_prediction():
    a = archive()
    a["race_control"].append({"date": at(440), "message": "VIRTUAL SAFETY CAR DEPLOYED"})
    assert all(r["stay_seconds"] is None for r in forecast(a)[2]["drivers"])
    a = archive()
    assert all(r["stay_seconds"] is None for r in forecast(a, 2000)[2]["drivers"])


def test_post_completed_outlap_target_is_not_silently_retargeted():
    a = archive()
    for lap in a["laps"]:
        if lap["lap_number"] == 4:
            lap["is_pit_out_lap"] = True
    for row in forecast(a)[2]["drivers"]:
        assert row["target_lap"] == 6
        post = row["post_completed_pit"]
        assert post["target_lap"] == 5
        assert post["prediction"] is None
        assert post["reason"] == "immediate_post_outlap_target_already_started"


def test_pit_action_matching_is_scoring_only_and_does_not_remove_all_target_error():
    a = archive()
    f, context, prediction = forecast(a)
    saved = deepcopy(prediction)
    for lap in a["laps"]:
        if lap["lap_number"] == 7:
            lap["is_pit_out_lap"] = True
        if lap["lap_number"] == 6:
            lap["lap_duration"] = 140
    scored = score_prediction(prediction, f, assess_prefix(f, context), a)
    assert prediction == saved
    assert all(r["category"] == "scored" and r["candidate_error"] > 40 for r in scored)
    assert all(r["planned_pit_error"] is not None for r in scored)
    assert all(not r["stay_action_matched"] for r in scored)


def test_sealed_belgian_prior_is_rejected():
    with pytest.raises(ValueError, match="sealed"):
        fit_pit_prior([], ["belgian-2024"])


def test_tampered_prediction_is_rejected_before_scoring():
    a = archive()
    f, ctx, p = forecast(a)
    p["drivers"][0]["stay_seconds"] = 0
    with pytest.raises(ValueError, match="freeze"):
        score_prediction(p, f, assess_prefix(f, ctx), a)
