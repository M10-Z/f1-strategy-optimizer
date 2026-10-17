"""Time/transition boundaries, not outcome-conditioned feature selection."""

from copy import deepcopy
from datetime import timedelta

import pytest

from f1_strategy_optimizer.event_replay import digest, dt
from f1_strategy_optimizer.prefix_quality import assess_prefix, make_context
from f1_strategy_optimizer.workbench import Workbench


def frozen():
    app = Workbench()
    return deepcopy(next(iter(app.cases.values()))[1])


def rehash(f):
    f.pop("decision_sha256")
    f["decision_sha256"] = digest(f)
    return f


def row(f, offset, **extra):
    return {"date": (dt(f["cutoff"]) - timedelta(seconds=offset)).isoformat(), **extra}


def test_context_ignores_future_weather_and_gaps():
    f = frozen()
    a = {
        "weather": [row(f, 10, rainfall=0)],
        "intervals": [row(f, 5, driver_number=16, gap_to_leader=3)],
    }
    before = make_context(a, f)
    a["weather"].append(row(f, -60, rainfall=1))
    a["intervals"].append(row(f, -60, driver_number=16, gap_to_leader=99))
    assert make_context(a, f) == before
    bad = deepcopy(before)
    bad["weather_history"].append(row(f, 1, rainfall=1))
    bad.pop("context_sha256")
    bad["context_sha256"] = digest(bad)
    with pytest.raises(ValueError, match="Future"):
        assess_prefix(f, bad)


def test_stale_lap_abstains_and_keeps_original_forecast():
    f = frozen()
    old = deepcopy(f["observation_forecasts"])
    f["cutoff"] = (dt(f["cutoff"]) + timedelta(hours=1)).isoformat()
    f["state"]["cutoff"] = f["cutoff"]
    rehash(f)
    q = assess_prefix(f)
    assert all(d["candidate"]["value_seconds"] is None for d in q["drivers"].values())
    assert q["drivers"]["leclerc"]["lap"]["reliability"] == "stale"
    assert f["observation_forecasts"] == old


def test_control_ending_not_clear_and_clear_requires_new_laps():
    f = frozen()
    f["state"]["visible_race_control"] = [
        row(f, 60, message="VIRTUAL SAFETY CAR DEPLOYED"),
        row(f, 10, message="VIRTUAL SAFETY CAR ENDING"),
    ]
    rehash(f)
    q = assess_prefix(f)
    assert q["race_control"]["usable_state"] == "VSC"
    assert (
        q["drivers"]["leclerc"]["candidate"]["reason"] == "control_active_or_clearance_unconfirmed"
    )
    f["state"]["visible_race_control"].append(row(f, 4, message="TRACK CLEAR"))
    rehash(f)
    q = assess_prefix(f)
    assert q["race_control"]["usable_state"] == "GREEN"
    assert (
        q["drivers"]["leclerc"]["candidate"]["reason"]
        == "segment_warmup_requires_three_completed_laps"
    )


def test_local_green_does_not_claim_whole_track_clear():
    f = frozen()
    f["state"]["visible_race_control"] = [row(f, 4, message="GREEN", flag="GREEN", scope="Sector")]
    rehash(f)
    assert assess_prefix(f)["race_control"]["usable_state"] == "UNKNOWN"


def test_rain_transition_requires_warmup_not_dry_track_inference():
    f = frozen()
    a = {"weather": [row(f, 100, rainfall=1), row(f, 4, rainfall=0)], "intervals": []}
    q = assess_prefix(f, make_context(a, f))
    assert q["drivers"]["leclerc"]["candidate"]["value_seconds"] is None
    assert q["weather"]["surface_state"].startswith("UNKNOWN")
    assert q["weather"]["rain_signal_transition_at"] == a["weather"][-1]["date"]


def test_completed_outlap_resets_segment_but_does_not_read_future_pits():
    f = frozen()
    car = next(c for c in f["state"]["cars"] if c["id"] == "leclerc")
    car["completed_lap_history"][-1]["is_pit_out_lap"] = True
    rehash(f)
    q = assess_prefix(f)
    assert q["drivers"]["leclerc"]["candidate"]["sample_laps"] == []
    assert (
        q["drivers"]["leclerc"]["candidate"]["reason"]
        == "segment_warmup_requires_three_completed_laps"
    )


def test_invalid_gap_retains_age_instead_of_becoming_zero():
    f = frozen()
    ctx = make_context(
        {"weather": [], "intervals": [row(f, 20, driver_number=16, gap_to_leader="+1 LAP")]}, f
    )
    gap = assess_prefix(f, ctx)["drivers"]["leclerc"]["gap"]
    assert gap["last_reported_value"] == "+1 LAP" and not gap["numeric_usable"]
    assert gap["age_seconds_at_cutoff"] == 20 and gap["reliability"] == "stale"


def test_evaluation_post_event_is_separate_from_missing_and_abstention():
    from f1_strategy_optimizer.freshness_evaluation import evaluate_quality, summarize_quality

    f = frozen()
    w = Workbench()
    case = next(iter(w.cases))
    race = w.cases[case][0]
    baseline = w._data(race["reveals"])[f["decision_sha256"]]
    archive = {"laps": [{"date_start": "2023-03-05T15:00:00Z", "lap_duration": 100}]}
    result = evaluate_quality(f, None, archive, baseline)
    s = summarize_quality([result])
    assert s["categories"] == {"not_applicable_post_event_proxy": 20}
    assert s["applicable_slots"] == 0 and s["candidate_mae_seconds"] is None
    assert all(r["candidate_abs_error"] is None for r in result["drivers"])
