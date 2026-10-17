"""Development-only event-time reconstruction and non-interventional forecasts.

The existing replay module evaluates fully specified action-matched strategy packets.
This module preserves the weaker semantics of public historical archives: asynchronous
observations, assumed publication delay, and unknown intervention timing. Observation
forecasts are never relabelled as stay-out strategy predictions.
"""

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import timedelta, timezone
from pathlib import Path

from .artifacts import _versions, write_json
from .replay import timestamp


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def dt(value):
    return timestamp(value, "event timestamp")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_gap(value):
    return number(value) and value >= 0


@dataclass(frozen=True)
class EventTimePolicy:
    publication_delay_seconds: float = 2.0
    timing_margin_seconds: float = 1.0
    interval_max_age_seconds: float = 12.0
    weather_max_age_seconds: float = 120.0
    gap_horizon_seconds: float = 90.0
    gap_window_seconds: float = 60.0
    lap_window: int = 8
    min_lap_samples: int = 3
    max_lap_slope: float = 1.0
    max_gap_slope: float = 0.2
    seed: int = 0

    def __post_init__(self):
        for key, value in asdict(self).items():
            if not number(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        for key in ("lap_window", "min_lap_samples", "seed"):
            if not isinstance(getattr(self, key), int):
                raise ValueError(f"{key} must be an integer")
        if not 2 <= self.min_lap_samples <= self.lap_window <= 30:
            raise ValueError("Need 2 <= min_lap_samples <= lap_window <= 30")
        if not 1 <= self.gap_horizon_seconds <= 300:
            raise ValueError("gap_horizon_seconds must be 1..300")
        if self.gap_window_seconds <= 0:
            raise ValueError("gap_window_seconds must be positive")

    @property
    def delay(self):
        return timedelta(seconds=self.publication_delay_seconds + self.timing_margin_seconds)


def unknown(reason):
    return {"value": None, "status": "unknown", "reason": reason}


def observed(value, event, cutoff, policy, source, *, inferred=False, max_age=None):
    age = (cutoff - event).total_seconds()
    result = {
        "value": value,
        "status": "inferred" if inferred else "observed",
        "source": source,
        "event_at": iso(event),
        "assumed_available_at": iso(event + policy.delay),
        "age_seconds": age,
        "publication_time_verified": False,
    }
    if max_age is not None and age > max_age:
        return {**result, "status": "unknown", "value": None, "reason": "stale_observation"}
    return result


def visible_events(rows, cutoff, policy):
    return sorted(
        (r for r in rows if dt(r["date"]) + policy.delay <= cutoff),
        key=lambda r: (dt(r["date"]), digest(r)),
    )


def lap_prefix(laps, cutoff, policy):
    """Do not inspect duration until the same driver's next start is visible.

    A future duration shortened by an archive revision cannot manufacture an earlier
    completion while the corroborating next-lap start is still unavailable.
    """
    starts = {}
    for row in laps:
        start = dt(row["date_start"])
        if start + policy.delay <= cutoff:
            key = (row["driver_number"], row["lap_number"])
            if key in starts:
                raise ValueError("Duplicate driver/lap start")
            starts[key] = (start, row)
    completed = {}
    for (driver, lap), (start, row) in starts.items():
        following = starts.get((driver, lap + 1))
        if following is None or following[0] <= start:
            continue
        duration = row.get("lap_duration")
        if not number(duration) or duration <= 0:
            continue
        end = max(start + timedelta(seconds=duration), following[0])
        if end + policy.delay <= cutoff:
            completed.setdefault(driver, []).append(
                {
                    "lap_number": lap,
                    "lap_duration": duration,
                    "start_at": iso(start),
                    "completion_at": iso(end),
                    "assumed_available_at": iso(end + policy.delay),
                    "is_pit_out_lap": row.get("is_pit_out_lap"),
                }
            )
    return starts, {d: sorted(rows, key=lambda r: r["lap_number"]) for d, rows in completed.items()}


def build_state(archive, cutoff, policy=None):
    """Return only an event-time prefix; archive audit/total/final results are excluded."""
    policy = policy or EventTimePolicy()
    at = dt(cutoff)
    starts, completed = lap_prefix(archive["laps"], at, policy)
    positions = visible_events(archive.get("position", []), at, policy)
    intervals = visible_events(archive.get("intervals", []), at, policy)
    weather = visible_events(archive.get("weather", []), at, policy)
    messages = visible_events(archive.get("race_control", []), at, policy)
    cars = []
    for driver in sorted(archive["drivers"], key=lambda r: r["driver_number"]):
        n = driver["driver_number"]
        history = completed.get(n, [])
        known_starts = [(lap, value[0]) for (d, lap), value in starts.items() if d == n]
        latest_start = max(known_starts, key=lambda pair: pair[1]) if known_starts else None
        car = {
            **driver,
            "completed_lap_history": history,
            "activity": unknown("No verified live retirement/activity event contract"),
            "tyre_inventory": unknown("No observed tyre stock"),
            "last_started_lap": observed(
                latest_start[0],
                latest_start[1],
                at,
                policy,
                "OpenF1.laps.date_start",
                inferred=True,
            )
            if latest_start
            else unknown("No available lap start"),
            "completed_laps": observed(
                history[-1]["lap_number"],
                dt(history[-1]["completion_at"]),
                at,
                policy,
                "corroborated_lap_completion",
                inferred=True,
            )
            if history
            else unknown("No corroborated completed lap"),
        }
        pos = [r for r in positions if r["driver_number"] == n]
        car["position"] = (
            observed(
                pos[-1]["position"],
                dt(pos[-1]["date"]),
                at,
                policy,
                "OpenF1.position:last_reported",
            )
            if pos
            else unknown("No position event available")
        )
        gaps = [r for r in intervals if r["driver_number"] == n]
        latest_gap = gaps[-1] if gaps else None
        if latest_gap is not None and valid_gap(latest_gap.get("gap_to_leader")):
            car["gap_seconds"] = observed(
                latest_gap["gap_to_leader"],
                dt(latest_gap["date"]),
                at,
                policy,
                "OpenF1.intervals:last_reported",
                max_age=policy.interval_max_age_seconds,
            )
        else:
            car["gap_seconds"] = unknown("Missing, negative, null or lap-string gap; not zero")
        car["interval_history"] = [
            {"date": r["date"], "gap_to_leader": r["gap_to_leader"]}
            for r in gaps
            if valid_gap(r.get("gap_to_leader"))
            and (at - dt(r["date"])).total_seconds() <= policy.gap_window_seconds
        ]
        # Whitelist fields. In particular, never read or propagate archival lap_end.
        eligible = []
        for s in archive.get("stints", []):
            if s["driver_number"] != n:
                continue
            start_event = starts.get((n, s["lap_start"]))
            if start_event is not None:
                eligible.append(
                    (
                        start_event[0],
                        {
                            k: s[k]
                            for k in ("lap_start", "stint_number", "compound", "tyre_age_at_start")
                        },
                    )
                )
        if eligible:
            event, stint = max(eligible, key=lambda pair: (pair[0], pair[1]["stint_number"]))
            count = sum(r["lap_number"] >= stint["lap_start"] for r in history)
            car["compound"] = observed(
                stint["compound"],
                event,
                at,
                policy,
                "OpenF1.stints:start-attached availability assumption",
                inferred=True,
            )
            car["estimated_completed_tyre_age"] = observed(
                stint["tyre_age_at_start"] + count,
                event,
                at,
                policy,
                "initial_age_plus_corroborated_completed_laps",
                inferred=True,
            )
        else:
            car["compound"] = unknown("No stint start available")
            car["estimated_completed_tyre_age"] = unknown("No stint start available")
        cars.append(car)
    weather_state = unknown("No available weather event")
    if weather:
        row = weather[-1]
        weather_state = observed(
            {k: row.get(k) for k in ("rainfall", "track_temperature", "air_temperature")},
            dt(row["date"]),
            at,
            policy,
            "OpenF1.weather",
            max_age=policy.weather_max_age_seconds,
        )
    return {
        "cutoff": iso(at),
        "partition": "development",
        "policy": asdict(policy),
        "session": {
            k: archive["session"][k]
            for k in ("session_key", "meeting_key", "year", "session_name", "date_start")
        },
        "time_semantics": "archival_event_time_with_assumed_delay_not_verified_online",
        "cars": cars,
        "weather_observation": weather_state,
        "track_status": unknown("Race-control semantics not reduced to whole-track state"),
        "surface_condition": unknown("Rainfall alone does not prove dry track"),
        "visible_race_control": [
            {
                k: r.get(k)
                for k in ("date", "category", "flag", "scope", "message", "driver_number", "sector")
            }
            for r in messages
        ],
        "field_semantics": "same UTC cutoff; asynchronous last-known events, not simultaneous gaps",
        "field_complete": False,
    }


def fit_line(points, target, max_slope, floor=0.001):
    """Small per-driver prefix-only OLS; no physical/causal pace interpretation."""
    xs, ys = zip(*points)
    xmean, ymean = statistics.mean(xs), statistics.mean(ys)
    denominator = sum((x - xmean) ** 2 for x in xs)
    slope = sum((x - xmean) * (y - ymean) for x, y in points) / denominator if denominator else 0
    slope = max(-max_slope, min(max_slope, slope))
    return {
        "prediction": max(floor, ymean + slope * (target - xmean)),
        "slope": slope,
        "center_x": xmean,
        "center_y": ymean,
        "sample_count": len(points),
    }


def code_version():
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("event_replay.py", "event_sources.py", "replay.py", "artifacts.py")
    }


def freeze_decision(archive, cutoff, policy=None):
    policy = policy or EventTimePolicy()
    state = build_state(archive, cutoff, policy)
    at = dt(state["cutoff"])
    horizon = at + timedelta(seconds=policy.gap_horizon_seconds)
    forecasts = []
    for car in state["cars"]:
        row = {"driver_number": car["driver_number"], "driver_id": car["id"]}
        history = [
            r
            for r in car["completed_lap_history"]
            if r["lap_number"] > 1 and r["is_pit_out_lap"] is False
        ][-policy.lap_window :]
        current = car["last_started_lap"]["value"]
        row["lap"] = {
            "target_lap": current + 1 if current is not None else None,
            "target_start_rule": "strictly_after_cutoff; reject without retargeting",
            "predictions": None,
            "reason": "insufficient_prefix_laps",
            "training_available_at": history[-1]["assumed_available_at"] if history else None,
        }
        if current is not None and len(history) >= policy.min_lap_samples:
            line = fit_line(
                [(r["lap_number"], r["lap_duration"]) for r in history],
                current + 1,
                policy.max_lap_slope,
            )
            row["lap"].update(
                predictions={
                    "prefix_linear": line["prediction"],
                    "prefix_median": statistics.median(r["lap_duration"] for r in history),
                    "last_eligible_completed": history[-1]["lap_duration"],
                },
                fit=line,
                reason=None,
            )
        gaps = car["interval_history"]
        row["gap"] = {
            "horizon": iso(horizon),
            "predictions": None,
            "reason": "insufficient_or_stale_numeric_interval_prefix",
        }
        if car["gap_seconds"]["value"] is not None and len(gaps) >= 2:
            line = fit_line(
                [((dt(g["date"]) - at).total_seconds(), g["gap_to_leader"]) for g in gaps],
                policy.gap_horizon_seconds,
                policy.max_gap_slope,
                floor=0,
            )
            row["gap"].update(
                predictions={
                    "prefix_linear": line["prediction"],
                    "persistence": car["gap_seconds"]["value"],
                },
                fit=line,
                reason=None,
            )
        forecasts.append(row)
    blockers = [
        "unknown_verified_action_effective_time",
        "unknown_pit_entry_exit_boundaries",
        "unverified_asynchronous_field_state",
        "unknown_whole_track_and_surface_state",
        "unknown_tyre_inventory_and_rule_feasibility",
        "unvalidated_causal_vehicle_and_tyre_model",
    ]
    record = {
        "schema_version": 1,
        "partition": "development",
        "cutoff": state["cutoff"],
        "code_version": code_version(),
        "config": asdict(policy),
        "seed": policy.seed,
        "randomness": "none; all forecasts and order deterministic",
        "data_version": {"visible_prefix_sha256": digest(state)},
        "fit_cutoff": state["cutoff"],
        "state": state,
        "observation_forecasts": forecasts,
        "observation_forecast_semantics": "unconditional factual prediction; not an intervention",
        "strategy": {
            "recommendation": None,
            "missing_fields": blockers,
            "candidates": [
                {
                    "action": action,
                    "requested_at": state["cutoff"],
                    "effective_at": None,
                    "effective_time_rule": "requires verified next pit-entry decision opportunity",
                    "status": "blocked",
                    "prediction": None,
                    "reasons": blockers,
                    "interpretation": "unavailable model counterfactual",
                }
                for action in ("stay_out", "pit_SOFT", "pit_MEDIUM", "pit_HARD")
            ],
        },
    }
    record["decision_sha256"] = digest(record)
    return record


def verify_frozen(frozen):
    body = {k: v for k, v in frozen.items() if k != "decision_sha256"}
    if digest(body) != frozen.get("decision_sha256"):
        raise ValueError("Frozen decision hash mismatch")


def score(predictions, actual):
    return {name: abs(value - actual) for name, value in predictions.items()}


def evaluate_frozen(frozen, archive):
    """Only this phase opens future outcomes. Never update a forecast or selection."""
    verify_frozen(frozen)
    policy = EventTimePolicy(**frozen["config"])
    at = dt(frozen["cutoff"])
    laps = {(r["driver_number"], r["lap_number"]): r for r in archive["laps"]}
    results = []
    for prediction in frozen["observation_forecasts"]:
        driver = prediction["driver_number"]
        result = {"driver_number": driver, "driver_id": prediction["driver_id"]}
        forecast = prediction["lap"]
        lap_result = {"status": "excluded", "reason": forecast["reason"], "errors": None}
        if forecast["predictions"] is not None:
            target = laps.get((driver, forecast["target_lap"]))
            if target is None:
                lap_result["reason"] = "target_missing_no_retirement_inference"
            elif dt(target["date_start"]) <= at:
                lap_result["reason"] = "target_already_started"
            elif not number(target.get("lap_duration")) or target["lap_duration"] <= 0:
                lap_result["reason"] = "target_duration_unknown"
            else:
                # Do not remove future pit/SC/weather laps: they are forecast error, not leakage.
                lap_result = {
                    "status": "scored_observation_only",
                    "reason": None,
                    "target_lap": forecast["target_lap"],
                    "start_at": target["date_start"],
                    "actual": target["lap_duration"],
                    "errors": score(forecast["predictions"], target["lap_duration"]),
                    "action_matching": "not_applicable_to_unconditional_forecast",
                }
        result["lap"] = lap_result
        forecast = prediction["gap"]
        gap_result = {"status": "excluded", "reason": forecast["reason"], "errors": None}
        if forecast["predictions"] is not None:
            horizon = dt(forecast["horizon"])
            observations = visible_events(
                [r for r in archive.get("intervals", []) if r["driver_number"] == driver],
                horizon,
                policy,
            )
            target = observations[-1] if observations else None
            if target is None or dt(target["date"]) <= at:
                gap_result["reason"] = "no_new_interval_outcome"
            elif (horizon - dt(target["date"])).total_seconds() > policy.interval_max_age_seconds:
                gap_result["reason"] = "stale_interval_outcome"
            elif not valid_gap(target.get("gap_to_leader")):
                gap_result["reason"] = "invalid_or_null_interval_outcome"
            else:
                gap_result = {
                    "status": "scored_observation_only",
                    "reason": None,
                    "event_at": target["date"],
                    "horizon": forecast["horizon"],
                    "actual": target["gap_to_leader"],
                    "errors": score(forecast["predictions"], target["gap_to_leader"]),
                    "action_matching": "not_applicable_to_unconditional_forecast",
                }
        result["gap"] = gap_result
        results.append(result)
    verify_frozen(frozen)
    return {
        "decision_sha256": frozen["decision_sha256"],
        "cutoff": frozen["cutoff"],
        "drivers": results,
        "strategy_scored": 0,
        "strategy_errors": None,
        "strategy_exclusion": "unknown_actions_or_blocked_candidates",
        "claim": "factual observation forecasts only; no causal strategy benefit",
    }


def summarize(evaluations):
    summary = {
        "partition": "development",
        "cases": len(evaluations),
        "strategy_scored": 0,
        "strategy_metrics": None,
    }
    for kind in ("lap", "gap"):
        rows = [d[kind] for case in evaluations for d in case["drivers"]]
        scored = [r for r in rows if r["errors"] is not None]
        methods = sorted({m for r in scored for m in r["errors"]})
        means = {m: statistics.mean(r["errors"][m] for r in scored) for m in methods}
        summary[kind] = {
            "attempted": len(rows),
            "scored": len(scored),
            "excluded": dict(Counter(r["reason"] for r in rows if r["errors"] is None)),
            "mae_seconds": means or None,
            "paired_linear_minus_baseline_mae_seconds": {
                m: means["prefix_linear"] - means[m] for m in methods if m != "prefix_linear"
            }
            or None,
            "metric": "full_lap_duration" if kind == "lap" else "last_available_gap_report",
            "selection": "fixed cutoffs; no future condition/action-based sample filtering",
        }
    return summary


def run_archive(archive, cutoffs, output_dir, policy=None):
    cutoffs = [iso(dt(c)) for c in cutoffs]
    if not cutoffs or len(cutoffs) > 30 or len(set(cutoffs)) != len(cutoffs):
        raise ValueError("Provide 1..30 distinct explicit UTC cutoffs")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    frozen = [freeze_decision(archive, c, policy) for c in cutoffs]
    # Durable freeze precedes every outcome evaluation in the batch.
    write_json(output / "decisions.json", frozen)
    evaluations = [evaluate_frozen(f, archive) for f in frozen]
    summary = summarize(evaluations)
    report = {
        "summary": summary,
        "evaluations": evaluations,
        "runtime_seconds": time.perf_counter() - start,
        "source_manifest": archive["source_manifest"],
        "source_audit": archive["audit"],
        "versions": _versions(),
        "limitations": [
            "Bahrain is development, not independent holdout",
            "Assumed event-time delay; historical publication times unavailable",
            "No action-matched strategy scores or strategy recommendation",
            "Asynchronous interval-report error is not physical gap accuracy",
            "No inventory, causal pace identification or strategy benefit claim",
        ],
    }
    write_json(output / "evaluation.json", report)
    lines = [
        "# Event-time development benchmark",
        "",
        "Observation forecasts only. Strategy recommendations and strategy metrics unavailable.",
        "",
        "| Target | Attempted | Scored | MAE seconds |",
        "|---|---:|---:|---|",
    ]
    for kind in ("lap", "gap"):
        r = summary[kind]
        lines.append(f"| {r['metric']} | {r['attempted']} | {r['scored']} | {r['mae_seconds']} |")
    lines += [
        "",
        "## Exclusions",
        "",
        json.dumps(
            {k: summary[k]["excluded"] for k in ("lap", "gap")}, ensure_ascii=False, indent=2
        ),
        "",
        *report["limitations"],
        "",
        f"Runtime: {report['runtime_seconds']:.3f}s",
    ]
    (output / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openf1-dir", required=True)
    parser.add_argument("--jolpica-dir", required=True)
    parser.add_argument(
        "--cutoffs", required=True, help="JSON file of predeclared UTC timestamp list"
    )
    parser.add_argument("--policy", help="Optional JSON EventTimePolicy overrides")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    from .event_sources import load_archive

    policy = EventTimePolicy(**json.loads(Path(args.policy).read_text())) if args.policy else None
    archive = load_archive(args.openf1_dir, args.jolpica_dir)
    report = run_archive(
        archive, json.loads(Path(args.cutoffs).read_text()), args.output_dir, policy
    )
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
