"""Development replay audit must never become another holdout evaluator."""

import json
import shutil

import pytest

from f1_strategy_optimizer import development_audit as audit
from f1_strategy_optimizer.workbench import Workbench


def test_real_development_metrics_and_receipt_precede_outcome_access(tmp_path, monkeypatch):
    destination = tmp_path / "audit"
    original = Workbench._data

    def checked(self, name):
        if "reveals" in name:
            assert (destination / "predictions.json").is_file()
            assert (destination / "prediction-receipt.json").is_file()
        return original(self, name)

    monkeypatch.setattr(Workbench, "_data", checked)
    report = audit.audit_development(destination)
    assert report["fixed_slots"] == 60
    assert report["scored_slots"] == 37
    assert report["categories"] == {
        "scored": 37,
        "candidate_abstention": 19,
        "target_data_missing": 4,
    }
    assert report["candidate"]["mae_seconds"] == pytest.approx(1.0336756756756755)
    assert report["paired_prefix_median_baseline"]["mae_seconds"] == pytest.approx(1.1487972973)
    assert report["candidate"]["max_error_seconds"] == pytest.approx(20.128)
    assert not report["new_independent_validation"]
    assert not report["model_changed"]
    assert json.loads((destination / "summary.json").read_text()) == report
    with pytest.raises(FileExistsError):
        audit.audit_development(destination)


@pytest.mark.parametrize("mode", ["mixed", "holdout_partition", "duplicate"])
def test_holdout_catalog_is_rejected_before_any_decision_read(tmp_path, monkeypatch, mode):
    from f1_strategy_optimizer import workbench

    root = tmp_path / "catalog"
    shutil.copytree(audit.DEFAULT_DATA, root)
    path = root / "catalog.json"
    catalog = json.loads(path.read_text())
    if mode == "mixed":
        catalog["races"].append(
            {"id": "reserved", "partition": "holdout", "decisions": "reserved-decisions.json"}
        )
        (root / "reserved-decisions.json").write_text("[]")
    elif mode == "holdout_partition":
        catalog["races"][0]["partition"] = "holdout"
    else:
        catalog["races"].append(dict(catalog["races"][0]))
    path.write_text(json.dumps(catalog))
    opened = []
    original = workbench._load

    def tracked(path):
        opened.append(path.name)
        return original(path)

    monkeypatch.setattr(workbench, "_load", tracked)
    monkeypatch.setattr(audit, "DEFAULT_DATA", root)
    with pytest.raises(ValueError, match="restricted"):
        audit.audit_development(tmp_path / "forbidden")
    assert opened == ["catalog.json"]
    assert not (tmp_path / "forbidden").exists()


def test_changed_prediction_fails_instead_of_reporting_old_metrics(tmp_path, monkeypatch):
    original = Workbench.forecast

    def changed(self, case, driver=None):
        result = original(self, case, driver)
        for row in result["drivers"]:
            if row["predicted_lap_seconds"] is not None:
                row["predicted_lap_seconds"] += 1
        return result

    monkeypatch.setattr(Workbench, "forecast", changed)
    with pytest.raises(ValueError, match="differs"):
        audit.audit_development(tmp_path / "changed")
    assert not (tmp_path / "changed" / "summary.json").exists()


def test_empty_metrics_are_unknown_not_zero():
    assert audit._metrics([])["mae_seconds"] is None
    assert audit._metrics([])["p95_seconds"] is None


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown"])
def test_driver_denominator_cannot_silently_change(tmp_path, monkeypatch, change):
    original = Workbench.forecast

    def changed(self, case, driver=None):
        result = original(self, case, driver)
        if change == "missing":
            result["drivers"].pop()
        elif change == "duplicate":
            result["drivers"][-1] = result["drivers"][0]
        else:
            result["drivers"][-1]["driver_id"] = "unknown-driver"
        return result

    monkeypatch.setattr(Workbench, "forecast", changed)
    with pytest.raises(ValueError, match="denominator"):
        audit.audit_development(tmp_path / change)
    assert not (tmp_path / change / "summary.json").exists()
