import json
from copy import deepcopy
from pathlib import Path

import pytest

from f1_strategy_optimizer.replay import evaluate_replay, frozen_decision, main


def example():
    path = Path(__file__).resolve().parents[1] / "examples" / "replay-synthetic.json"
    return json.loads(path.read_text())


def selections(report):
    return [
        {
            "hash": r["decision_input_sha256"],
            "plans": {
                k: {key: value for key, value in v.items() if key != "evaluation"}
                for k, v in r["strategies"].items()
            },
        }
        for r in report["cases"]
    ]


def test_synthetic_replay_reports_partition_coverage_and_action_matched_errors():
    report = evaluate_replay(example())
    assert report["source_status"] == "synthetic_fixture"
    assert report["search"]["rollouts_executed"] == 5
    development = report["coverage"]["development"]
    holdout = report["coverage"]["holdout"]
    assert development["methods"]["position"]["gap_mae_seconds"] == pytest.approx(0.2)
    assert holdout["methods"]["position"]["gap_mae_seconds"] == pytest.approx(0.05)
    assert holdout["methods"]["elapsed_time"]["evaluated_cases"] == 0
    assert holdout["methods"]["elapsed_time"]["action_mismatches"] == 1
    assert holdout["methods"]["elapsed_time"]["position_mae"] is None
    assert development["paired_position_minus_elapsed_time"]["cases"] == 1
    assert holdout["paired_position_minus_elapsed_time"]["cases"] == 0
    assert (
        holdout["paired_position_minus_elapsed_time"]["error_differences"]["position_mae"] is None
    )
    case = report["cases"][1]
    assert case["strategies"]["position"]["label"] == "pit-after-5-HARD"
    assert case["strategies"]["elapsed_time"]["label"] == "pit-after-4-HARD"


def test_changed_future_outcome_cannot_change_any_decision_plan_or_input_hash():
    original = example()
    modified = deepcopy(original)
    modified["cases"][0]["outcome"]["cars"][1]["gap_seconds"] = 50
    modified["cases"][1]["outcome"]["track_status"] = "SC"
    modified["cases"][1]["outcome"]["weather"] = "WET"
    before, after = evaluate_replay(original), evaluate_replay(modified)
    assert selections(before) == selections(after)
    assert before["coverage"] != after["coverage"]
    modified["cases"][1].pop("outcome")
    missing = evaluate_replay(modified)
    assert selections(before) == selections(missing)
    assert missing["cases"][1]["status"] == "outcome_rejected"


def test_decision_function_accepts_only_packet_not_outcome(monkeypatch):
    import f1_strategy_optimizer.replay as replay

    supplied = example()
    original = replay.plan_from_document
    calls = []

    def spy(planning):
        assert "outcome" not in planning
        calls.append(deepcopy(planning))
        return original(planning)

    class GuardedCase(dict):
        def __getitem__(self, key):
            if key == "outcome":
                assert len(calls) == 1
            return super().__getitem__(key)

    supplied["cases"] = [GuardedCase(supplied["cases"][0])]
    monkeypatch.setattr(replay, "plan_from_document", spy)
    replay.evaluate_replay(supplied)
    assert calls[0] == frozen_decision(
        supplied["cases"][0]["decision"], "development", supplied["splits"]
    )


@pytest.mark.parametrize("field", ["available_at", "assumptions_available_at"])
def test_unavailable_decision_information_is_rejected(field):
    supplied = example()
    supplied["cases"][1]["decision"][field] = "2024-03-01T12:01:00Z"
    report = evaluate_replay(supplied)
    assert report["cases"][1]["status"] == "decision_rejected"
    assert "strategies" not in report["cases"][1]
    assert report["coverage"]["holdout"]["methods"]["position"]["evaluated_cases"] == 0


def test_training_cutoff_is_checked_separately_from_decision_time():
    supplied = example()
    decision = supplied["cases"][1]["decision"]
    decision.update(model_kind="fitted", model_data_end_at="2024-02-01T12:00:00Z")
    report = evaluate_replay(supplied)
    assert "training cutoff" in report["cases"][1]["reason"]
    decision["model_data_end_at"] = "2023-12-01T12:00:00Z"
    assert evaluate_replay(supplied)["cases"][1]["status"] == "outcome_valid"


@pytest.mark.parametrize("problem", ["missing_weather", "lapped", "incomplete", "null_laps"])
def test_missing_or_unsupported_snapshot_is_explicitly_unscored(problem):
    supplied = example()
    decision = supplied["cases"][0]["decision"]
    if problem == "missing_weather":
        decision["planning"]["state"].pop("weather")
    elif problem == "lapped":
        decision["driver_completed_laps"]["R"] = 3
    elif problem == "incomplete":
        decision["field_complete"] = False
    else:
        decision["driver_completed_laps"] = None
    report = evaluate_replay(supplied)
    assert report["cases"][0]["status"] == "decision_rejected"
    assert report["cases"][0]["reason"]
    assert report["cases"][1]["status"] == "outcome_valid"


@pytest.mark.parametrize(
    "problem", ["missing_car", "lapped", "unknown_pits", "backdated", "compound"]
)
def test_invalid_outcome_preserves_plan_but_never_produces_error_metrics(problem):
    supplied = example()
    outcome = supplied["cases"][0]["outcome"]
    if problem == "missing_car":
        outcome["cars"].pop()
    elif problem == "lapped":
        outcome["cars"][1]["completed_laps"] = 4
    elif problem == "unknown_pits":
        outcome["pit_actions_complete"] = False
    elif problem == "backdated":
        outcome["observed_at"] = "2023-03-01T11:00:00Z"
    else:
        outcome["cars"][1]["compound"] = "HARD"
    report = evaluate_replay(supplied)
    assert report["cases"][0]["status"] == "outcome_rejected"
    assert report["cases"][0]["strategies"]["position"]["label"] == "stay-out"
    assert report["coverage"]["development"]["methods"]["position"]["position_mae"] is None


def test_other_driver_action_mismatch_blocks_scoring_even_if_ego_matches():
    supplied = example()
    outcome = supplied["cases"][0]["outcome"]
    outcome["pit_actions"] = {"R": "HARD"}
    outcome["cars"][1].update(compound="HARD", tyre_age=1)
    report = evaluate_replay(supplied)
    case = report["cases"][0]
    assert case["status"] == "outcome_valid"
    assert all(s["evaluation"]["status"] == "action_mismatch" for s in case["strategies"].values())


def test_batch_budget_and_unknown_stock_are_reported_without_fabricated_errors():
    supplied = example()
    supplied["max_total_rollouts"] = 2
    supplied["cases"][0]["decision"]["planning"]["state"]["cars"][0].pop("tyre_inventory")
    report = evaluate_replay(supplied)
    assert report["search"]["rollouts_executed"] == 2
    assert report["cases"][0]["inventory_scope"]["E"] == "unspecified_unlimited"
    assert report["cases"][1]["status"] == "budget_exhausted"
    assert report["coverage"]["holdout"]["methods"]["position"]["position_mae"] is None


def test_provenance_and_timezone_validation():
    supplied = example()
    supplied["provenance"]["source"] = ""
    with pytest.raises(ValueError, match="nonempty"):
        evaluate_replay(supplied)
    supplied = example()
    supplied["cases"][0]["decision"]["at"] = "2023-03-01T12:00:00"
    report = evaluate_replay(supplied)
    assert "timezone" in report["cases"][0]["reason"]


def test_replay_cli_artifacts_and_no_overwrite(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "replay-synthetic.json"
    output = tmp_path / "回放"
    assert main(["--input", str(source), "--output-dir", str(output)]) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["input"] == example()
    assert len(manifest["input_sha256"]) == 64
    saved = (output / "replay.json").read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["--input", str(source), "--output-dir", str(output)])
    assert exc.value.code == 2
    assert (output / "replay.json").read_bytes() == saved
    assert "no causal" in (output / "replay.md").read_text()


def test_cli_writes_partial_evidence_and_returns_nonzero(tmp_path):
    supplied = example()
    supplied["cases"][1].pop("outcome")
    source = tmp_path / "input.json"
    source.write_text(json.dumps(supplied))
    assert main(["--input", str(source), "--output-dir", str(tmp_path / "report")]) == 2
    report = json.loads((tmp_path / "report" / "replay.json").read_text())
    assert report["rejected_cases"] == 1
    assert report["case_status_counts"]["outcome_valid"] == 1
