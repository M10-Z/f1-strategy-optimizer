"""Browser API/export gates, never granting live forecast eligibility."""

from copy import deepcopy
from datetime import timedelta

import pytest

from f1_strategy_optimizer.event_replay import digest, dt, iso
from f1_strategy_optimizer.workbench import Workbench
from f1_strategy_optimizer.workbench_replay import replay_record


def selected():
    app = Workbench()
    case = list(app.cases)[-1]
    return app, {"case": case, "driver": "leclerc"}


def fixture(app, request):
    frozen = app.cases[request["case"]][1]
    baseline = app.horizon(request)
    original = baseline["selection"]["original_immediate_target_lap"]
    assert original is not None
    stream = "driver:leclerc:lap_state"
    return {
        "schema_version": 1, "session_id": str(frozen["state"]["session"]["session_key"]),
        "decision_sha256": frozen["decision_sha256"], "driver_id": "leclerc",
        "data_kind": "synthetic_fixture", "required_streams": [stream],
        "original_immediate_target_lap": original,
        "records": [{"event_id": "fixture-state", "stream": stream, "kind": "lap_state",
                     "source": "synthetic-receipt-fixture", "session_id": "7953",
                     "event_time": iso(dt(frozen["cutoff"]) - timedelta(seconds=1)),
                     "received_at": frozen["cutoff"], "sequence": 1, "revision": 0,
                     "payload": {"current_lap": original}}],
    }


def test_cached_horizons_preserve_original_and_never_read_reveals(monkeypatch):
    app, request = selected()
    monkeypatch.setattr(app, "_data", lambda _: pytest.fail("Horizon opened dataset/outcomes"))
    exact = app.horizon(request)
    later = app.horizon(request | {"horizon_request": {
        "horizon": "first_unstarted_after_confirmation"}})
    assert exact["selection"]["requested_horizon"] == "immediate_post_pit"
    assert exact["selection"]["original_immediate_target_lap"] == (
        later["selection"]["original_immediate_target_lap"])
    assert later["selection"]["candidate_target_lap"] is not None
    assert later["selection"]["selected_target_lap"] is None
    assert later["selection"]["prediction"] is None
    assert later["selection"]["availability_label"] == "retrospective assumed availability"
    record = app.export_horizon(request)
    assert replay_record(record)["status"] == "exact_match"
    assert record["kind"] == "local_workbench_horizon_record"


def test_late_revision_missing_receipt_and_import_identity_gates():
    app, request = selected()
    envelope = fixture(app, request)
    row = envelope["records"][0]
    envelope["records"].append({**row, "revision": 1, "sequence": 2,
                                 "received_at": iso(dt(row["received_at"])
                                                    + timedelta(seconds=30)),
                                 "payload": {"current_lap": 999}})
    req = request | {"horizon_request": {"horizon": "first_unstarted_after_confirmation",
                                        "mode": "recorded_receipts", "envelope": envelope}}
    report = app.horizon(req)
    visible = report["availability"]["snapshot"]
    assert next(iter(visible.values()))["revision"] == 0
    assert report["selection"]["selected_target_lap"] is None
    assert not report["prediction_enabled"]
    assert report["data_label"] == "synthetic_fixture_unverified"
    assert replay_record(app.export_horizon(req))["status"] == "exact_match"
    envelope["driver_id"] = "hamilton"
    with pytest.raises(ValueError, match="不匹配"):
        app.horizon(req)


def test_horizon_replay_rejects_rehashed_forged_target_and_invalid_request():
    app, request = selected()
    record = app.export_horizon(request)
    forged = deepcopy(record)
    forged["horizon_report"]["selection"]["selected_target_lap"] = 999
    forged["record_sha256"] = digest({k: v for k, v in forged.items() if k != "record_sha256"})
    with pytest.raises(ValueError, match="不能宣称已复现"):
        replay_record(forged)
    with pytest.raises(ValueError, match="horizon"):
        app.horizon(request | {"horizon_request": {"horizon": "automatic-retarget"}})
