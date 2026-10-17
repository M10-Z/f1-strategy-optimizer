"""Observation-only decision packets and separate next-lap replay evaluation.

Input is a normalized export from a trusted cache, not a raw FastF1 cache parser.
Later outcomes never enter plan_from_document. Action mismatches are unscored,
not evidence for or against the causal value of an unobserved strategy.
"""

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from math import comb
from pathlib import Path

from .artifacts import _versions, write_json
from .config import finite_number, positive_int
from .race_constraints import nonnegative_int
from .race_planner import plan_from_document


def timestamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} requires an ISO timestamp with timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires a timezone")
    return parsed


def named(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty")
    return value


def frozen_decision(decision, partition, splits):
    """Validate only the decision packet. No outcome object is accepted here."""
    if partition not in {"development", "holdout"}:
        raise ValueError("partition must be development or holdout")
    at = timestamp(decision["at"], "decision.at")
    observed = timestamp(decision["observed_at"], "decision.observed_at")
    available = timestamp(decision["available_at"], "decision.available_at")
    if not observed <= available <= at:
        raise ValueError("Observation must be observed and available by the decision time")
    if timestamp(decision["assumptions_available_at"], "assumptions_available_at") > at:
        raise ValueError("Assumptions were unavailable at the decision time")
    if decision["field_complete"] is not True:
        raise ValueError("Full active field coverage must be explicitly confirmed")
    model_kind = decision["model_kind"]
    cutoff = decision["model_data_end_at"]
    if model_kind == "fitted":
        cutoff = timestamp(cutoff, "model_data_end_at")
        if cutoff > at:
            raise ValueError("Model training uses data after the decision")
    elif model_kind != "assumed" or cutoff is not None:
        raise ValueError("Use model_kind=fitted with cutoff, or assumed with null cutoff")
    if partition == "holdout":
        if at < timestamp(splits["holdout_start_at"], "holdout_start_at"):
            raise ValueError("Holdout decision precedes the declared holdout period")
        if cutoff is not None and cutoff > timestamp(splits["training_end_at"], "training_end_at"):
            raise ValueError("Fitted model exceeds the declared training cutoff")
    planning = deepcopy(decision["planning"])
    if "joint" in planning or "rolling" in planning:
        raise ValueError("Replay v1 supports single-ego snapshot planning only")
    if planning.get("objective", {}).get("mode", "driver_position") != "driver_position":
        raise ValueError("Replay comparison requires the individual position objective")
    state = planning["state"]
    positive_int(state["season"], "state.season")
    named(state["event"], "state.event")
    if state["event"] == "unspecified":
        raise ValueError("Observed race event must be identified")
    # These must be observed, not simulator defaults silently filling missing fields.
    for key in ("track_status", "weather", "track_temp"):
        if key not in state or state[key] is None:
            raise ValueError(f"Missing observed state.{key}")
    cars = state["cars"]
    drivers = [c["driver"] for c in cars]
    laps = decision["driver_completed_laps"]
    if not isinstance(laps, dict):
        raise ValueError("driver_completed_laps must explicitly map every driver to a lap")
    for value in laps.values():
        nonnegative_int(value, "driver_completed_laps")
    if set(laps) != set(drivers) or any(v != state["completed_laps"] for v in laps.values()):
        raise ValueError("Missing driver laps or lapped field: same-lap snapshots only")
    for car in cars:
        for key in ("gap_seconds", "compound", "tyre_age", "team", "base_lap_time"):
            if key not in car or car[key] is None:
                raise ValueError(f"Missing {car['driver']} snapshot field: {key}")
        named(car["team"], "team")
        rules = planning.get("rules", {})
        if rules.get("min_stops", 0) and "pit_stops" not in car:
            raise ValueError("Minimum-stop rules require known prior pit_stops for each car")
        if (rules.get("min_dry_compounds", 0) or rules.get("mandatory_dry_compounds")) and (
            "used_compounds" not in car
        ):
            raise ValueError("Dry-compound rules require known used_compounds for each car")
    return planning


def observed_next_lap(outcome, decision, planning):
    observed = timestamp(outcome["observed_at"], "outcome.observed_at")
    available = timestamp(outcome["available_at"], "outcome.available_at")
    if not timestamp(decision["at"], "decision.at") < observed <= available:
        raise ValueError("Outcome must be observed after the decision and then available")
    state = planning["state"]
    positive_int(outcome["completed_laps"], "outcome.completed_laps")
    if outcome["completed_laps"] != state["completed_laps"] + 1:
        raise ValueError("Replay v1 requires the immediately following lap")
    if outcome["field_complete"] is not True or outcome["pit_actions_complete"] is not True:
        raise ValueError("Outcome needs complete field and known pit actions")
    if outcome["pit_after_lap"] != state["completed_laps"]:
        raise ValueError("Observed pit actions must belong to the decision boundary")
    if outcome["track_status"] not in {"GREEN", "SC", "VSC"}:
        raise ValueError("Unsupported observed track status")
    if outcome["weather"] not in {"DRY", "WET"}:
        raise ValueError("Unsupported observed weather")
    drivers = {c["driver"] for c in state["cars"]}
    cars = outcome["cars"]
    if len(cars) != len(drivers) or {c["driver"] for c in cars} != drivers:
        raise ValueError("Outcome field differs: missing cars, duplicates or retirements")
    for car in cars:
        positive_int(car["completed_laps"], "outcome driver lap")
        if car["completed_laps"] != outcome["completed_laps"]:
            raise ValueError("Lapped outcome is outside the same-lap model")
        positive_int(car["position"], "outcome.position")
        positive_int(car["tyre_age"], "outcome.tyre_age")
        finite_number(car["gap_seconds"], "outcome.gap_seconds", 0)
        named(car["compound"], "outcome.compound")
    ordered = sorted(cars, key=lambda c: c["position"])
    if [c["position"] for c in ordered] != list(range(1, len(cars) + 1)):
        raise ValueError("Outcome positions must be a complete permutation")
    gaps = [c["gap_seconds"] for c in ordered]
    if gaps[0] != 0 or gaps != sorted(gaps):
        raise ValueError("Outcome gaps must agree with the position order and leader gap zero")
    actions = outcome["pit_actions"]
    if not isinstance(actions, dict) or set(actions) - drivers:
        raise ValueError("Unknown observed pit driver")
    if any(not isinstance(c, str) or c not in planning["tyres"] for c in actions.values()):
        raise ValueError("Observed pit compound is unsupported by the supplied tyre model")
    before = {c["driver"]: c for c in state["cars"]}
    if any(
        c["compound"] != actions.get(c["driver"], before[c["driver"]]["compound"]) for c in cars
    ):
        raise ValueError("Observed tyre compounds disagree with recorded pit actions")
    return {c["driver"]: c for c in cars}


def forecast_error(row, truth, outcome):
    # Actions must match for the ENTIRE active field, not only for the ego.
    if any(o["trace"][0]["pit_actions"] != outcome["pit_actions"] for o in row["outcomes"]):
        return {"status": "action_mismatch", "metrics": None}
    predicted = {}
    for driver in truth:
        predicted[driver] = {
            "mean_position": sum(
                o["weight"] * (o["trace"][0]["order"].index(driver) + 1) for o in row["outcomes"]
            ),
            "mean_gap_seconds": sum(
                o["weight"] * o["trace"][0]["gaps_seconds"][driver] for o in row["outcomes"]
            ),
        }
    count = len(truth)
    return {
        "status": "evaluated_action_match",
        "predicted_next_lap": predicted,
        "metrics": {
            "driver_count": count,
            "position_mae": sum(
                abs(predicted[d]["mean_position"] - truth[d]["position"]) for d in truth
            )
            / count,
            "gap_mae_seconds": sum(
                abs(predicted[d]["mean_gap_seconds"] - truth[d]["gap_seconds"]) for d in truth
            )
            / count,
        },
    }


def evaluate_replay(document):
    if document["schema_version"] != 1:
        raise ValueError("Replay schema_version must be 1")
    provenance = document["provenance"]
    if provenance["kind"] not in {"synthetic", "observed"}:
        raise ValueError("Provenance kind must be synthetic or observed")
    for key in ("source", "uri", "processing"):
        named(provenance[key], f"provenance.{key}")
    timestamp(provenance["acquired_at"], "provenance.acquired_at")
    splits = document["splits"]
    if timestamp(splits["training_end_at"], "training_end_at") >= timestamp(
        splits["holdout_start_at"], "holdout_start_at"
    ):
        raise ValueError("Training cutoff must precede holdout start")
    cases = document["cases"]
    if not cases or len(cases) > 100:
        raise ValueError("Provide 1..100 decision cases per bounded replay batch")
    if not all(isinstance(case, dict) for case in cases):
        raise ValueError("Each replay case must be an object")
    if len({named(c["case_id"], "case_id") for c in cases}) != len(cases):
        raise ValueError("Case identifiers must be unique")
    budget = document.get("max_total_rollouts", 10000)
    positive_int(budget, "max_total_rollouts")
    rollouts = 0
    results = []
    for case in cases:
        result = {"case_id": case["case_id"], "partition": case.get("partition")}
        results.append(result)
        try:
            planning = frozen_decision(case["decision"], case["partition"], splits)
            grid = planning["candidates"]
            stops = grid.get("max_stops", 1)
            nonnegative_int(stops, "max_stops")
            if stops > 2:
                raise ValueError("Replay supports at most two future stops")
            count = sum(
                comb(len(grid["pit_laps"]), k) * len(grid["compounds"]) ** k
                for k in range(min(stops, len(grid["pit_laps"])) + 1)
            )
            if rollouts + count * len(planning["scenarios"]) > budget:
                result.update(status="budget_exhausted", reason="Next case exceeds batch budget")
                continue
            # This call is completed BEFORE any access to the independent outcome.
            report = plan_from_document(planning)
            rollouts += report["search"]["rollouts_executed"]
            result["decision_input_sha256"] = hashlib.sha256(
                json.dumps(planning, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            result["search"] = report["search"]
            result["inventory_scope"] = report["inventory_scope"]
            if not report["ranking"]:
                result.update(
                    status="no_feasible_candidate", failures=report["rejected_candidates"]
                )
                continue
            selected = {
                "position": report["ranking"][0],
                "elapsed_time": min(
                    report["ranking"],
                    key=lambda r: (r["expected_elapsed_seconds"], len(r["stops"]), r["label"]),
                ),
                "stay_out": next((r for r in report["ranking"] if not r["stops"]), None),
            }
            result["strategies"] = {
                key: {
                    "label": row["label"],
                    "stops": row["stops"],
                    "simulated_expected_finish_position": row["expected_finish_position"],
                    "simulated_expected_elapsed_seconds": row["expected_elapsed_seconds"],
                    "evaluation": {"status": "outcome_unavailable", "metrics": None},
                }
                if row
                else {
                    "label": None,
                    "evaluation": {
                        "status": "infeasible_baseline",
                        "metrics": None,
                    },
                }
                for key, row in selected.items()
            }
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            result.update(status="decision_rejected", reason=f"{type(exc).__name__}: {exc}")
            continue
        try:
            truth = observed_next_lap(case["outcome"], case["decision"], planning)
            for key, row in selected.items():
                if row:
                    result["strategies"][key]["evaluation"] = forecast_error(
                        row, truth, case["outcome"]
                    )
            result["status"] = "outcome_valid"
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            result.update(status="outcome_rejected", reason=f"{type(exc).__name__}: {exc}")
    coverage = {}
    for partition in ("development", "holdout"):
        part = [r for r in results if r["partition"] == partition]
        methods = {}
        for method in ("position", "elapsed_time", "stay_out"):
            evaluations = [r["strategies"][method]["evaluation"] for r in part if "strategies" in r]
            metrics = [e["metrics"] for e in evaluations if e["metrics"] is not None]
            drivers = sum(m["driver_count"] for m in metrics)
            methods[method] = {
                "evaluated_cases": len(metrics),
                "status_counts": {
                    status: sum(e["status"] == status for e in evaluations)
                    for status in sorted({e["status"] for e in evaluations})
                },
                "action_mismatches": sum(e["status"] == "action_mismatch" for e in evaluations),
                "evaluated_driver_observations": drivers,
                "position_mae": sum(m["position_mae"] * m["driver_count"] for m in metrics)
                / drivers
                if drivers
                else None,
                "gap_mae_seconds": sum(m["gap_mae_seconds"] * m["driver_count"] for m in metrics)
                / drivers
                if drivers
                else None,
            }
        paired = [
            r
            for r in part
            if "strategies" in r
            and all(
                r["strategies"][m]["evaluation"]["metrics"] is not None
                for m in ("position", "elapsed_time")
            )
        ]
        paired_drivers = sum(
            r["strategies"]["position"]["evaluation"]["metrics"]["driver_count"] for r in paired
        )
        differences = {
            metric: sum(
                (
                    r["strategies"]["position"]["evaluation"]["metrics"][metric]
                    - r["strategies"]["elapsed_time"]["evaluation"]["metrics"][metric]
                )
                * r["strategies"]["position"]["evaluation"]["metrics"]["driver_count"]
                for r in paired
            )
            / paired_drivers
            if paired_drivers
            else None
            for metric in ("position_mae", "gap_mae_seconds")
        }
        coverage[partition] = {
            "requested_cases": len(part),
            "methods": methods,
            "paired_position_minus_elapsed_time": {
                "cases": len(paired),
                "driver_observations": paired_drivers,
                "error_differences": differences,
                "meaning": "Same cases and observed actions only; not causal strategy gains",
            },
        }
    return {
        "schema_version": 1,
        "provenance": provenance,
        "splits": splits,
        "claim": "Next-lap observational prediction check; no causal strategy-gain estimate",
        "source_status": "synthetic_fixture"
        if provenance["kind"] == "synthetic"
        else "user_supplied_observed_data_not_independently_verified",
        "baseline": "Same feasible candidate grid, minimum simulated elapsed time; plus stay-out",
        "weight_interpretation": "User-supplied scenario weights, not calibrated probabilities",
        "coverage": coverage,
        "cases": results,
        "case_status_counts": {
            status: sum(r["status"] == status for r in results)
            for status in sorted({r["status"] for r in results})
        },
        "search": {"rollouts_executed": rollouts, "max_total_rollouts": budget},
        "rejected_cases": sum(
            r["status"] in {"decision_rejected", "outcome_rejected"} for r in results
        ),
        "limits": [
            "Complete same-lap active fields; no missing-field imputation or retirements",
            "Only immediate next-lap error, conditional on full-field pit-action agreement",
            "Method coverage may differ: aggregate errors are not a paired strategy comparison",
            "Later outcomes do not enter planning; user-supplied timestamps still require audit",
            "Input uses normalized cache exports, not automatic reconstruction from raw FastF1",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline timestamped next-lap replay evaluation")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.expanduser()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output directory must be empty")
        raw = args.input.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        report = evaluate_replay(document)
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "replay.json", report)
        write_json(
            output / "manifest.json",
            {
                "versions": _versions(),
                "input_sha256": hashlib.sha256(raw).hexdigest(),
                "input": document,
            },
        )
        lines = [
            "# Next-lap replay evaluation",
            "",
            report["claim"],
            report["source_status"],
            "",
            "| Case | Partition | Status |",
            "|---|---|---|",
        ]
        lines += [f"| {r['case_id']} | {r['partition']} | {r['status']} |" for r in report["cases"]]
        lines += [
            "",
            "## Coverage and prediction error",
            "",
            "Errors concern the next observed lap only, conditional on all cars' pit actions "
            "matching. Empty metrics are unmeasured, not zero.",
            "",
            "| Partition | Method | Cases scored | Action mismatches | Rank MAE | Gap MAE (s) |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for partition, coverage in report["coverage"].items():
            for method, metrics in coverage["methods"].items():
                rank = metrics["position_mae"]
                gap = metrics["gap_mae_seconds"]
                rank_text = f"{rank:.4f}" if rank is not None else "unmeasured"
                gap_text = f"{gap:.4f}" if gap is not None else "unmeasured"
                lines.append(
                    f"| {partition} | {method} | {metrics['evaluated_cases']} | "
                    f"{metrics['action_mismatches']} | "
                    f"{rank_text} | {gap_text} |"
                )
        for partition, coverage in report["coverage"].items():
            paired = coverage["paired_position_minus_elapsed_time"]["cases"]
            lines += ["", f"{partition}: {paired} common scored cases for paired comparison.", ""]
        failures = [r for r in report["cases"] if r.get("reason")]
        if failures:
            lines += ["## Unscored case reasons", ""]
            lines += [f"- {r['case_id']}: {r['reason']}" for r in failures]
        lines += ["", "Coverage, per-strategy errors and failure reasons: replay.json", ""]
        lines += [f"- {limit}" for limit in report["limits"]]
        (output / "replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        scored = sum(
            p["methods"]["position"]["evaluated_cases"] for p in report["coverage"].values()
        )
        print(f"{report['source_status']}: {len(report['cases'])} cases; position scored: {scored}")
        print(report["claim"])
        incomplete = any(r["status"] != "outcome_valid" for r in report["cases"])
        return 0 if scored and not incomplete else 2
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
