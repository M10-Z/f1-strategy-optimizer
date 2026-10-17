"""Outcome-only error descriptions, never imported by decision construction."""

import hashlib
import statistics
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .replay import timestamp


def _dt(value):
    return timestamp(value, "diagnostic timestamp")


def _control_windows(messages):
    windows, active = [], None
    for row in sorted(messages, key=lambda r: _dt(r["date"])):
        text = row.get("message", "").upper()
        if text in {"VIRTUAL SAFETY CAR DEPLOYED", "SAFETY CAR DEPLOYED"}:
            active = {"kind": "VSC" if text.startswith("VIRTUAL") else "SC", "start": row["date"]}
        elif text == "TRACK CLEAR" and active:
            windows.append({**active, "end": row["date"]})
            active = None
    if active:
        windows.append({**active, "end": None})
    return windows


def _overlaps(start, end, windows):
    return any(
        _dt(w["start"]) < end and (w["end"] is None or _dt(w["end"]) > start) for w in windows
    )


def _metrics(rows):
    if not rows:
        return {"count": 0, "mae_seconds": None}
    return {
        "count": len(rows),
        "mae_seconds": {
            m: statistics.mean(r["errors"][m] for r in rows) for m in sorted(rows[0]["errors"])
        },
    }


def diagnose(archive, frozen, evaluations):
    """Group by observed outcomes only after all forecasts have been frozen.

    Labels are descriptive and may overlap. Absence of an identified event does
    not prove green track, no traffic, or an exact pit-entry boundary.
    """
    laps = {(r["driver_number"], r["lap_number"]): r for r in archive["laps"]}
    ids = {r["id"]: r["driver_number"] for r in archive["drivers"]}
    pits = {(ids[r["driverId"]], r["lap"]) for r in archive.get("pitstops", [])}
    windows = _control_windows(archive.get("race_control", []))
    lap_groups, gap_groups = defaultdict(list), defaultdict(list)
    identities, top_errors = {}, []
    for decision, evaluation in zip(frozen, evaluations):
        identities[decision["cutoff"]] = {
            "completed_lap_numbers": sorted(
                {
                    c["completed_laps"]["value"]
                    for c in decision["state"]["cars"]
                    if c["completed_laps"]["value"] is not None
                }
            ),
            "asynchronous_state": True,
        }
        at = _dt(decision["cutoff"])
        for row in evaluation["drivers"]:
            result = row["lap"]
            if result["errors"] is not None:
                key = (row["driver_number"], result["target_lap"])
                raw = laps[key]
                start = _dt(raw["date_start"])
                end = start + timedelta(seconds=raw["lap_duration"])
                pit_related = key in pits or raw.get("is_pit_out_lap") is True
                lap_groups[
                    "pit_related" if pit_related else "not_identified_as_pit_related"
                ].append(result)
                control = _overlaps(start, end, windows)
                lap_groups[
                    "control_window_overlap" if control else "no_identified_control_overlap"
                ].append(result)
                top_errors.append(
                    {
                        "cutoff": decision["cutoff"],
                        "driver_id": row["driver_id"],
                        "target_lap": result["target_lap"],
                        "pit_related": pit_related,
                        "control_overlap": control,
                        "errors": result["errors"],
                    }
                )
            result = row["gap"]
            if result["errors"] is not None:
                horizon = _dt(result["horizon"])
                label = (
                    "control_window_overlap"
                    if _overlaps(at, horizon, windows)
                    else "no_identified_control_overlap"
                )
                gap_groups[label].append(result)
    return {
        "purpose": "posthoc_development_error_description_not_features_or_causal_attribution",
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "groups_overlap": True,
        "control_windows": windows,
        "lap_groups": {k: _metrics(v) for k, v in sorted(lap_groups.items())},
        "gap_groups": {k: _metrics(v) for k, v in sorted(gap_groups.items())},
        "lap_exclusions": dict(
            Counter(
                r["lap"]["reason"]
                for e in evaluations
                for r in e["drivers"]
                if r["lap"]["errors"] is None
            )
        ),
        "gap_exclusions": dict(
            Counter(
                r["gap"]["reason"]
                for e in evaluations
                for r in e["drivers"]
                if r["gap"]["errors"] is None
            )
        ),
        "state_alignment": identities,
        "largest_linear_lap_errors": sorted(
            top_errors, key=lambda r: r["errors"]["prefix_linear"], reverse=True
        )[:10],
        "limitations": [
            "First-lap source differences excluded from training, not silently reconciled",
            "Pit-related labels use archived pit-lap/outlap evidence, not exact entry times",
            "Control-ending message is not clearance; only explicit TRACK CLEAR closes window",
            "No identified event does not mean traffic-free or green",
            "Null leader/lapped gaps and stale reports stay excluded; no interpolation",
        ],
    }
