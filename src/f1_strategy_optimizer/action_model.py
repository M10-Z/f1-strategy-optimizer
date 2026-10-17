"""Finite v2 candidates. Prediction accepts frozen prefixes, never archive outcomes."""

import statistics

from .event_replay import digest, dt, verify_frozen
from .prefix_quality import assess_prefix

CANDIDATES = ("guarded_last", "shrunk_local_trend")
POLICY = {
    "max_age_seconds": 180,
    "window": 5,
    "slope_cap": 1.0,
    "shrink_pseudocount": 3,
    "max_adjustment_seconds": 3.0,
}


def _interrupted(messages, start, end):
    active = False
    for row in messages:
        if dt(row["date"]) > dt(end):
            break
        if dt(row["date"]) >= dt(start) and active:
            return True
        text = (row.get("message") or "").upper().strip()
        if text in {"SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR DEPLOYED"} or (
            row.get("scope") == "Track" and row.get("flag") == "RED"
        ):
            active = True
            if dt(row["date"]) >= dt(start):
                return True
        elif text == "TRACK CLEAR" or (row.get("scope") == "Track" and row.get("flag") == "GREEN"):
            active = False
    return active


def completed_pit_residuals(cars, cutoff, messages=()):
    """Past completed in/out pair residuals; not causal pit-lane loss estimates."""
    result = []
    for car in cars:
        history = car["completed_lap_history"]
        by_lap = {x["lap_number"]: x for x in history}
        known_in = {x["lap_number"] - 1 for x in history if x["is_pit_out_lap"] is True}
        for out in history:
            if out["is_pit_out_lap"] is not True:
                continue
            n = out["lap_number"]
            before = [
                x
                for x in history
                if 1 < x["lap_number"] < n - 1
                and x["is_pit_out_lap"] is False
                and x["lap_number"] not in known_in
            ][-3:]
            entry = by_lap.get(n - 1)
            if entry is None or len(before) < 3:
                continue
            if _interrupted(messages, before[0]["start_at"], out["completion_at"]):
                continue
            if dt(out["assumed_available_at"]) > dt(cutoff):
                raise ValueError("Future pit pair")
            # Interrupted / unstable pre-stop pace is not a clean training comparison.
            if max(x["lap_duration"] for x in before) - min(x["lap_duration"] for x in before) > 4:
                continue
            base = statistics.median(x["lap_duration"] for x in before)
            result.append(
                {
                    "driver_id": car["id"],
                    "inlap": n - 1,
                    "outlap": n,
                    "in_residual": entry["lap_duration"] - base,
                    "out_residual": out["lap_duration"] - base,
                    "available_at": out["assumed_available_at"],
                }
            )
    return result


def fit_pit_prior(records, training_events):
    """Call only on the training side of a whole-event development fold."""
    if any("belg" in e.lower() for e in training_events):
        raise ValueError("Belgium is sealed and cannot train a prior")
    return {
        "in_seconds": max(0.0, statistics.median(x["in_residual"] for x in records))
        if records
        else None,
        "out_seconds": max(0.0, statistics.median(x["out_residual"] for x in records))
        if records
        else None,
        "sample_count": len(records),
        "training_events": list(training_events),
        "meaning": "Completed-pair observational residual prior, not causal pit loss",
    }


def predict(frozen, context, candidate, prior):
    verify_frozen(frozen)
    if candidate not in CANDIDATES:
        raise ValueError("Candidate outside registered finite budget")
    quality = assess_prefix(frozen, context)
    cutoff = frozen["cutoff"]
    cars = frozen["state"]["cars"]
    past_pits = completed_pit_residuals(cars, cutoff, frozen["state"]["visible_race_control"])
    # Each driver/stop counted once; only already completed pairs from this event.
    loss = (
        fit_pit_prior(past_pits, ["visible_current_event_prefix"]) if len(past_pits) >= 3 else prior
    )
    output = []
    for car in cars:
        q = quality["drivers"][car["id"]]
        history = car["completed_lap_history"]
        current = car["last_started_lap"]["value"]
        target = current + 1 if current is not None else None
        known_in = {x["lap_number"] - 1 for x in history if x["is_pit_out_lap"] is True}
        clean = [
            x
            for x in history
            if x["lap_number"] > 1
            and x["is_pit_out_lap"] is False
            and x["lap_number"] not in known_in
            and not _interrupted(
                frozen["state"]["visible_race_control"], x["start_at"], x["completion_at"]
            )
        ]
        stint_at = car["compound"].get("event_at")
        boundaries_at = [
            x
            for x in [
                stint_at,
                quality["weather"]["rain_signal_transition_at"],
                quality["race_control"]["event_at"],
            ]
            if x
        ]
        segment_at = max(boundaries_at, key=dt, default=None)
        same = [x for x in clean if segment_at and dt(x["start_at"]) >= dt(segment_at)]
        pool = (same or clean)[-POLICY["window"] :]
        fallback = "same_visible_segment" if same else "pre_transition_unadjusted_fallback"
        reason = None
        if not pool or target is None:
            reason = "missing_prefix"
        elif (dt(cutoff) - dt(pool[-1]["completion_at"])).total_seconds() > 180:
            reason = "stale_clean_lap"
        elif quality["race_control"]["last_reported_value"] in {"SC", "VSC", "RED"}:
            reason = "control_active_or_clearance_unconfirmed"
        pace, slope = None, 0.0
        if reason is None:
            pace = pool[-1]["lap_duration"]
            if candidate == "shrunk_local_trend" and len(same) >= 3:
                slopes = [
                    (b["lap_duration"] - a["lap_duration"]) / (b["lap_number"] - a["lap_number"])
                    for i, a in enumerate(pool)
                    for b in pool[i + 1 :]
                ]
                raw = statistics.median(slopes)
                slope = max(-1.0, min(1.0, raw)) * len(pool) / (len(pool) + 3)
                anchor = statistics.mean(x["lap_duration"] for x in pool[-2:])
                lap = statistics.mean(x["lap_number"] for x in pool[-2:])
                pace = anchor + max(-3.0, min(3.0, slope * (target - lap)))
            elif candidate == "shrunk_local_trend":
                fallback += ":under_three_samples_last_lap"
        boundaries = q["candidate"]["segment_boundaries"]
        boundary = max((x["event_at"] for x in boundaries), key=dt, default=None)
        outlaps = [x for x in history if x["is_pit_out_lap"] is True]
        latest_out = outlaps[-1] if outlaps else None
        # Exact first lap after the observed completed outlap is kept, never retargeted.
        post_target = latest_out["lap_number"] + 1 if latest_out else None
        post_reason = "no_prefix_confirmed_completed_outlap"
        if latest_out:
            post_reason = (
                "immediate_post_outlap_target_already_started" if current >= post_target else reason
            )
        planned = None
        if pace is not None and loss["in_seconds"] is not None and loss["out_seconds"] is not None:
            planned = {
                "inlap_seconds": pace + loss["in_seconds"],
                "outlap_seconds": pace + loss["out_seconds"],
                "two_lap_seconds": 2 * pace + loss["in_seconds"] + loss["out_seconds"],
            }
        output.append(
            {
                "driver_id": car["id"],
                "driver_number": car["driver_number"],
                "target_lap": target,
                "stay_seconds": pace,
                "reason": reason,
                "conditionality": "Assume no new pit action/control/weather regime change",
                "fallback": fallback,
                "slope_seconds_per_lap": slope,
                "sample_laps": [x["lap_number"] for x in pool],
                "sample_available_at": [x["assumed_available_at"] for x in pool],
                "latest_boundary": boundary,
                "rainfall": (quality["weather"].get("last_reported_value") or {}).get("rainfall"),
                "estimated_completed_tyre_age": car["estimated_completed_tyre_age"]["value"],
                "planned_pit": {
                    "assumed_decided_at": cutoff,
                    "effective_boundary": "pit entry during target lap; timestamp unknown",
                    "inlap": target,
                    "outlap": target + 1 if target else None,
                    "prediction": planned,
                    "loss_prior": loss,
                    "status": "explicit_hypothesis_not_observed_action",
                },
                "post_completed_pit": {
                    "effective_at_upper_bound": latest_out["completion_at"] if latest_out else None,
                    "evidence_available_at": latest_out["assumed_available_at"]
                    if latest_out
                    else None,
                    "target_lap": post_target,
                    "prediction": pace if post_reason is None else None,
                    "reason": post_reason,
                },
                "unconditional_proxy_warning": (
                    "Stay estimate scored on ALL fixed targets too; future actions unknown"
                ),
            }
        )
    result = {
        "schema_version": 1,
        "candidate": candidate,
        "policy": POLICY,
        "decision_sha256": frozen["decision_sha256"],
        "cutoff": cutoff,
        "prior_sha256": digest(prior),
        "drivers": output,
        "verified_publication_time": False,
        "surface_state": "UNKNOWN",
        "pit_exit_clock": "Not established; completed outlap is conservative completion proof",
    }
    result["sha256"] = digest(result)
    return result


def confirm_action(action, cutoff):
    """Validate an explicit plan before evaluating any action-conditional output."""
    if action["kind"] not in {"stay", "planned_pit", "post_completed_pit"}:
        raise ValueError("Unknown action")
    if dt(action["decided_at"]) > dt(cutoff):
        raise ValueError("Future action decision")
    effective = action.get("effective_at")
    if action["kind"] == "post_completed_pit" and (effective is None or dt(effective) > dt(cutoff)):
        raise ValueError("Completed pit requires past effective-time evidence")
    if action["kind"] == "planned_pit" and effective and dt(effective) < dt(action["decided_at"]):
        raise ValueError("Plan cannot be effective before decision")
    return dict(action)
