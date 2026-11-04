"""Posthoc Bahrain development error attribution proxies, never model features."""

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

from f1_strategy_optimizer.development_audit import _write, audit_development
from f1_strategy_optimizer.workbench import DEFAULT_DATA, Workbench


def classify_transition(target, following):
    """Positive evidence takes precedence; missing labels never mean no event."""
    if target.get("is_pit_out_lap") is True:
        return "target_is_outlap"
    if following is not None and following.get("is_pit_out_lap") is True:
        return "next_lap_is_outlap_proxy"
    if (
        target.get("is_pit_out_lap") is False
        and following is not None
        and following.get("is_pit_out_lap") is False
    ):
        return "no_identified_pit_relation"
    return "transition_label_unavailable"


def diagnose(laps_path, output_dir):
    output = Path(output_dir)
    # Freeze/reproduce forecasts before reading any new posthoc labels.
    summary = audit_development(output)
    source = Path(laps_path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("Bahrain lap source exceeds byte budget")
    raw = source.read_bytes()
    laps = json.loads(raw)
    if not isinstance(laps, list) or not laps:
        raise ValueError("Expected nonempty lap array")
    if any(row["session_key"] != 7953 or row["meeting_key"] != 1141 for row in laps):
        raise ValueError("Only already-observed Bahrain 2023 development data is permitted")
    lookup = {(row["driver_number"], row["lap_number"]): row for row in laps}
    if len(lookup) != len(laps):
        raise ValueError("Duplicate lap identity")
    app = Workbench(DEFAULT_DATA, expected_races={"bahrain-2023": "development"})
    frozen = {row[1]["cutoff"]: row[1] for row in app.cases.values()}
    audit_rows = json.loads((output / "rows.json").read_text())
    groups, details = defaultdict(list), []
    for row in audit_rows:
        if row["category"] != "scored":
            continue
        state = frozen[row["cutoff"]]
        car = next(car for car in state["state"]["cars"] if car["id"] == row["driver_id"])
        key = car["driver_number"], row["target_lap"]
        target = lookup[key]
        if target["lap_duration"] != row["actual"]:
            raise ValueError("Raw source target differs from audited outcome")
        following = lookup.get((key[0], key[1] + 1))
        label = classify_transition(target, following)
        groups[label].append(row["candidate_abs_error"])
        if label in {"target_is_outlap", "next_lap_is_outlap_proxy"}:
            details.append(
                {
                    **row,
                    "posthoc_label": label,
                    "target_start": target["date_start"],
                    "visible_last_started_lap": car["last_started_lap"],
                    "visible_compound": car["compound"],
                    "visible_tyre_age": car["estimated_completed_tyre_age"],
                    "visible_completed_laps": car["completed_lap_history"][-3:],
                }
            )
    total_error = sum(sum(errors) for errors in groups.values())
    report = {
        "purpose": "posthoc_development_description_not_causal_identification_or_features",
        "event": "Bahrain 2023",
        "new_independent_validation": False,
        "model_changed": False,
        "source_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_origin": "caller-supplied OpenF1-schema raw file; origin not verified",
        "source_receipt_verified": False,
        "overall_unchanged": summary["candidate"],
        "fixed_slots_unchanged": summary["fixed_slots"],
        "scored_slots": summary["scored_slots"],
        "coverage": summary["coverage"],
        "score_categories": summary["categories"],
        "labelled_scored_slots": sum(
            len(errors)
            for label, errors in groups.items()
            if label != "transition_label_unavailable"
        ),
        "label_unavailable_scored_slots": len(groups.get("transition_label_unavailable", [])),
        "groups": {
            label: {
                "n": len(errors),
                "mae_seconds": statistics.mean(errors),
                "share_of_total_absolute_error": sum(errors) / total_error if total_error else None,
            }
            for label, errors in sorted(groups.items())
        },
        "pit_related_examples": details,
        "limitations": [
            "Labels use future outcomes and must never enter predictor or abstention rules",
            "Next-lap outlap is a pit-related proxy, not verified pit-entry timing",
            "No identified pit relation does not establish absence of traffic/control effects",
            "Group errors describe association; they do not identify causal pit-loss effects",
            "Deleting labelled difficult cases would distort operational accuracy and coverage",
            "No reliable new prefix-only candidate established from three observed cutoffs",
        ],
    }
    _write(output / "transition-diagnostics.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.laps, args.output_dir), ensure_ascii=False, indent=2))
