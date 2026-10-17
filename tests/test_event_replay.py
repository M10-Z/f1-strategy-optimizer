"""Causal boundary tests, distinct from the source-integrity adapter fixtures."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from f1_strategy_optimizer.event_replay import (
    EventTimePolicy,
    build_state,
    evaluate_frozen,
    freeze_decision,
    run_archive,
    summarize,
)

BASE = datetime(2023, 3, 5, 15, tzinfo=timezone.utc)


def at(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def archive():
    return {
        "session": {
            "session_key": 7953,
            "meeting_key": 1141,
            "year": 2023,
            "session_name": "Race",
            "date_start": at(0),
            "date_end": at(10000),
        },
        "drivers": [
            {"driver_number": n, "id": str(n), "team": "T", "name": str(n)} for n in (1, 2)
        ],
        "laps": [
            {
                "driver_number": n,
                "lap_number": lap,
                "date_start": at(100 * (lap - 1) + shift),
                "lap_duration": 90.0 + lap,
                "is_pit_out_lap": False,
            }
            for n, shift in ((1, 0), (2, 10))
            for lap in range(1, 9)
        ],
        "stints": [
            {
                "driver_number": n,
                "stint_number": s,
                "lap_start": lap,
                "lap_end": 5 if s == 1 else 8,
                "compound": "SOFT" if s == 1 else "HARD",
                "tyre_age_at_start": 0,
            }
            for n in (1, 2)
            for s, lap in ((1, 1), (2, 6))
        ],
        "position": [
            {"driver_number": n, "date": at(t), "position": n}
            for n in (1, 2)
            for t in (10, 440, 530, 600)
        ],
        "intervals": [
            {"driver_number": n, "date": at(t), "gap_to_leader": n + t / 1000}
            for n in (1, 2)
            for t in (400, 430, 440, 530, 545, 600)
        ],
        "weather": [
            {"date": at(t), "rainfall": 0, "track_temperature": 30, "air_temperature": 25}
            for t in (400, 600)
        ],
        "race_control": [
            {
                "date": at(t),
                "category": "Flag",
                "scope": "Track",
                "flag": "GREEN",
                "message": "GREEN LIGHT - PIT EXIT OPEN",
            }
            for t in (0, 600)
        ],
        "pitstops": [{"driverId": "1", "lap": 5}],
        "source_manifest": {"sha256": "full-archive-not-a-decision-feature"},
        "audit": {},
    }


def test_all_future_changes_leave_past_frozen_decision_identical():
    original = archive()
    before = freeze_decision(original, at(450))
    changed = deepcopy(original)
    for row in changed["laps"]:
        if row["lap_number"] >= 5:  # Current unfinished duration is also future information.
            row["lap_duration"] = 0.01
            row["is_pit_out_lap"] = True
    for row in changed["stints"]:
        row["lap_end"] = 999
        if row["lap_start"] == 6:
            row.update(compound="WET", tyre_age_at_start=99)
    for key in ("position", "intervals", "weather", "race_control"):
        changed[key] = [r for r in changed[key] if r["date"] <= at(450)]
    changed["laps"] += [
        {
            "driver_number": 1,
            "lap_number": 99,
            "date_start": at(10000),
            "lap_duration": 999,
            "is_pit_out_lap": True,
        }
    ]
    changed["pitstops"] = [{"driverId": "2", "lap": 7}]
    changed["final_results"] = {"winner": "2", "future_retirement": "1"}
    changed["source_manifest"]["sha256"] = "different-full-file-hash"
    changed["session"]["date_end"] = at(20000)
    assert freeze_decision(changed, at(450)) == before


def test_common_utc_does_not_force_same_completed_lap_or_read_future_stint_end():
    state = build_state(archive(), at(405))
    assert [r["completed_laps"]["value"] for r in state["cars"]] == [4, 3]
    assert all(r["compound"]["value"] == "SOFT" for r in state["cars"])
    assert "lap_end" not in json.dumps(state)
    assert state["track_status"]["status"] == "unknown"
    assert state["surface_condition"]["status"] == "unknown"
    assert state["field_complete"] is False


def test_delay_changes_visibility_without_retrospective_target_reselection():
    data = archive()
    frozen = freeze_decision(data, at(501), EventTimePolicy(publication_delay_seconds=20))
    assert frozen["observation_forecasts"][0]["lap"]["target_lap"] == 6
    evaluated = evaluate_frozen(frozen, data)
    assert evaluated["drivers"][0]["lap"]["reason"] == "target_already_started"
    assert frozen != freeze_decision(data, at(501), EventTimePolicy(publication_delay_seconds=0))


def test_new_next_start_cannot_turn_null_duration_into_completed_lap():
    data = archive()
    data["laps"][2]["lap_duration"] = None  # driver 1 lap 3
    state = build_state(data, at(450))
    assert 3 not in [r["lap_number"] for r in state["cars"][0]["completed_lap_history"]]


def test_future_outcomes_change_errors_only_and_missing_target_is_not_replaced():
    data = archive()
    frozen = freeze_decision(data, at(450))
    before = deepcopy(frozen)
    report = evaluate_frozen(frozen, data)
    changed = deepcopy(data)
    for r in changed["laps"]:
        if r["driver_number"] == 1 and r["lap_number"] == 6:
            r["lap_duration"] = 200
    later = evaluate_frozen(frozen, changed)
    assert report["drivers"][0]["lap"]["errors"] != later["drivers"][0]["lap"]["errors"]
    assert frozen == before
    changed["laps"] = [
        r for r in changed["laps"] if not (r["driver_number"] == 1 and r["lap_number"] == 6)
    ]
    missing = evaluate_frozen(frozen, changed)
    assert missing["drivers"][0]["lap"]["reason"] == "target_missing_no_retirement_inference"
    assert frozen["observation_forecasts"][0]["lap"]["target_lap"] == 6


@pytest.mark.parametrize("bad_gap", [None, "+1 LAP", -1])
def test_nonnumeric_gap_truth_is_excluded_not_zero(bad_gap):
    data = archive()
    frozen = freeze_decision(data, at(450))
    for r in data["intervals"]:
        if r["date"] == at(530):
            r["gap_to_leader"] = bad_gap
    report = evaluate_frozen(frozen, data)
    assert all(r["gap"]["reason"] == "invalid_or_null_interval_outcome" for r in report["drivers"])
    assert summarize([report])["gap"]["mae_seconds"] is None


def test_gap_outcome_is_last_available_new_report_never_nearest_future_report():
    data = archive()
    frozen = freeze_decision(data, at(450))
    result = evaluate_frozen(frozen, data)
    assert result["drivers"][0]["gap"]["event_at"] == at(530)  # 545 is after horizon.
    data["intervals"] = [r for r in data["intervals"] if r["date"] <= at(450)]
    result = evaluate_frozen(frozen, data)
    assert result["drivers"][0]["gap"]["reason"] == "no_new_interval_outcome"


def test_missing_key_data_blocks_every_strategy_without_blocking_observation_metrics():
    data = archive()
    frozen = freeze_decision(data, at(450))
    assert frozen["strategy"]["recommendation"] is None
    assert len(frozen["strategy"]["candidates"]) == 4
    assert all(
        c["prediction"] is None and c["effective_at"] is None and c["status"] == "blocked"
        for c in frozen["strategy"]["candidates"]
    )
    result = evaluate_frozen(frozen, data)
    assert result["strategy_errors"] is None and result["strategy_scored"] == 0
    assert result["drivers"][0]["lap"]["status"] == "scored_observation_only"


def test_freeze_tampering_and_unknown_zero_coverage_fail_closed():
    data = archive()
    frozen = freeze_decision(data, at(10))
    summary = summarize([evaluate_frozen(frozen, data)])
    assert summary["lap"]["mae_seconds"] is None
    assert summary["lap"]["paired_linear_minus_baseline_mae_seconds"] is None
    frozen["seed"] = 123
    with pytest.raises(ValueError, match="hash mismatch"):
        evaluate_frozen(frozen, data)


def test_durable_all_case_freeze_precedes_any_outcome_evaluation(tmp_path, monkeypatch):
    from f1_strategy_optimizer import event_replay

    output = tmp_path / "run"
    evaluate = event_replay.evaluate_frozen
    calls = []

    def spy(frozen, raw):
        stored = json.loads((output / "decisions.json").read_text())
        assert len(stored) == 2
        assert frozen in stored
        calls.append(frozen["decision_sha256"])
        return evaluate(frozen, raw)

    monkeypatch.setattr(event_replay, "evaluate_frozen", spy)
    run_archive(archive(), [at(450), at(470)], output)
    assert len(calls) == 2
    with pytest.raises(FileExistsError):
        run_archive(archive(), [at(450)], output)


def test_equivalent_cutoff_offsets_are_not_duplicate_weighted_cases(tmp_path):
    with pytest.raises(ValueError, match="distinct"):
        run_archive(archive(), [at(450), "2023-03-05T18:07:30+03:00"], tmp_path / "run")


def test_zero_numeric_gap_is_not_floored_to_positive_error():
    data = archive()
    for row in data["intervals"]:
        row["gap_to_leader"] = 0
    frozen = freeze_decision(data, at(450))
    assert frozen["observation_forecasts"][0]["gap"]["predictions"]["prefix_linear"] == 0
    assert evaluate_frozen(frozen, data)["drivers"][0]["gap"]["errors"]["prefix_linear"] == 0
