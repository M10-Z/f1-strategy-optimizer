"""Forecast API safety, missingness and real packaged-prefix integration."""

import json
import threading
from copy import deepcopy
from datetime import timedelta
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from f1_strategy_optimizer.event_replay import digest, dt
from f1_strategy_optimizer.forecast_service import forecast_report
from f1_strategy_optimizer.workbench import Handler, Workbench


def setup():
    app = Workbench()
    case = next(iter(app.cases))
    return app, case, deepcopy(app.cases[case][1])


def rehash(frozen):
    frozen.pop("decision_sha256")
    frozen["decision_sha256"] = digest(frozen)


def test_forecast_never_reads_outcomes_and_preserves_default(monkeypatch):
    app, case, frozen = setup()
    original = app._data

    def prefix_only(name):
        assert "reveal" not in name and "evidence" not in name
        return original(name)

    monkeypatch.setattr(app, "_data", prefix_only)
    report = app.forecast(case)
    assert report["summary"]["drivers"] == 20
    assert report["summary"]["available"] + report["summary"]["abstained"] == 20
    assert report["model"]["id"] == "visible_segment_median_v1"
    assert report["model"]["validation_status"] == "failed_acceptance"
    assert report["live_ready"] is False
    assert app.cases[case][1] == frozen
    assert app.revealed == {}
    assert '"actual":' not in json.dumps(report)
    assert all(row["prediction_interval"] is None for row in report["drivers"])


def test_forecast_keeps_stale_values_null_and_reports_reason():
    _, _, frozen = setup()
    frozen["cutoff"] = (dt(frozen["cutoff"]) + timedelta(hours=1)).isoformat()
    frozen["state"]["cutoff"] = frozen["cutoff"]
    rehash(frozen)
    report = forecast_report(frozen)
    assert report["summary"] == {
        "drivers": 20,
        "available": 0,
        "abstained": 20,
        "abstention_reasons": {"missing_or_stale_lap_evidence": 20},
    }
    assert all(row["predicted_lap_seconds"] is None for row in report["drivers"])
    assert all(row["reason_zh"] for row in report["drivers"])
    assert all(row["gap"]["value_seconds"] is None for row in report["drivers"])


def test_selected_driver_matches_existing_candidate_and_has_reproducible_hash():
    app, case, _ = setup()
    first = app.forecast(case, "leclerc")
    assert first == app.forecast(case, "leclerc")
    candidate = app.quality(case)["drivers"]["leclerc"]["candidate"]
    assert len(first["drivers"]) == 1
    row = first["drivers"][0]
    assert row["predicted_lap_seconds"] == candidate["value_seconds"]
    assert row["target_lap"] == candidate["target_lap"]
    assert row["sample_laps"] == candidate["sample_laps"]
    assert row["target_start_verified"] is False
    assert "source_publication_unverified" in row["blocking_factors"]
    payload = {k: v for k, v in first.items() if k not in {"case", "report_sha256"}}
    assert digest(payload) == first["report_sha256"]


def test_unknown_driver_is_rejected_not_silently_substituted():
    app, case, _ = setup()
    with pytest.raises(ValueError, match="车手"):
        app.forecast(case, "not-a-driver")


def test_tampered_and_future_prefixes_fail():
    _, _, frozen = setup()
    frozen["cutoff"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="hash"):
        forecast_report(frozen)
    _, _, frozen = setup()
    frozen["state"]["cars"][0]["completed_lap_history"][-1]["assumed_available_at"] = (
        dt(frozen["cutoff"]) + timedelta(seconds=1)
    ).isoformat()
    rehash(frozen)
    with pytest.raises(ValueError, match="Future"):
        forecast_report(frozen)


def test_forecast_http_endpoint_and_unknown_selection():
    app, case, _ = setup()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.app = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/forecast?"
    try:
        with urlopen(base + urlencode({"case": case, "driver": "leclerc"}), timeout=5) as response:
            report = json.load(response)
            assert response.headers["Cache-Control"] == "no-store"
        assert report["drivers"][0]["driver_id"] == "leclerc"
        with pytest.raises(HTTPError) as error:
            urlopen(base + urlencode({"case": "missing"}), timeout=5)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
