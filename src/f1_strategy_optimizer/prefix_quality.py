"""Prefix-only freshness and segment diagnostics; never consumes outcomes or audits."""

import hashlib
import statistics
from dataclasses import asdict
from pathlib import Path

from .event_replay import EventTimePolicy, digest, dt, valid_gap, verify_frozen, visible_events

POLICY = {
    "lap_max_age_seconds": 180,
    "control_max_age_seconds": 180,
    "segment_window": 3,
    "min_segment_samples": 3,
    "max_segment_range_seconds": 4.0,
}


def make_context(archive, frozen):
    """Store only visible weather reports and each driver's last visible gap report."""
    verify_frozen(frozen)
    at = dt(frozen["cutoff"])
    policy = EventTimePolicy(**frozen["config"])
    weather = visible_events(archive.get("weather", []), at, policy)
    intervals = visible_events(archive.get("intervals", []), at, policy)
    last = {}
    for row in intervals:
        last[str(row["driver_number"])] = {k: row.get(k) for k in ("date", "gap_to_leader")}
    result = {
        "decision_sha256": frozen["decision_sha256"],
        "weather_history": [{k: r.get(k) for k in ("date", "rainfall")} for r in weather],
        "last_gap_reports": last,
        "semantics": "event timestamps plus assumed delay; publication times unverified",
    }
    result["context_sha256"] = digest(result)
    return result


def _check_context(context, frozen, policy):
    if context is None:
        return
    content = {k: v for k, v in context.items() if k != "context_sha256"}
    if digest(content) != context.get("context_sha256"):
        raise ValueError("Prefix context hash mismatch")
    if context["decision_sha256"] != frozen["decision_sha256"]:
        raise ValueError("Prefix context belongs to another frozen decision")
    for row in context["weather_history"] + list(context["last_gap_reports"].values()):
        if dt(row["date"]) + policy.delay > dt(frozen["cutoff"]):
            raise ValueError("Future environment report in prefix context")


def _fresh(event_at, cutoff, threshold, source, value=None):
    age = (dt(cutoff) - dt(event_at)).total_seconds() if event_at else None
    return {
        "event_at": event_at,
        "age_seconds_at_cutoff": age,
        "max_age_seconds": threshold,
        "clock_source": source,
        "reliability": "missing"
        if age is None
        else "stale"
        if age > threshold
        else "event_time_only",
        "last_reported_value": value,
        "publication_time_verified": False,
    }


def _control(messages, cutoff):
    current, event, transition = "UNKNOWN", None, None
    for row in messages:
        text = (row.get("message") or "").strip().upper()
        next_state = None
        if text in {"SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR DEPLOYED"}:
            next_state = "VSC" if text.startswith("VIRTUAL") else "SC"
        elif text == "TRACK CLEAR" and current in {"SC", "VSC", "RED"}:
            next_state = "GREEN"
        elif row.get("scope") == "Track" and row.get("flag") in {"RED", "GREEN"}:
            next_state = row["flag"]
        if next_state is not None and next_state != current:
            current, event, transition = next_state, row["date"], row["date"]
    quality = _fresh(
        event,
        cutoff,
        POLICY["control_max_age_seconds"],
        "OpenF1.race_control explicit whole-track transition",
        current,
    )
    quality["usable_state"] = current if quality["reliability"] == "event_time_only" else "UNKNOWN"
    quality["rule"] = "No GREEN inference from silence, local flags, or SC/VSC ENDING"
    return quality, current, transition


def assess_prefix(frozen, context=None):
    verify_frozen(frozen)
    policy = EventTimePolicy(**frozen["config"])
    _check_context(context, frozen, policy)
    state, cutoff = frozen["state"], frozen["cutoff"]
    for message in state["visible_race_control"]:
        if dt(message["date"]) + policy.delay > dt(cutoff):
            raise ValueError("Future control message in frozen prefix")
    for car in state["cars"]:
        for lap in car["completed_lap_history"]:
            if dt(lap["assumed_available_at"]) > dt(cutoff):
                raise ValueError("Future completed lap in frozen prefix")
    control, active_control, control_boundary = _control(state["visible_race_control"], cutoff)
    weather = state["weather_observation"]
    weather_quality = _fresh(
        weather.get("event_at"),
        cutoff,
        policy.weather_max_age_seconds,
        "OpenF1.weather.date",
        weather.get("value"),
    )
    rain_boundary, previous_rain = None, None
    for row in (context or {}).get("weather_history", []):
        rain = row.get("rainfall")
        if rain in (0, 1) and rain is not None:
            if previous_rain is not None and rain != previous_rain:
                rain_boundary = row["date"]
            previous_rain = rain
    weather_quality["rain_signal_transition_at"] = rain_boundary
    weather_quality["surface_state"] = (
        "UNKNOWN: rainfall/zero rainfall does not establish wet/dry track"
    )
    forecasts = {r["driver_id"]: r for r in frozen["observation_forecasts"]}
    drivers = {}
    for car in state["cars"]:
        last_gap = (context or {}).get("last_gap_reports", {}).get(str(car["driver_number"]))
        gap_event = last_gap["date"] if last_gap else car["gap_seconds"].get("event_at")
        gap_value = last_gap.get("gap_to_leader") if last_gap else car["gap_seconds"].get("value")
        gap = _fresh(
            gap_event, cutoff, policy.interval_max_age_seconds, "OpenF1.intervals.date", gap_value
        )
        gap["numeric_usable"] = valid_gap(gap_value) and gap["reliability"] == "event_time_only"
        history = car["completed_lap_history"]
        lap_quality = _fresh(
            history[-1]["completion_at"] if history else None,
            cutoff,
            POLICY["lap_max_age_seconds"],
            "max(lap start + duration, corroborating next start)",
        )
        boundaries = []
        for kind, event in (
            ("visible_stint_start", car["compound"].get("event_at")),
            ("whole_track_control_transition", control_boundary),
            ("rain_signal_transition_not_surface_classification", rain_boundary),
        ):
            if event:
                boundaries.append({"kind": kind, "event_at": event})
        outlaps = [r for r in history if r["is_pit_out_lap"] is True]
        if outlaps:
            boundaries.append(
                {"kind": "completed_outlap", "event_at": outlaps[-1]["completion_at"]}
            )
        boundary = max((dt(b["event_at"]) for b in boundaries), default=None)
        pool = [
            r
            for r in history
            if r["lap_number"] > 1
            and r["is_pit_out_lap"] is False
            and (boundary is None or dt(r["start_at"]) >= boundary)
        ][-POLICY["segment_window"] :]
        spread = (
            max(r["lap_duration"] for r in pool) - min(r["lap_duration"] for r in pool)
            if pool
            else None
        )
        reason = None
        if lap_quality["reliability"] in {"missing", "stale"}:
            reason = "missing_or_stale_lap_evidence"
        elif active_control in {"SC", "VSC", "RED"}:
            reason = "control_active_or_clearance_unconfirmed"
        elif len(pool) < POLICY["min_segment_samples"]:
            reason = "segment_warmup_requires_three_completed_laps"
        elif (dt(cutoff) - dt(pool[-1]["completion_at"])).total_seconds() > POLICY[
            "lap_max_age_seconds"
        ]:
            reason = "stale_eligible_segment"
        elif spread > POLICY["max_segment_range_seconds"]:
            reason = "unstable_segment_range_exceeds_four_seconds"
        elif forecasts[car["id"]]["lap"]["target_lap"] is None:
            reason = "no_fixed_target_lap"
        values = [r["lap_duration"] for r in pool]
        drivers[car["id"]] = {
            "gap": gap,
            "lap": lap_quality,
            "candidate": {
                "method": "visible_segment_median_v1",
                "value_seconds": None if reason else statistics.median(values),
                "status": "abstained" if reason else "conditional_observation_forecast",
                "reason": reason,
                "target_lap": forecasts[car["id"]]["lap"]["target_lap"],
                "segment_boundaries": boundaries,
                "sample_laps": [r["lap_number"] for r in pool],
                "sample_completion_times": [r["completion_at"] for r in pool],
                "observed_range_seconds": spread,
                "range_is_not_confidence_interval": True,
            },
        }
    latest_events = [
        x["event_at"]
        for x in [weather_quality, control]
        + [v[k] for v in drivers.values() for k in ("gap", "lap")]
        if x["event_at"]
    ]
    return {
        "schema_version": 1,
        "decision_sha256": frozen["decision_sha256"],
        "cutoff": cutoff,
        "policy": POLICY,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "context_sha256": context.get("context_sha256") if context else None,
        "snapshot": _fresh(
            max(latest_events, key=dt) if latest_events else None,
            cutoff,
            180,
            "latest visible lap/gap/weather/control event; not all-car freshness",
        ),
        "weather": weather_quality,
        "race_control": control,
        "drivers": drivers,
        "availability_assumption": asdict(policy),
        "limitations": [
            "Historical event time plus assumed delay; publication time unverified",
            "No retirement inference, synchronized gaps, future pit actions or outcome audit input",
            "Rain/tyre transitions are proxies; wet/dry track state remains unknown",
            "Missing weather history disables rain-transition detection"
            if context is None
            else "Weather history is visible-prefix only",
            "Conditional lap-duration reference, not probability or strategy gain",
        ],
    }
