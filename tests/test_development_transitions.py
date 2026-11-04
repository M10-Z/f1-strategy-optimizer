"""Posthoc labels may change diagnostics, never frozen predictions or denominators."""

import importlib.util
import json
from pathlib import Path

import pytest

from f1_strategy_optimizer.workbench import Workbench

SPEC = importlib.util.spec_from_file_location(
    "diagnose_bahrain_transitions",
    Path(__file__).resolve().parents[1] / "scripts" / "diagnose_bahrain_transitions.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def lap_fixture():
    app = Workbench()
    rows = {}
    for race, frozen in app.cases.values():
        evaluation = app._data(race["reveals"])[frozen["decision_sha256"]]
        for driver in evaluation["drivers"]:
            lap = driver["lap"]
            if driver["freshness_evaluation"]["lap_category"] != "scored":
                continue
            key = driver["driver_number"], lap["target_lap"]
            rows[key] = {
                "driver_number": key[0],
                "lap_number": key[1],
                "session_key": 7953,
                "meeting_key": 1141,
                "date_start": lap["start_at"],
                "lap_duration": lap["actual"],
                "is_pit_out_lap": False,
            }
    return list(rows.values())


def test_future_action_labels_do_not_change_forecasts_or_overall_error(tmp_path):
    path = tmp_path / "laps.json"
    rows = lap_fixture()
    path.write_text(json.dumps(rows))
    before = MODULE.diagnose(path, tmp_path / "before")
    for row in rows:
        row["is_pit_out_lap"] = True
    path.write_text(json.dumps(rows))
    after = MODULE.diagnose(path, tmp_path / "after")
    assert before["overall_unchanged"] == after["overall_unchanged"]
    assert before["fixed_slots_unchanged"] == after["fixed_slots_unchanged"] == 60
    assert (tmp_path / "before/predictions.json").read_bytes() == (
        tmp_path / "after/predictions.json"
    ).read_bytes()
    assert before["groups"]["transition_label_unavailable"]["n"] == 37
    assert before["label_unavailable_scored_slots"] == 37
    assert after["labelled_scored_slots"] == 37
    assert after["groups"]["target_is_outlap"]["n"] == 37
    assert not after["model_changed"]
    assert after["source_receipt_verified"] is False
    assert "origin not verified" in after["source_origin"]


@pytest.mark.parametrize("change", ["other_session", "duplicate", "changed_duration"])
def test_source_mismatch_is_not_a_valid_diagnostic(tmp_path, change):
    rows = lap_fixture()
    if change == "other_session":
        rows[0]["session_key"] = 9999
    elif change == "duplicate":
        rows.append(rows[0])
    else:
        rows[0]["lap_duration"] += 10
    path = tmp_path / "laps.json"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        MODULE.diagnose(path, tmp_path / "audit")
    assert not (tmp_path / "audit/transition-diagnostics.json").exists()


@pytest.mark.parametrize(
    "target,following,expected",
    [
        (True, True, "target_is_outlap"),
        (True, False, "target_is_outlap"),
        (False, True, "next_lap_is_outlap_proxy"),
        (None, True, "next_lap_is_outlap_proxy"),
        (False, False, "no_identified_pit_relation"),
        (False, None, "transition_label_unavailable"),
        (None, False, "transition_label_unavailable"),
        ("false", False, "transition_label_unavailable"),
        (False, 0, "transition_label_unavailable"),
    ],
)
def test_transition_label_precedence_and_unknown(target, following, expected):
    assert (
        MODULE.classify_transition({"is_pit_out_lap": target}, {"is_pit_out_lap": following})
        == expected
    )


def test_missing_following_lap_is_unknown_unless_target_is_outlap():
    assert MODULE.classify_transition({}, None) == "transition_label_unavailable"
    assert MODULE.classify_transition({"is_pit_out_lap": True}, None) == "target_is_outlap"


def test_next_lap_proxy_appears_in_full_report(tmp_path):
    rows = lap_fixture()
    first = rows[0]
    rows.append({**first, "lap_number": first["lap_number"] + 1, "is_pit_out_lap": True})
    path = tmp_path / "laps.json"
    path.write_text(json.dumps(rows))
    report = MODULE.diagnose(path, tmp_path / "report")
    assert report["groups"]["next_lap_is_outlap_proxy"]["n"] == 1
    assert report["labelled_scored_slots"] == 1
    assert report["label_unavailable_scored_slots"] == 36
    assert sum(group["n"] for group in report["groups"].values()) == 37
    assert report["coverage"] == pytest.approx(37 / 60)
