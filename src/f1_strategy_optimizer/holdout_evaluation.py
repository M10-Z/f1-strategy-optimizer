"""Pre-registered whole-event holdout evaluation using the unchanged replay kernel."""

import argparse
import json
import statistics
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from .artifacts import _versions, write_json
from .event_replay import (
    EventTimePolicy,
    digest,
    evaluate_frozen,
    freeze_decision,
    iso,
    summarize,
    verify_frozen,
)
from .holdout_sources import (
    EVENTS,
    _schedule_rows,
    _try_read,
    load_holdout_archive,
    sha_file,
    verify_freeze,
)
from .replay import timestamp


def selected_metadata(data_root, protocol):
    """Reconstruct event identity from hash-verified schedule responses, not event.json."""
    root = Path(data_root) / "holdout-2024-metadata"
    files, availability = [], {}
    schedule = _try_read(root, "jolpica-schedule", "metadata", files, availability)
    sessions = _try_read(root, "openf1-sessions", "metadata", files, availability)
    if schedule is None or sessions is None:
        return [
            {**e, "status": "missing", "reason": "missing_schedule_or_session_metadata"}
            for e in protocol["events"]
        ], files
    schedules = _schedule_rows(schedule[0])
    events = []
    for reserved in protocol["events"]:
        candidates = [
            r
            for r in schedules
            if r["raceName"] == reserved["name"]
            and r["Circuit"]["circuitId"] == reserved["circuit"]
        ]
        if len(candidates) != 1:
            events.append(
                {**reserved, "status": "missing", "reason": "schedule_identity_not_unique"}
            )
            continue
        race = candidates[0]
        at = timestamp(f"{race['date']}T{race['time']}", "scheduled start")
        candidates = [
            s
            for s in sessions[0]
            if s["year"] == 2024
            and s["session_name"] == "Race"
            and s["session_type"] == "Race"
            and s["country_name"] == reserved["country"]
            and timestamp(s["date_start"], "session start") == at
        ]
        if len(candidates) != 1:
            events.append(
                {**reserved, "status": "missing", "reason": "session_identity_not_unique"}
            )
            continue
        events.append(
            {
                **reserved,
                "round": int(race["round"]),
                "scheduled_start": iso(at),
                "session": candidates[0],
                "status": "selected",
            }
        )
    return events, files


def holdout_freeze(archive, cutoff, policy, protocol_sha256, freeze_commit):
    """Change metadata partition before the durable freeze, without changing forecasts."""
    record = freeze_decision(archive, cutoff, policy)
    record["partition"] = record["state"]["partition"] = "holdout"
    record["data_version"]["visible_prefix_sha256"] = digest(record["state"])
    record["holdout_protocol"] = {"sha256": protocol_sha256, "freeze_commit": freeze_commit}
    record.pop("decision_sha256")
    record["decision_sha256"] = digest(record)
    verify_frozen(record)
    return record


def _missing_summary(driver_count, cutoff_count, reason):
    count = driver_count * cutoff_count if driver_count is not None else None
    summary = {
        "partition": "holdout",
        "cases": cutoff_count,
        "strategy_scored": 0,
        "strategy_metrics": None,
    }
    for kind in ("lap", "gap"):
        summary[kind] = {
            "attempted": count,
            "scored": 0,
            "excluded": {reason: count},
            "mae_seconds": None,
            "default_mae_seconds": None,
            "default_method_counts": {},
            "paired_linear_minus_baseline_mae_seconds": None,
            "metric": "full_lap_duration" if kind == "lap" else "last_available_gap_report",
        }
    return summary


def equal_race_aggregate(races):
    """Each reserved event has equal weight; never pool targets to weight a race."""
    result = {
        "events_reserved": len(EVENTS),
        "aggregation_unit": "whole_event",
        "strategy_scored": 0,
        "strategy_metrics": None,
    }
    for kind in ("lap", "gap"):
        rows = [r["summary"][kind] for r in races]
        available = [r for r in rows if r["scored"]]
        methods = sorted({m for r in available for m in r["mae_seconds"]})
        means = {m: statistics.mean(r["mae_seconds"][m] for r in available) for m in methods}
        default_mean = (
            statistics.mean(r["default_mae_seconds"] for r in available) if available else None
        )
        coverages = [r["scored"] / r["attempted"] for r in rows if r["attempted"]]
        result[kind] = {
            "events_scored": len(available),
            "events_reserved": len(EVENTS),
            "equal_race_mae_seconds": means or None,
            "equal_race_default_mae_seconds": default_mean,
            "complete_three_event_default_mae_seconds": default_mean
            if len(available) == len(EVENTS)
            else None,
            "equal_race_coverage_fraction": statistics.mean(coverages) if coverages else None,
            "events_with_known_denominator": len(coverages),
            "paired_linear_minus_baseline_equal_race_mae_seconds": {
                m: means["prefix_linear"] - means[m] for m in methods if m != "prefix_linear"
            }
            or None,
            "total_registered_driver_cutoffs": sum(r["attempted"] for r in rows)
            if all(r["attempted"] is not None for r in rows)
            else None,
            "total_scored": sum(r["scored"] for r in rows),
            "missing_event_policy": (
                "Null errors stay null; macro MAE averages scored events, with count disclosed"
            ),
        }
    return result


def _registered_count(root):
    """A denominator-only fallback; no identity or future classification inference."""
    files, availability = [], {}
    try:
        loaded = _try_read(root, "openf1-drivers", "denominator", files, availability)
    except (ValueError, KeyError, TypeError, OSError):
        return None
    if loaded is None or not isinstance(loaded[0], list):
        return None
    numbers = [r.get("driver_number") for r in loaded[0]]
    return (
        len(numbers)
        if numbers and None not in numbers and len(set(numbers)) == len(numbers)
        else None
    )


def run_holdouts(data_root, output_dir, protocol_file, freeze_commit):
    protocol = verify_freeze(protocol_file, freeze_commit)
    policy = EventTimePolicy()
    if asdict(policy) != protocol["policy"]:
        raise ValueError("Current EventTimePolicy defaults differ from the pre-acquisition freeze")
    output = Path(output_dir)
    if output.exists():
        raise ValueError("Output directory already exists; frozen results cannot be overwritten")
    offsets = protocol["sampling"]["offset_seconds"]
    if offsets != list(range(600, 7201, 300)):
        raise ValueError("Expected the original 23 scheduled-start offsets")
    start = time.perf_counter()
    events, metadata_files = selected_metadata(data_root, protocol)
    prepared = []
    for event in events:
        event_start = time.perf_counter()
        root = Path(data_root) / f"holdout-2024-{event['slug']}"
        loaded = {
            "archive": None,
            "registered_driver_count": None,
            "reason": event.get("reason"),
            "source_manifest": None,
            "availability": {},
        }
        if event["status"] == "selected":
            try:
                loaded = load_holdout_archive(root, event)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                loaded.update(
                    reason=f"source_validation_rejected:{type(exc).__name__}:{exc}",
                    registered_driver_count=_registered_count(root),
                )
        cutoffs = (
            [
                iso(timestamp(event["scheduled_start"], "scheduled start") + timedelta(seconds=o))
                for o in offsets
            ]
            if "scheduled_start" in event
            else []
        )
        frozen = (
            [
                holdout_freeze(
                    loaded["archive"], cutoff, policy, sha_file(protocol_file), freeze_commit
                )
                for cutoff in cutoffs
            ]
            if loaded["archive"] is not None
            else []
        )
        prepared.append(
            {
                "event": event,
                "loaded": loaded,
                "frozen": frozen,
                "cutoffs": cutoffs,
                "preparation_seconds": time.perf_counter() - event_start,
            }
        )
    output.mkdir(parents=True, exist_ok=False)
    # All three events and every fixed cutoff are durably frozen before ANY evaluation.
    packets = [
        {
            "event": p["event"]["name"],
            "slug": p["event"]["slug"],
            "decisions": p["frozen"],
            "status": "frozen" if p["frozen"] else "unavailable",
            "unavailable_reason": p["loaded"]["reason"],
        }
        for p in prepared
    ]
    write_json(output / "decisions.json", packets)
    write_json(output / "frozen-protocol.json", protocol)
    write_json(
        output / "decision-freeze-receipt.json",
        {
            "freeze_commit": freeze_commit,
            "protocol_sha256": sha_file(protocol_file),
            "decisions_file_sha256": sha_file(output / "decisions.json"),
            "all_events_frozen_before_scoring": True,
            "decision_count": sum(len(p["frozen"]) for p in prepared),
        },
    )
    races = []
    for prepared_event in prepared:
        t0 = time.perf_counter()
        event, loaded = prepared_event["event"], prepared_event["loaded"]
        evaluations = [
            evaluate_frozen(frozen, loaded["archive"]) for frozen in prepared_event["frozen"]
        ]
        summary = (
            summarize(evaluations)
            if evaluations
            else _missing_summary(
                loaded["registered_driver_count"],
                len(offsets),
                loaded["reason"] or "missing_source",
            )
        )
        summary["partition"] = "holdout"
        race = {
            "event": event["name"],
            "slug": event["slug"],
            "season": 2024,
            "partition": "holdout",
            "status": "evaluated" if evaluations else "unavailable",
            "scheduled_start": event.get("scheduled_start"),
            "cutoffs": prepared_event["cutoffs"],
            "registered_driver_count": loaded["registered_driver_count"],
            "summary": summary,
            "evaluations": evaluations,
            "source_manifest": loaded["source_manifest"],
            "availability": loaded["availability"],
            "source_audit": loaded["archive"]["audit"] if loaded["archive"] else None,
            "unavailable_reason": loaded["reason"],
            "runtime_seconds": prepared_event["preparation_seconds"] + time.perf_counter() - t0,
        }
        races.append(race)
        write_json(output / f"{event['slug']}-evaluation.json", race)
    report = {
        "schema_version": 1,
        "partition": "whole_event_holdout",
        "freeze_commit": freeze_commit,
        "candidate_commit": protocol["candidate_commit"],
        "protocol_sha256": sha_file(protocol_file),
        "reservation_sha256": protocol["reservation_sha256"],
        "policy": asdict(policy),
        "versions": _versions(),
        "metadata_receipts": metadata_files,
        "races": races,
        "equal_race_aggregate": equal_race_aggregate(races),
        "runtime_seconds": time.perf_counter() - start,
        "claim": "Reserved-event observation forecast evaluation; no causal strategy benefit",
        "limits": [
            "Only three reserved events; repeated driver/cutoff targets are correlated",
            "Median lap and persistence gap defaults were fixed before outcome acquisition",
            "Scheduled-start cutoffs include delays, red flags and race end; no resampling",
            "Denominators retain all registered drivers, including inactive/missing targets",
            "Event time plus assumed delay does not prove historical online availability",
            "Gap error measures fresh asynchronous interval reports, not physical distance",
            "Null/missing/quarantined observations are excluded with counts, never imputed as zero",
            "Kernel metadata partition becomes holdout before the decision hash freezes",
            "No inventory, full rules, action-matched strategy score or causal benefit proved",
            "No event, setting, cutoff or method changes after viewing holdout errors",
        ],
    }
    write_json(output / "evaluation.json", report)
    lines = [
        "# Reserved whole-event holdout validation",
        "",
        report["claim"],
        "",
        f"Freeze commit: {freeze_commit}",
        "",
        "| Event | Lap scored/all | Median MAE (s) | Gap scored/all | Persistence MAE (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for race in races:
        lap, gap = race["summary"]["lap"], race["summary"]["gap"]
        lines.append(
            f"| {race['event']} | {lap['scored']}/{lap['attempted']} | "
            f"{lap['default_mae_seconds']} | "
            f"{gap['scored']}/{gap['attempted']} | {gap['default_mae_seconds']} |"
        )
    lines += [
        "",
        "## Equal-event aggregate",
        "",
        json.dumps(report["equal_race_aggregate"], indent=2),
        "",
        "## Exclusions",
        "",
    ]
    for race in races:
        lines.append(
            f"- {race['event']}: "
            + json.dumps({k: race["summary"][k]["excluded"] for k in ("lap", "gap")})
        )
    lines += ["", *report["limits"], "", f"Runtime seconds: {report['runtime_seconds']:.3f}", ""]
    (output / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args(argv)
    try:
        report = run_holdouts(args.data_root, args.output_dir, args.freeze, args.freeze_commit)
        print(
            json.dumps(
                {
                    "equal_race_aggregate": report["equal_race_aggregate"],
                    "runtime_seconds": report["runtime_seconds"],
                },
                indent=2,
            )
        )
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
