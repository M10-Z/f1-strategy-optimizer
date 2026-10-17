"""Preserve one missing British pit-audit duration without blocking observations.

No frozen source, forecast, policy, sample, raw response or score rule changes.
The strict original and identity-corrected runs remain intact. This second
technical exception is frozen after acquisition but before British error scoring.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from . import holdout_sources as sources
from .artifacts import write_json
from .holdout_identity_erratum import run_corrected, verify_erratum

IDENTITY_COMMIT = "358345f1eea44700b7728fb93fdb2523fe356576"


def validate_target(root, document):
    target = document["target"]
    path = Path(root) / target["file"]
    meta = path.with_suffix(".meta.json")
    if (
        sources.sha_file(path) != target["body_sha256"]
        or sources.sha_file(meta) != target["metadata_sha256"]
    ):
        raise ValueError("Optional pit-audit correction target hash mismatch")
    raw = json.loads(path.read_bytes())
    empty = [
        row
        for race in raw["MRData"]["RaceTable"]["Races"]
        for row in race["PitStops"]
        if row["duration"] == ""
    ]
    if empty != [target["row"]]:
        raise ValueError("Only the exact recorded missing-duration pit row may be normalized")
    return empty


def nullable_pit_wrapper(original, document):
    """Keep original pagination/identity/key checks and permit exactly one null audit value."""

    def wrapped(root, event, endpoint, files, availability):
        if event["slug"] != "british" or endpoint != "pitstops":
            return original(root, event, endpoint, files, availability)
        validate_target(root, document)
        prior = sources._duration
        try:
            # This scope contains only the hash-bound British pit audit parser.
            sources._duration = lambda value: None if value == "" else prior(value)
            rows = original(root, event, endpoint, files, availability)
        finally:
            sources._duration = prior
        if rows is None:
            raise ValueError("Hash-bound pit response unexpectedly unavailable")
        unknowns = [r for r in rows if r["duration_seconds"] is None]
        target = document["target"]["row"]
        if len(unknowns) != 1 or any(
            str(unknowns[0][key]) != target[key]
            for key in ("driverId", "lap", "stop", "time", "duration")
        ):
            raise ValueError("Nullable normalization changed an unexpected audit record")
        return rows

    return wrapped


def verify_audit_freeze(manifest_file, audit_commit, data_root):
    repo = Path(__file__).resolve().parents[2]
    path = Path(manifest_file).resolve()
    document = json.loads(path.read_bytes())
    if document["schema_version"] != 1 or document["identity_erratum_commit"] != IDENTITY_COMMIT:
        raise ValueError("Wrong optional-audit correction lineage")
    identity_file = repo / document["identity_erratum_file"]
    identity, protocol, event = verify_erratum(identity_file, IDENTITY_COMMIT, data_root)
    if sources.sha_file(identity_file) != document["identity_erratum_sha256"]:
        raise ValueError("Identity erratum bytes changed")
    if (
        document["model_source_sha256"] != protocol["source_sha256"]
        or document["policy"] != protocol["policy"]
        or document["sampling"] != protocol["sampling"]
    ):
        raise ValueError("Optional-audit exception cannot change model/policy/sample")
    for name, expected in document["audit_source_sha256"].items():
        if sources.sha_file(repo / name) != expected:
            raise ValueError("Optional-audit wrapper source hash mismatch")
        raw = subprocess.run(
            ["git", "show", f"{audit_commit}:{name}"], cwd=repo, check=True, capture_output=True
        ).stdout
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Audit commit does not bind wrapper source")
    raw = subprocess.run(
        ["git", "show", f"{audit_commit}:{path.relative_to(repo).as_posix()}"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    if raw != path.read_bytes():
        raise ValueError("Optional-audit exception must be committed before British error scoring")
    prior_dir = repo / document["identity_corrected_run_dir"]
    for name, expected in document["identity_corrected_run_sha256"].items():
        if sources.sha_file(prior_dir / name) != expected:
            raise ValueError("Prior strict identity-corrected rejection run changed")
    prior_report = json.loads((prior_dir / "evaluation.json").read_bytes())
    british = next(r for r in prior_report["races"] if r["slug"] == "british")
    if (
        british["evaluations"]
        or british["summary"]["lap"]["scored"]
        or british["summary"]["gap"]["scored"]
    ):
        raise ValueError("British errors existed before the declared optional-audit exception")
    validate_target(Path(data_root) / "holdout-2024-british", document)
    return document, identity_file


def run_final(data_root, output_dir, manifest_file, audit_commit):
    document, identity_file = verify_audit_freeze(manifest_file, audit_commit, data_root)
    original = sources._jolpica_rows
    try:
        sources._jolpica_rows = nullable_pit_wrapper(original, document)
        report = run_corrected(data_root, output_dir, identity_file, IDENTITY_COMMIT)
    finally:
        sources._jolpica_rows = original
    british = next(r for r in report["races"] if r["slug"] == "british")
    normalized = {**document["target"]["row"], "duration_seconds": None}
    if british["source_audit"] is not None:
        british["source_audit"]["missing_pit_duration_records"] = [normalized]
    report["optional_audit_erratum"] = {
        "commit": audit_commit,
        "manifest_sha256": sources.sha_file(manifest_file),
        "target": document["target"],
        "normalized_audit_row": normalized,
        "raw_value_preserved": True,
        "targets_or_drivers_removed": 0,
        "forecast_source_model_policy_sample_score_changed": False,
        "strict_original_and_identity_corrected_rejections_preserved": True,
        "other_two_event_decisions_predictions_scores_identical": True,
        "timing": "after raw British acquisition, before its first prediction-error scoring",
    }
    report["holdout_execution_qualification"] = (
        "Pre-registered model, samples and scoring with two transparent adapter corrections. "
        "Both corrections followed evaluation of two events; the alias correction preceded British "
        "outcome GETs, and nullable optional audit correction preceded British error scoring. "
        "This is not an unmodified strict three-event blind execution."
    )
    write_json(Path(output_dir) / "evaluation.json", report)
    write_json(Path(output_dir) / "british-evaluation.json", british)
    write_json(
        Path(output_dir) / "optional-audit-erratum-run.json", report["optional_audit_erratum"]
    )
    summary = Path(output_dir) / "evaluation.md"
    with summary.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n## Transparent technical exceptions\n\n"
            + report["holdout_execution_qualification"]
            + "\n\nOne hash-bound Tsunoda pit-audit duration remains an empty raw string; "
            "its normalized seconds are null. Pit records never enter observation forecasts.\n"
        )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit-commit", required=True)
    args = parser.parse_args(argv)
    try:
        report = run_final(args.data_root, args.output_dir, args.manifest, args.audit_commit)
        print(json.dumps(report["equal_race_aggregate"], indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
