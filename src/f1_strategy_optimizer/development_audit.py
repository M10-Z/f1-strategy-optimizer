"""Reproduce forecasts and score the packaged Bahrain development sample only."""

import argparse
import hashlib
import json
import math
import os
import statistics
from collections import Counter
from pathlib import Path

from .event_replay import dt
from .workbench import DEFAULT_DATA, Workbench


def _write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _metrics(values):
    values = sorted(values)
    return {
        "n": len(values),
        "mae_seconds": statistics.mean(values) if values else None,
        "p95_seconds": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        "p95_definition": "nearest_rank_ceiling_0.95_n",
        "max_error_seconds": max(values) if values else None,
    }


def audit_development(output_dir):
    """Never fit, tune, acquire data, or open a reserved/archived holdout catalog."""
    app = Workbench(DEFAULT_DATA, expected_races={"bahrain-2023": "development"})
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    predictions = [app.forecast(case) for case in app.cases]
    _write(output / "predictions.json", predictions)
    prediction_hash = hashlib.sha256((output / "predictions.json").read_bytes()).hexdigest()
    _write(
        output / "prediction-receipt.json",
        {"sha256": prediction_hash, "saved_before_outcome_read": True, "mode": "development"},
    )
    # Only now read already-observed development outcomes. Never feed them back.
    scored, categories, all_rows = [], Counter(), []
    for forecast in predictions:
        race, frozen = app.cases[forecast["case"]]
        driver_ids = [row["driver_id"] for row in forecast["drivers"]]
        expected_ids = {car["id"] for car in frozen["state"]["cars"]}
        if len(driver_ids) != len(expected_ids) or set(driver_ids) != expected_ids:
            raise ValueError("Forecast driver coverage differs from the frozen denominator")
        evaluation = app._data(race["reveals"])[frozen["decision_sha256"]]
        if evaluation["decision_sha256"] != forecast["decision_sha256"]:
            raise ValueError("Outcome does not match the frozen decision")
        outcomes = {row["driver_id"]: row for row in evaluation["drivers"]}
        baselines = {row["driver_id"]: row for row in frozen["observation_forecasts"]}
        for row in forecast["drivers"]:
            outcome = outcomes[row["driver_id"]]
            saved = outcome["freshness_evaluation"]
            if (
                saved["target_lap"] != row["target_lap"]
                or saved["prediction"] != row["predicted_lap_seconds"]
            ):
                raise ValueError("Current forecast differs from archived development prediction")
            category = saved["lap_category"]
            categories[category] += 1
            record = {
                "cutoff": forecast["cutoff"],
                "driver_id": row["driver_id"],
                "target_lap": row["target_lap"],
                "category": category,
                "prediction": row["predicted_lap_seconds"],
                "actual": None,
                "candidate_abs_error": None,
                "baseline_abs_error": None,
            }
            if category == "scored":
                lap = outcome["lap"]
                if dt(lap["start_at"]) <= dt(forecast["cutoff"]):
                    raise ValueError("Scored target had already started at decision time")
                if lap["target_lap"] != row["target_lap"]:
                    raise ValueError("Scored target does not match forecast target")
                error = abs(row["predicted_lap_seconds"] - lap["actual"])
                baseline_value = baselines[row["driver_id"]]["lap"]["predictions"]["prefix_median"]
                baseline = abs(baseline_value - lap["actual"])
                if not math.isclose(error, saved["candidate_abs_error"], abs_tol=1e-9):
                    raise ValueError("Recomputed forecast error differs from stored score")
                if not math.isclose(
                    baseline, saved["baseline_abs_error_same_target"], abs_tol=1e-9
                ):
                    raise ValueError("Paired baseline differs from stored score")
                record.update(
                    actual=lap["actual"], candidate_abs_error=error, baseline_abs_error=baseline
                )
                scored.append(record)
            all_rows.append(record)
    count = len(all_rows)
    applicable = count - categories["not_applicable_post_event_proxy"]
    candidate = _metrics([row["candidate_abs_error"] for row in scored])
    baseline = _metrics([row["baseline_abs_error"] for row in scored])
    summary = {
        "schema_version": 1,
        "event": "Bahrain 2023",
        "partition": "previously_observed_development_sample",
        "new_independent_validation": False,
        "model_changed": False,
        "live_validation": False,
        "case_count": len(predictions),
        "fixed_slots": count,
        "applicable_slots": applicable,
        "scored_slots": len(scored),
        "coverage": len(scored) / applicable if applicable else None,
        "categories": dict(categories),
        "candidate": candidate,
        "paired_prefix_median_baseline": baseline,
        "paired_mae_ratio": candidate["mae_seconds"] / baseline["mae_seconds"]
        if baseline["mae_seconds"]
        else None,
        "prediction_sha256": prediction_hash,
        "dataset_sha256": app.data_hashes,
        "integrity_checks": {
            "forecast_equals_archived_prediction": True,
            "scored_target_starts_after_cutoff": True,
            "recomputed_error_equals_saved_error": True,
            "future_outcomes_used_as_input": False,
            "sealed_holdout_read": False,
        },
        "limitations": [
            "Only three previously observed cutoffs from one development race",
            "Driver/cutoff observations are dependent; no independence or calibration claim",
            "Selective forecast coverage; all excluded slots retained in denominator",
            "No new accuracy improvement, causal strategy benefit or live-readiness evidence",
            "Scores rely on packaged source-verified historical outcomes, not a fresh raw download",
        ],
    }
    _write(output / "rows.json", all_rows)
    _write(output / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = audit_development(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
