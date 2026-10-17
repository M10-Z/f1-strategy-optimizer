"""Decision-affecting workbench boundaries, using the packaged real frozen prefix."""

import json
from copy import deepcopy

import pytest

from f1_strategy_optimizer.event_replay import digest
from f1_strategy_optimizer.strategy_exploration import propose_exploration
from f1_strategy_optimizer.workbench import Workbench
from f1_strategy_optimizer.workbench_replay import replay_record


def setup():
    app = Workbench()
    case = next(iter(app.cases))
    return app, case, app.cases[case][1], app.assumptions(case, "leclerc")


def test_prefix_initialization_has_no_future_reads_and_no_double_tyre_count(monkeypatch):
    app, case, frozen, assumptions = setup()
    monkeypatch.setattr(app, "_data", lambda _: deepcopy(assumptions))
    a = app.assumptions(case, "leclerc")
    forecasts = {f["driver_id"]: f for f in frozen["observation_forecasts"]}
    p = a["planning"]
    for car in p["state"]["cars"]:
        curve = p["tyres"][car["compound"]]
        next_lap = (
            car["base_lap_time"]
            + curve["base_time"]
            + curve["degradation"] * car["tyre_age"]
            - p["physics"]["reference_lap_time"]
        )
        assert next_lap == pytest.approx(
            forecasts[car["driver"]]["default_prediction"]["lap"]["value_seconds"]
        )
        assert car["tyre_inventory"] is None
    assert (
        p["state"]["completed_laps"]
        == next(c for c in frozen["state"]["cars"] if c["id"] == "leclerc")["completed_laps"][
            "value"
        ]
    )
    assert all(
        c["team"] == next(f["team"] for f in frozen["state"]["cars"] if f["id"] == c["driver"])
        for c in p["state"]["cars"]
    )


def test_all_field_keeps_unknown_and_explicit_custom_scope():
    app, case, frozen, _ = setup()
    all_cars = app.assumptions(case, "leclerc", "all")
    assert len(all_cars["planning"]["state"]["cars"]) == 20
    assert any(c["gap_seconds"] is None for c in all_cars["planning"]["state"]["cars"])
    with pytest.raises(ValueError, match="缺少"):
        propose_exploration(frozen, all_cars)
    custom = app.assumptions(case, "leclerc", "custom", ["leclerc", "sainz"])
    r = propose_exploration(frozen, custom)
    assert r["model_scope"]["drivers"] == ["leclerc", "sainz"]
    assert len(r["model_scope"]["excluded_drivers"]) == 18


def test_opponent_response_and_vehicle_pace_actually_change_rollouts():
    _, _, frozen, a = setup()
    base = propose_exploration(frozen, a)
    changed = deepcopy(a)
    p = changed["planning"]
    p["opponents"]["sainz"] = {
        "kind": "reactive",
        "rival": "leclerc",
        "compound": "HARD",
        "planned_lap": 12,
        "window_start": 8,
        "window_end": 13,
        "mode": "cover_undercut",
        "response_gap": 100,
    }
    p["state"]["cars"][2]["base_lap_time"] += 5
    result = propose_exploration(frozen, changed)
    original = base["stay_out"]["candidate"]["outcomes"][0]
    outcome = result["stay_out"]["candidate"]["outcomes"][0]
    assert original["driver_elapsed_seconds"]["sainz"] != outcome["driver_elapsed_seconds"]["sainz"]
    assert any("sainz" in row["pit_actions"] for row in outcome["trace"])
    pit_candidate = next(c for c in result["top3"] if c["stops"])
    trace = pit_candidate["outcomes"][0]["trace"]
    ego_stop = next(t["lap"] for t in trace if "leclerc" in t["pit_actions"])
    mate_stop = next(t["lap"] for t in trace if "sainz" in t["pit_actions"])
    assert mate_stop > ego_stop  # response observes a completed pit, never simultaneous intent


def test_no_feasible_plan_still_reports_rejected_stay_out():
    _, _, frozen, a = setup()
    p = a["planning"]
    p["rules"] = {"season": p["state"]["season"], "event": p["state"]["event"], "min_stops": 2}
    r = propose_exploration(frozen, a)
    assert r["status"] == "no_feasible_candidate"
    assert r["top3"] == []
    assert r["stay_out"]["status"] == "infeasible" and r["stay_out"]["rejection"]


def test_export_replay_ignores_outcome_evidence_but_detects_changed_file():
    app, case, frozen, a = setup()
    report = propose_exploration(frozen, a)
    app.jobs["fixture"] = {
        "case": case,
        "driver": "leclerc",
        "status": "succeeded",
        "assumptions_sha256": digest(a),
        "assumptions": a,
        "report": report,
    }
    record = app.export(
        {"case": case, "driver": "leclerc", "job_id": "fixture", "assumptions_sha256": digest(a)}
    )
    assert replay_record(json.loads(json.dumps(record)))["status"] == "exact_match"
    record["source_evidence"] = {"actual_future": "should never be read"}
    record["reveal"] = {"actual_future": "should never be read"}
    record["record_sha256"] = digest({k: v for k, v in record.items() if k != "record_sha256"})
    assert replay_record(json.loads(json.dumps(record)))["status"] == "exact_match"
    record["assumptions"]["planning"]["physics"]["pit_loss"] = 0
    with pytest.raises(ValueError, match="哈希"):
        replay_record(record)
