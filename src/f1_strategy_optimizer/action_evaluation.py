"""Post-freeze scoring of v2 all-target proxies and separately matched action branches."""

import statistics
from collections import Counter

from .event_replay import digest, dt
from .freshness_evaluation import event_end_proxy


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * fraction
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def distribution(values):
    return {
        "n": len(values),
        "mae": statistics.mean(values) if values else None,
        "median": percentile(values, 0.5),
        "p90": percentile(values, 0.9),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def score_prediction(prediction, frozen, v1, archive):
    saved = {k: v for k, v in prediction.items() if k != "sha256"}
    if (
        digest(saved) != prediction["sha256"]
        or prediction["decision_sha256"] != frozen["decision_sha256"]
    ):
        raise ValueError("Prediction freeze mismatch")
    laps = {(x["driver_number"], x["lap_number"]): x for x in archive["laps"]}
    baseline = {x["driver_id"]: x for x in frozen["observation_forecasts"]}
    after = dt(prediction["cutoff"]) > dt(event_end_proxy(archive))
    rows = []
    for row in prediction["drivers"]:
        target = laps.get((row["driver_number"], row["target_lap"]))
        following = laps.get((row["driver_number"], (row["target_lap"] or 0) + 1))
        old = baseline[row["driver_id"]]["default_prediction"]["lap"]["value_seconds"]
        old_v1 = v1["drivers"][row["driver_id"]]["candidate"]["value_seconds"]
        category = "scored"
        if after:
            category = "post_event_na"
        elif target is None or target.get("lap_duration") is None:
            category = "target_missing"
        elif dt(target["date_start"]) <= dt(prediction["cutoff"]):
            category = "target_already_started"
        elif row["stay_seconds"] is None:
            category = "prefix_abstention"
        actual = target.get("lap_duration") if target else None
        valid_target = category in {"scored", "prefix_abstention"}
        audit = "unknown"
        if target:
            audit = (
                "outlap"
                if target.get("is_pit_out_lap") is True
                else "inlap_before_outlap"
                if following and following.get("is_pit_out_lap") is True
                else "stay_no_recorded_pit"
                if target.get("is_pit_out_lap") is False
                else "unknown"
            )
        planned = row["planned_pit"]["prediction"]
        pit_actual = (
            actual + following["lap_duration"]
            if valid_target
            and audit == "inlap_before_outlap"
            and actual
            and following.get("lap_duration")
            else None
        )
        loss = row["planned_pit"]["loss_prior"]
        paired = category == "scored" and old is not None
        rows.append(
            {
                "driver_id": row["driver_id"],
                "cutoff": prediction["cutoff"],
                "target_lap": row["target_lap"],
                "category": category,
                "reason": row["reason"],
                "fallback": row["fallback"],
                "prefix_available": row["stay_seconds"] is not None,
                "latest_boundary": row["latest_boundary"],
                "rainfall": row["rainfall"],
                "tyre_age": row["estimated_completed_tyre_age"],
                "posthoc_action_audit": audit,
                "candidate_error": abs(row["stay_seconds"] - actual)
                if category == "scored"
                else None,
                "baseline_error": abs(old - actual) if valid_target and old is not None else None,
                "v1_error": abs(old_v1 - actual) if valid_target and old_v1 is not None else None,
                "paired": paired,
                "stay_action_matched": category == "scored" and audit == "stay_no_recorded_pit",
                "planned_pit_error": abs(planned["two_lap_seconds"] - pit_actual)
                if pit_actual and planned
                else None,
                "planned_pit_baseline_same_prior_error": abs(
                    2 * old + loss["in_seconds"] + loss["out_seconds"] - pit_actual
                )
                if pit_actual and planned and old is not None
                else None,
                "planned_pit_match": pit_actual is not None,
                "post_completed_pit_reason": row["post_completed_pit"]["reason"],
                "post_completed_pit_prediction_available": row["post_completed_pit"]["prediction"]
                is not None,
            }
        )
    return rows


def summarize(rows):
    categories = Counter(x["category"] for x in rows)
    applicable = len(rows) - categories["post_event_na"]
    paired = [x for x in rows if x["paired"]]
    waits, censored, runs, spans = [], 0, [], []
    drivers = sorted({x["driver_id"] for x in rows})
    for driver in drivers:
        seq = sorted(
            [x for x in rows if x["driver_id"] == driver and x["category"] != "post_event_na"],
            key=lambda x: dt(x["cutoff"]),
        )
        run = 0
        run_start = None
        seen_boundaries = set()
        for i, row in enumerate(seq):
            run = run + 1 if not row["prefix_available"] else 0
            if run == 1:
                run_start = dt(row["cutoff"])
            if run:
                spans.append((dt(row["cutoff"]) - run_start).total_seconds())
            runs.append(run)
            boundary = row["latest_boundary"]
            if not boundary or boundary in seen_boundaries:
                continue
            seen_boundaries.add(boundary)
            available = next(
                (x for x in seq[i:] if x["latest_boundary"] == boundary and x["prefix_available"]),
                None,
            )
            if available:
                waits.append((dt(available["cutoff"]) - dt(boundary)).total_seconds())
            else:
                censored += 1
    return {
        "fixed_slots": len(rows),
        "applicable_slots": applicable,
        "categories": dict(categories),
        "coverage": categories["scored"] / applicable if applicable else None,
        "v1_coverage": sum(x["v1_error"] is not None for x in rows) / applicable
        if applicable
        else None,
        "baseline_coverage": sum(x["baseline_error"] is not None for x in rows) / applicable
        if applicable
        else None,
        "all_scored": distribution(
            [x["candidate_error"] for x in rows if x["candidate_error"] is not None]
        ),
        "paired_candidate": distribution([x["candidate_error"] for x in paired]),
        "paired_baseline": distribution([x["baseline_error"] for x in paired]),
        "stay_action_matched": distribution(
            [x["candidate_error"] for x in rows if x["stay_action_matched"]]
        ),
        "planned_pit_matched": distribution(
            [x["planned_pit_error"] for x in rows if x["planned_pit_error"] is not None]
        ),
        "planned_pit_paired_candidate": distribution(
            [
                x["planned_pit_error"]
                for x in rows
                if x["planned_pit_baseline_same_prior_error"] is not None
            ]
        ),
        "planned_pit_paired_baseline_same_prior": distribution(
            [
                x["planned_pit_baseline_same_prior_error"]
                for x in rows
                if x["planned_pit_baseline_same_prior_error"] is not None
            ]
        ),
        "planned_pit_action_match_count": sum(x["planned_pit_match"] for x in rows),
        "post_pit_reasons": dict(Counter(x["post_completed_pit_reason"] for x in rows)),
        "abstention_reasons": dict(
            Counter(x["reason"] for x in rows if x["category"] == "prefix_abstention")
        ),
        "max_consecutive_sampled_abstentions": max(runs, default=0),
        "max_sampled_abstention_span_seconds": max(spans, default=0),
        "boundary_to_first_sampled_availability_seconds": distribution(waits),
        "boundary_wait_right_censored": censored,
        "wait_notice": "Sampled upper bounds, not exact continuous wait; Bahrain grid irregular",
        "future_action_conditioning": (
            "All branches frozen before matching; matched scores not unconditional "
            "accuracy or causal benefit"
        ),
    }
