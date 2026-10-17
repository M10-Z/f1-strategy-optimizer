"""Integration boundaries for the local UI, using the actual frozen Bahrain sample."""

import json
import time
from copy import deepcopy

import pytest

from f1_strategy_optimizer.event_replay import digest
from f1_strategy_optimizer.workbench import Workbench


def selected(app):
    case = next(iter(app.cases))
    return {
        "case": case,
        "driver": "leclerc",
        "acknowledged": True,
        "assumptions": app.assumptions(case, "leclerc"),
    }


def wait(app, key):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = app.job(key)
        if result["status"] != "running":
            return result
        time.sleep(0.02)
    pytest.fail("workbench process did not finish")


def test_catalog_and_decision_do_not_read_outcome_file(monkeypatch):
    from f1_strategy_optimizer import workbench

    original, opened = workbench._load, []

    def spy(path):
        opened.append(path.name)
        return original(path)

    monkeypatch.setattr(workbench, "_load", spy)
    app = Workbench()
    document = selected(app)
    assert len(app.catalog()["races"][0]["cases"]) == 3
    assert '"actual":' not in json.dumps(app.decision(document["case"]))
    reveal_file = app.cases[document["case"]][0]["reveals"]
    assert reveal_file not in opened
    revealed = app.reveal(document["case"], document["driver"])
    assert revealed["evaluation"]["lap"]["actual"] == 99.073
    assert reveal_file in opened


def test_actual_example_job_and_export_keep_matching_selection_and_hashes():
    app = Workbench()
    document = selected(app)
    before = deepcopy(document)
    key = app.start(document)["id"]
    result = wait(app, key)
    assert result["status"] == "succeeded", result
    assert document == before
    assert len(result["report"]["top3"]) == 3
    request = {
        "case": document["case"],
        "driver": document["driver"],
        "job_id": key,
        "assumptions_sha256": result["assumptions_sha256"],
    }
    exported = app.export(request)
    assert exported["reveal"] is None
    assert exported["exploration"]["model_scope"]["modeled_driver_count"] == 5
    assert exported["dataset_file_sha256"]
    saved_hash = exported.pop("record_sha256")
    assert digest(exported) == saved_hash
    with pytest.raises(ValueError, match="假设已修改"):
        app.export(request | {"assumptions_sha256": "changed"})
    with pytest.raises(ValueError, match="不匹配"):
        app.export(request | {"driver": "hamilton"})


def test_timeout_cancels_real_process_with_readable_status():
    app = Workbench(timeout=0.001)
    key = app.start(selected(app))["id"]
    result = wait(app, key)
    assert result["status"] == "timed_out"
    assert "已停止" in result["error"]
    assert "report" not in result


def test_job_rejects_missing_ack_and_mismatched_ego_before_start():
    app = Workbench()
    document = selected(app)
    with pytest.raises(ValueError, match="确认"):
        app.start(document | {"acknowledged": False})
    with pytest.raises(ValueError, match="ego"):
        app.start(document | {"driver": "hamilton"})
    assert not app.jobs


@pytest.mark.parametrize("driver", ["hamilton", "sainz", "perez", "max_verstappen"])
def test_template_driver_mapping_preserves_explicit_field_and_opponents(driver):
    app = Workbench()
    case = next(iter(app.cases))
    result = app.assumptions(case, driver)
    planning = result["planning"]
    assert planning["ego"] == driver
    ids = {c["driver"] for c in planning["state"]["cars"]}
    assert 2 <= len(ids) <= 7 and driver in ids
    assert set(planning["opponents"]) == ids - {driver}
    assert set(result["model_subset"]["drivers"]) == ids
