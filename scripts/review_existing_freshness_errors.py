"""Describe saved evaluation errors only; no fitting, prediction or data acquisition."""

import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "output/freshness-delivery-review"
RECEIPTS = {}


def read(path):
    raw = path.read_bytes()
    RECEIPTS[str(path)] = hashlib.sha256(raw).hexdigest()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def summarize(rows):
    paired = [r for r in rows if r["lap_category"] == "scored"]
    errors = [r["candidate_abs_error"] for r in paired]
    baseline = [r["baseline_abs_error_same_target"] for r in paired]
    applicable = sum(r["lap_category"] != "not_applicable_post_event_proxy" for r in rows)
    total_error = sum(errors)
    return {
        "slots": len(rows),
        "applicable": applicable,
        "categories": dict(Counter(r["lap_category"] for r in rows)),
        "paired": len(paired),
        "coverage_applicable": len(paired) / applicable if applicable else None,
        "candidate_mae": statistics.mean(errors) if errors else None,
        "baseline_paired_mae": statistics.mean(baseline) if baseline else None,
        "candidate_median_ae": quantile(errors, 0.5),
        "candidate_p90_ae": quantile(errors, 0.9),
        "candidate_p95_ae": quantile(errors, 0.95),
        "candidate_max_ae": max(errors) if errors else None,
        "sum_absolute_error": total_error,
        "over_five_seconds_count": sum(v > 5 for v in errors),
        "over_five_seconds_error_share": sum(v for v in errors if v > 5) / total_error
        if total_error
        else None,
        "signed_bias_prediction_minus_actual": statistics.mean(r["signed_error"] for r in paired)
        if paired
        else None,
    }


def prefix_features(frozen, context, car):
    cutoff = dt(frozen["cutoff"])
    rain_boundary, previous_rain = None, None
    for row in context["weather_history"]:
        assert dt(row["date"]) <= cutoff
        rain = row.get("rainfall")
        if rain in (0, 1) and rain is not None:
            if previous_rain is not None and rain != previous_rain:
                rain_boundary = row["date"]
            previous_rain = rain
    control, recovery = "UNKNOWN", None
    for row in frozen["state"]["visible_race_control"]:
        assert dt(row["date"]) <= cutoff
        text = (row.get("message") or "").upper().strip()
        next_state = None
        if text in {"SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR DEPLOYED"}:
            next_state = "VSC" if text.startswith("VIRTUAL") else "SC"
        elif text == "TRACK CLEAR" and control in {"SC", "VSC", "RED"}:
            next_state = "GREEN"
        elif row.get("scope") == "Track" and row.get("flag") in {"RED", "GREEN"}:
            next_state = row["flag"]
        if next_state:
            if control in {"SC", "VSC", "RED"} and next_state == "GREEN":
                recovery = row["date"]
            control = next_state
    stint_at = car["compound"].get("event_at")
    outlaps = [x for x in car["completed_lap_history"] if x["is_pit_out_lap"] is True]
    boundary_events = [stint_at] if stint_at else []
    boundary_events += [x["completion_at"] for x in outlaps]
    latest = max(map(dt, boundary_events), default=None)
    if control in {"SC", "VSC", "RED"}:
        scenario = "active_control_or_clearance_unconfirmed"
    elif recovery and (cutoff - dt(recovery)).total_seconds() <= 600:
        scenario = "within_10min_explicit_control_recovery"
    elif rain_boundary and (cutoff - dt(rain_boundary)).total_seconds() <= 600:
        scenario = "within_10min_rain_signal_change"
    elif previous_rain == 1:
        scenario = "rain_signal_on_no_recent_change"
    elif latest and (cutoff - latest).total_seconds() <= 600:
        scenario = "within_10min_visible_stint_or_completed_outlap"
    else:
        scenario = "other_prefix_no_recent_boundary_not_verified_green_or_dry"
    age = car["estimated_completed_tyre_age"].get("value")
    age_bin = (
        "unknown"
        if age is None
        else "0_to_5"
        if age <= 5
        else "6_to_15"
        if age <= 15
        else "16_plus"
    )
    return {
        "prefix_scenario": scenario,
        "prefix_tyre_age_bin": age_bin,
        "prefix_compound": car["compound"].get("value") or "unknown",
        "last_explicit_control": control,
        "prefix_rain_signal": previous_rain,
    }


def main():
    all_rows, event_summaries = [], {}
    for event in ["bahrain", "monaco", "british", "italian", "belgian"]:
        reserved = event == "belgian"
        root = REPO / (
            "output/freshness-belgian-validation" if reserved else "output/freshness-development"
        )
        if reserved:
            report = read(root / "evaluation.json")
            evaluations, baselines = report["evaluations"], report["baseline_evaluations"]
            frozen = read(root / "decisions.json")
            contexts = read(root / "contexts.json")
            baseline_map = {x["decision_sha256"]: x for x in baselines}
            expected = report["candidate_summary"]
        else:
            evaluations = read(root / f"{event}-quality-evaluation.json")
            frozen = read(
                root / ("decisions.json.gz" if event == "bahrain" else f"{event}-decisions.json.gz")
            )
            contexts = read(root / f"{event}-prefix-context.json.gz")
            baseline_map = read(root / f"{event}-quality-reveals.json.gz")
            expected = read(root / "development-summary.json")[event]
        frozen_map = {x["decision_sha256"]: x for x in frozen}
        raw = (
            REPO.parent
            / "real-data"
            / ("freshness-2024-belgian" if reserved else f"holdout-2024-{event}")
        )
        laps_path, pits_path = raw / "openf1-laps.body", raw / "openf1-pit.body"
        lap_map = (
            {(x["driver_number"], x["lap_number"]): x for x in read(laps_path)}
            if laps_path.exists()
            else {}
        )
        pit_set = (
            {(x["driver_number"], x["lap_number"]) for x in read(pits_path)}
            if pits_path.exists()
            else set()
        )
        event_rows = []
        for evaluation in evaluations:
            key = evaluation["decision_sha256"]
            f = frozen_map[key]
            cars = {x["id"]: x for x in f["state"]["cars"]}
            bases = {x["driver_id"]: x for x in baseline_map[key]["drivers"]}
            for row in evaluation["drivers"]:
                car, base = cars[row["driver_id"]], bases[row["driver_id"]]
                target = (car["driver_number"], row["target_lap"])
                raw_lap = lap_map.get(target)
                # Future pit/outlap labels explain errors only. They never feed a predictor.
                audit = (
                    "target_outlap"
                    if raw_lap and raw_lap.get("is_pit_out_lap") is True
                    else "target_pit_record_lap"
                    if target in pit_set
                    else "target_without_recorded_pit_or_outlap"
                    if raw_lap
                    else "audit_unavailable"
                )
                copied = {
                    **row,
                    "event": event,
                    "cutoff": f["cutoff"],
                    "posthoc_target_pit_audit": audit,
                    **prefix_features(f, contexts[key], car),
                    "signed_error": row["prediction"] - base["lap"]["actual"]
                    if row["lap_category"] == "scored"
                    else None,
                }
                event_rows.append(copied)
        stats = summarize(event_rows)
        assert stats["paired"] == expected["paired_scored"]
        assert math.isclose(
            stats["candidate_mae"], expected["candidate_mae_seconds"], abs_tol=1e-12
        )
        assert math.isclose(
            stats["baseline_paired_mae"], expected["baseline_paired_mae_seconds"], abs_tol=1e-12
        )
        dimensions = {}
        for dimension in [
            "prefix_scenario",
            "prefix_tyre_age_bin",
            "prefix_compound",
            "posthoc_target_pit_audit",
        ]:
            groups = defaultdict(list)
            for row in event_rows:
                groups[str(row[dimension])].append(row)
            dimensions[dimension] = {k: summarize(v) for k, v in sorted(groups.items())}
        scored = [x for x in event_rows if x["lap_category"] == "scored"]
        event_summaries[event] = {
            "role": "one_completed_independent_test_result_no_retest"
            if reserved
            else "development_observed",
            "overall": stats,
            "dimensions": dimensions,
            "worst_ten": sorted(scored, key=lambda x: x["candidate_abs_error"], reverse=True)[:10],
        }
        all_rows.extend(event_rows)
    # Prove this script left every input artifact byte-for-byte unchanged.
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in RECEIPTS.items())
    result = {
        "scope": (
            "Posthoc descriptive analysis of saved predictions/errors; "
            "no fits, prediction reruns, network or new holdout"
        ),
        "scenario_definitions": (
            "Mutually exclusive prefix scenarios, priority control active, recovery <=600s, "
            "rain change <=600s, rain on, stint/outlap boundary <=600s, other. "
            "Other is not verified green/dry. Time bins selected posthoc for diagnosis, "
            "not preregistered performance claims."
        ),
        "posthoc_label_restriction": (
            "Raw target pit/outlap labels are explanatory audits only, "
            "never available model inputs. No claim of causal attribution."
        ),
        "uncertainty": (
            "Repeated drivers/cutoffs from the same race are correlated; "
            "no independent-sample confidence claims or generalized performance claim."
        ),
        "inputs_unchanged_sha256": RECEIPTS,
        "events": event_summaries,
        "rows": all_rows,
    }
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "existing-scenario-errors.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    for event, entry in event_summaries.items():
        print(event, json.dumps(entry["overall"]))
        for dimension in ["prefix_scenario", "posthoc_target_pit_audit"]:
            print(dimension, json.dumps(entry["dimensions"][dimension]))


if __name__ == "__main__":
    main()
