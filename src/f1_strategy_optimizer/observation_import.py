"""Offline receipt-envelope validation; never grants live/model eligibility.

This staging boundary is intentionally independent of frozen replay/model code.
Imported receipt timestamps are declarations, not verified publication evidence.
"""

import argparse
import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path

from .event_replay import digest, iso
from .replay import named, timestamp


def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and nonnegative")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def inspect_import(document, cutoff, *, mode="recorded_receipts", assumed_delay_seconds=None,
                   max_age_seconds=120, max_skew_seconds=2):
    """Select as-of revisions and report missing/delayed/asynchronous observations.

    Required streams are explicit per-source/per-driver keys. No field defaults,
    last-known-value filling, interpolation, or conversion to model inputs occurs.
    """
    at = timestamp(cutoff, "cutoff")
    if mode not in {"recorded_receipts", "historical_approximation"}:
        raise ValueError("Unknown import mode")
    if mode == "historical_approximation":
        _seconds(assumed_delay_seconds, "assumed_delay_seconds")
    elif assumed_delay_seconds is not None:
        raise ValueError("Recorded mode cannot assume a publication delay")
    _seconds(max_age_seconds, "max_age_seconds")
    _seconds(max_skew_seconds, "max_skew_seconds")
    if document.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    session = named(document.get("session_id"), "session_id")
    sequence_semantics = document.get("sequence_semantics", "unknown")
    if sequence_semantics not in {"unknown", "contiguous_per_stream"}:
        raise ValueError("Unknown sequence_semantics")
    required = document.get("required_streams")
    if not isinstance(required, list) or not required:
        raise ValueError("required_streams must be an explicit nonempty list")
    for stream in required:
        named(stream, "required stream")
    if len(set(required)) != len(required):
        raise ValueError("Duplicate required stream")
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    seen, identities, sequences, visible, stream_sources = {}, {}, {}, {}, {}
    diagnostics = Counter()
    rows = []
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("Record must be an object")
        row = dict(raw)
        for field in ("event_id", "source", "stream", "kind"):
            named(row.get(field), field)
        if row.get("payload") is not None and not isinstance(row["payload"], dict):
            raise ValueError("payload must be an object or null")
        if row.get("session_id") != session:
            raise ValueError("Mixed session identities")
        if stream_sources.setdefault(row["stream"], row["source"]) != row["source"]:
            raise ValueError("Stream keys must distinguish sources")
        for field in ("sequence", "revision"):
            value = row.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field} must be null or a nonnegative integer")
        identity = (row["source"], row["event_id"])
        stable = (row["stream"], row["kind"])
        if identities.setdefault(identity, stable) != stable:
            raise ValueError("Revision changes stream or kind")
        # Unknown revision permits one record, never an invented revision zero.
        key = (*identity, row.get("revision"))
        if key in seen:
            if digest(seen[key]) != digest(row):
                raise ValueError("Conflicting duplicate revision")
            diagnostics["exact_duplicate"] += 1
            continue
        seen[key] = row
        if row.get("sequence") is not None:
            seqkey = (row["source"], row["stream"], row["sequence"])
            if seqkey in sequences and sequences[seqkey] != key:
                raise ValueError("Conflicting source sequence")
            sequences[seqkey] = key
        event = timestamp(row["event_time"], "event_time") if row.get("event_time") else None
        received = (timestamp(row["received_at"], "received_at")
                    if row.get("received_at") else None)
        if event is not None and received is not None and received < event:
            raise ValueError("received_at precedes event_time; clock reconciliation required")
        if row["kind"] == "action":
            decided = timestamp(row["decided_at"], "decided_at") if row.get("decided_at") else None
            effective = (timestamp(row["effective_at"], "effective_at")
                         if row.get("effective_at") else None)
            if effective is not None and decided is not None and effective < decided:
                raise ValueError("Action effective_at precedes decided_at")
            diagnostics["action_boundary_requires_external_validation"] += 1
        available = received
        basis = "imported_received_at_unverified" if received else "unknown"
        if received is None and event is not None and mode == "historical_approximation":
            available = event + timedelta(seconds=assumed_delay_seconds)
            basis = "assumed_delay_not_publication_time"
        row = {**row, "available_at": iso(available) if available else None,
               "availability_basis": basis}
        rows.append(row)
        if event is None:
            diagnostics["missing_event_time"] += 1
        if available is None:
            diagnostics["missing_received_at"] += 1
            continue
        if available > at:
            diagnostics["not_yet_available"] += 1
            continue
        if event is not None and event > at:
            diagnostics["future_event_time"] += 1
        visible.setdefault(identity, []).append(row)

    # Provider IDs need not be contiguous; only an explicit local stream contract
    # can turn a numeric gap into missing-message evidence.
    groups = {}
    for source, stream, seq in sequences:
        groups.setdefault((source, stream), set()).add(seq)
    diagnostics["internal_sequence_gaps"] = sum(
        max(s) - min(s) + 1 - len(s) for s in groups.values()
    )
    latest = {}
    for versions in visible.values():
        if len(versions) > 1 and any(v.get("revision") is None for v in versions):
            raise ValueError("Multiple revisions require explicit revision numbers")
        version = max(versions, key=lambda v: v.get("revision") or 0)
        # An available correction removing/invalidating event time supersedes the
        # older value, rather than silently resurrecting that obsolete version.
        if not version.get("event_time") or timestamp(version["event_time"], "event_time") > at:
            continue
        previous = latest.get(version["stream"])
        order = (timestamp(version["event_time"], "event_time"),
                 timestamp(version["available_at"], "available_at"), version["event_id"])
        if previous is None or order > previous[0]:
            latest[version["stream"]] = (order, version)
    snapshot = {stream: item[1] for stream, item in latest.items() if stream in required}
    missing = [s for s in required if s not in snapshot]
    null_payload = [s for s, row in snapshot.items() if row.get("payload") is None]
    stale = [s for s, row in snapshot.items()
             if (at - timestamp(row["event_time"], "event_time")).total_seconds()
             > max_age_seconds]
    times = [timestamp(row["event_time"], "event_time") for row in snapshot.values()]
    skew = (max(times) - min(times)).total_seconds() if times else None
    sequence_ok = (sequence_semantics == "unknown"
                   or diagnostics["internal_sequence_gaps"] == 0)
    quality = (not missing and not null_payload and not stale and skew <= max_skew_seconds
               and sequence_ok)
    return {
        "schema_version": 1, "session_id": session, "cutoff": iso(at), "mode": mode,
        "label": ("HISTORICAL_APPROXIMATION_NOT_LIVE" if mode == "historical_approximation"
                  else "IMPORTED_RECEIPTS_NOT_VERIFIED_LIVE"),
        "input_sha256": digest(document), "assumed_delay_seconds": assumed_delay_seconds,
        "sequence_semantics": sequence_semantics,
        "policy": {"max_age_seconds": max_age_seconds, "max_skew_seconds": max_skew_seconds},
        "records": rows, "snapshot": snapshot, "diagnostics": dict(diagnostics),
        "missing_streams": missing, "null_payload_streams": null_payload,
        "stale_streams": stale, "snapshot_skew_seconds": skew,
        "snapshot_checks_passed": quality,
        "publication_time_verified": False, "model_eligible": False,
        "immediate_post_pit_target_enabled": False,
        "notice": "Offline staging only; source completeness, clocks, field and action boundaries "
                  "need external evidence. Receipt time is not source publication time.",
    }


def select_horizon(report, *, horizon, driver_stream, original_target_lap):
    """Explicit staging choice, preserving the original target even when blocked.

    A delayed lap-state report cannot prove that its next lap is still unstarted.
    Only an imported boundary assertion covering the confirmation cutoff passes
    the structural gate; it remains unverified and never enables a model here.
    """
    if horizon not in {"immediate_post_pit", "first_unstarted_after_confirmation"}:
        raise ValueError("Unknown horizon; an explicit choice is required")
    if type(original_target_lap) is not int or original_target_lap < 1:
        raise ValueError("original_target_lap must be a positive integer")
    result = {
        "requested_horizon": horizon, "original_immediate_target_lap": original_target_lap,
        "confirmation_at": report["cutoff"], "selected_target_lap": None,
        "candidate_target_lap": None, "prediction": None,
        "availability_label": ("retrospective assumed availability"
                               if report["mode"] == "historical_approximation"
                               else "imported received_at; provenance unverified"),
        "model_eligible": False, "reason": "immediate_next_lap_remains_blocked",
    }
    if horizon == "immediate_post_pit":
        return result
    row = report["snapshot"].get(driver_stream)
    payload = row.get("payload") if row else None
    lap = payload.get("current_lap") if isinstance(payload, dict) else None
    if type(lap) is not int or lap < 1 or row["kind"] != "lap_state":
        return {**result, "reason": "missing_current_lap_state"}
    candidate = lap + 1
    result["candidate_target_lap"] = candidate
    if candidate <= original_target_lap:
        return {**result, "reason": "candidate_not_after_original_immediate_target"}
    through = payload.get("not_started_through")
    if through is None:
        return {**result, "reason": "unstarted_boundary_unverified"}
    proof = timestamp(through, "not_started_through")
    if proof > timestamp(row["event_time"], "event_time"):
        raise ValueError("Boundary assertion cannot cover time after its observation")
    if proof < timestamp(report["cutoff"], "cutoff"):
        return {**result, "reason": "unstarted_boundary_stale"}
    if not report["snapshot_checks_passed"]:
        return {**result, "reason": "snapshot_checks_failed"}
    return {**result, "selected_target_lap": candidate,
            "reason": "distinct_horizon_structurally_selected_external_validation_required"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--mode", choices=["recorded_receipts", "historical_approximation"],
                        default="recorded_receipts")
    parser.add_argument("--assumed-delay-seconds", type=float)
    parser.add_argument("--max-age-seconds", type=float, default=120)
    parser.add_argument("--max-skew-seconds", type=float, default=2)
    parser.add_argument("--horizon", choices=["immediate_post_pit",
                                             "first_unstarted_after_confirmation"])
    parser.add_argument("--driver-stream")
    parser.add_argument("--original-target-lap", type=int)
    args = parser.parse_args(argv)
    result = inspect_import(json.loads(args.input.read_text()), args.cutoff, mode=args.mode,
                            assumed_delay_seconds=args.assumed_delay_seconds,
                            max_age_seconds=args.max_age_seconds,
                            max_skew_seconds=args.max_skew_seconds)
    if args.horizon:
        if not args.driver_stream or args.original_target_lap is None:
            parser.error("--horizon requires --driver-stream and --original-target-lap")
        result["horizon"] = select_horizon(
            result, horizon=args.horizon, driver_stream=args.driver_stream,
            original_target_lap=args.original_target_lap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    print(f"{result['label']}: snapshot_checks_passed={result['snapshot_checks_passed']}")


if __name__ == "__main__":
    main()
