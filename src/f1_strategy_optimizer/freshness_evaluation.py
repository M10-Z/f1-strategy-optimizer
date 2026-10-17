"""New additive scoring; original frozen forecasts/reports are never rewritten."""

import statistics
from collections import Counter
from datetime import timedelta

from .event_replay import dt, evaluate_frozen
from .prefix_quality import assess_prefix


def event_end_proxy(archive):
    ends = [
        dt(r["date_start"]) + timedelta(seconds=r["lap_duration"])
        for r in archive["laps"]
        if r.get("date_start") and r.get("lap_duration") and r["lap_duration"] > 0
    ]
    return max(ends).isoformat() if ends else None


def evaluate_quality(frozen, context, archive, baseline=None):
    # The predictor is called before any target or event-end audit is read here.
    quality = assess_prefix(frozen, context)
    baseline = baseline or evaluate_frozen(frozen, archive)
    end = event_end_proxy(archive)
    after = end is not None and dt(frozen["cutoff"]) > dt(end)
    drivers = []
    for old in baseline["drivers"]:
        candidate = quality["drivers"][old["driver_id"]]["candidate"]
        reason = old["lap"]["reason"]
        if after:
            category = "not_applicable_post_event_proxy"
        elif reason in {"target_missing_no_retirement_inference", "target_duration_unknown"}:
            category = "target_data_missing"
        elif reason == "target_already_started":
            category = "publication_boundary_rejection"
        elif reason == "insufficient_prefix_laps":
            category = "prefix_data_missing"
        elif candidate["value_seconds"] is None:
            category = "candidate_abstention"
        else:
            category = "scored"
        scored = category == "scored"
        gap_reason = old["gap"]["reason"]
        gap_category = (
            "not_applicable_post_event_proxy"
            if after
            else "scored"
            if old["gap"]["errors"]
            else "prefix_missing_or_stale"
            if gap_reason == "insufficient_or_stale_numeric_interval_prefix"
            else "target_data_missing_or_stale"
        )
        drivers.append(
            {
                "driver_id": old["driver_id"],
                "lap_category": category,
                "candidate_reason": candidate["reason"],
                "baseline_reason": reason,
                "target_lap": candidate["target_lap"],
                "prediction": candidate["value_seconds"],
                "candidate_abs_error": abs(candidate["value_seconds"] - old["lap"]["actual"])
                if scored
                else None,
                "baseline_abs_error_same_target": old["lap"]["errors"]["prefix_median"]
                if scored
                else None,
                "gap_category": gap_category,
                "gap_reason": gap_reason,
                "gap_abs_error": old["gap"]["errors"]["persistence"]
                if gap_category == "scored"
                else None,
            }
        )
    return {
        "decision_sha256": frozen["decision_sha256"],
        "cutoff": frozen["cutoff"],
        "posthoc_event_end_proxy": end,
        "drivers": drivers,
        "applicability_notice": "Posthoc last-completion proxy; not a live signal or feature",
    }


def summarize_quality(evaluations, thresholds=None):
    rows = [r for e in evaluations for r in e["drivers"]]
    categories = Counter(r["lap_category"] for r in rows)
    paired = [r for r in rows if r["lap_category"] == "scored"]
    applicable = len(rows) - categories["not_applicable_post_event_proxy"]
    candidate = statistics.mean(r["candidate_abs_error"] for r in paired) if paired else None
    baseline = (
        statistics.mean(r["baseline_abs_error_same_target"] for r in paired) if paired else None
    )
    ratio = candidate / baseline if baseline and candidate is not None else None
    coverage = len(paired) / applicable if applicable else None
    result = {
        "fixed_slots": len(rows),
        "applicable_slots": applicable,
        "categories": dict(categories),
        "abstention_reasons": dict(
            Counter(
                r["candidate_reason"] for r in rows if r["lap_category"] == "candidate_abstention"
            )
        ),
        "paired_scored": len(paired),
        "candidate_mae_seconds": candidate,
        "baseline_paired_mae_seconds": baseline,
        "paired_mae_ratio": ratio,
        "candidate_scored_fraction_applicable": coverage,
        "candidate_scored_fraction_original_denominator": len(paired) / len(rows) if rows else None,
        "gap_categories": dict(Counter(r["gap_category"] for r in rows)),
        "gap_mae_seconds": statistics.mean(
            r["gap_abs_error"] for r in rows if r["gap_abs_error"] is not None
        )
        if any(r["gap_abs_error"] is not None for r in rows)
        else None,
        "classification": "Failures never count as zero error; all exclusions retained",
        "claim": "Conditional observation forecast; selective coverage, no causal benefit claim",
    }
    if thresholds:
        result["threshold_checks"] = {
            "mae_ratio": ratio is not None and ratio <= thresholds["paired_lap_mae_ratio_at_most"],
            "coverage": coverage is not None
            and coverage >= thresholds["candidate_scored_fraction_of_applicable_slots_at_least"],
            "paired_count": len(paired) >= thresholds["paired_scored_targets_at_least"],
        }
    return result
