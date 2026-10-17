"""Once-only reserved Belgian acquisition and frozen paired evaluation, no event substitution."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from f1_strategy_optimizer.artifacts import write_json
from f1_strategy_optimizer.event_replay import (
    digest,
    dt,
    evaluate_frozen,
    freeze_decision,
    summarize,
)
from f1_strategy_optimizer.freshness_evaluation import evaluate_quality, summarize_quality
from f1_strategy_optimizer.freshness_sources import load_candidate_archive
from f1_strategy_optimizer.holdout_evaluation import selected_metadata
from f1_strategy_optimizer.holdout_sources import (
    MAX_PAGES,
    OPENF1_KINDS,
    BoundedFetcher,
    _page,
)
from f1_strategy_optimizer.prefix_quality import POLICY, assess_prefix, make_context


def verify_freeze(manifest, commit):
    root = Path(__file__).resolve().parents[1]
    raw = manifest.read_bytes()
    document = json.loads(raw)
    saved = subprocess.check_output(["git", "show", f"{commit}:{manifest.as_posix()}"], cwd=root)
    if raw != saved or document["policy"] != POLICY:
        raise ValueError("Committed freeze/policy mismatch")
    for path, sha in document["source_sha256"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != sha:
            raise ValueError(f"Source changed: {path}")
        if (
            hashlib.sha256(
                subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)
            ).hexdigest()
            != sha
        ):
            raise ValueError(f"Freeze did not bind source: {path}")
    return document


def acquire(event, root, freeze):
    if root.exists():
        raise ValueError("Reserved outcome directory already exists; do not overwrite/reacquire")
    root.mkdir(parents=True)
    write_json(root / "event.json", event)
    fetcher = BoundedFetcher(freeze)
    for kind in OPENF1_KINDS:
        fetcher.fetch(
            root,
            f"openf1-{kind}",
            "https://api.openf1.org/v1/"
            + kind
            + "?"
            + urlencode({"session_key": event["session"]["session_key"]}),
        )
    for endpoint in ("results", "laps", "pitstops"):
        offset = 0
        expected = None
        for _ in range(MAX_PAGES):
            stem = f"jolpica-{endpoint}-{offset:04d}"
            receipt = fetcher.fetch(
                root,
                stem,
                f"https://api.jolpi.ca/ergast/f1/2024/{event['round']}/{endpoint}/?"
                + urlencode({"limit": 100, "offset": offset}),
            )
            if (
                receipt["http_and_connect"] not in {"200 200", "200 000"}
                or receipt["curl_exit_code"]
            ):
                break
            raw = json.loads((root / f"{stem}.body").read_bytes())
            race, got, limit, total = _page(raw, receipt, event, endpoint)
            if got != offset or (expected is not None and expected != total):
                raise ValueError("Pagination mismatch")
            expected = total
            count = (
                sum(len(lap["Timings"]) for lap in race["Laps"])
                if endpoint == "laps"
                else len(race["Results" if endpoint == "results" else "PitStops"])
            )
            if count > limit or (not count and total):
                raise ValueError("Invalid page count")
            offset += count
            if offset == total:
                break
            if offset > total:
                raise ValueError("Pagination overrun")
        else:
            raise ValueError("Page budget exceeded")
    return fetcher.requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument(
        "--manifest", type=Path, default=Path("examples/freshness-validation-freeze.json")
    )
    parser.add_argument(
        "--data-root", type=Path, default=Path(__file__).resolve().parents[2] / "real-data"
    )
    parser.add_argument("--output", type=Path, default=Path("output/freshness-belgian-validation"))
    args = parser.parse_args()
    manifest = verify_freeze(args.manifest, args.freeze_commit)
    if args.output.exists():
        parser.error("Output exists; no automatic rerun")
    args.output.mkdir(parents=True)
    reservation = json.loads(Path("examples/freshness-validation-reservation.json").read_text())
    try:
        events, metadata = selected_metadata(args.data_root, {"events": [reservation["event"]]})
        event = events[0]
        if event["status"] != "selected":
            raise ValueError(f"Frozen event unavailable: {event}")
        if event["session"]["circuit_short_name"] != reservation["event"]["openf1_circuit"]:
            raise ValueError("Circuit metadata mismatch; no substitution")
        raw_root = args.data_root / "freshness-2024-belgian"
        requests = acquire(event, raw_root, args.freeze_commit)
        loaded = load_candidate_archive(raw_root, event)
        archive = loaded["archive"]
        if archive is None:
            raise ValueError("Missing identity-complete reserved archive")
        records = []
        contexts = {}
        qualities = []
        for offset in range(600, 7201, 300):
            cutoff = (dt(event["scheduled_start"]) + timedelta(seconds=offset)).isoformat()
            frozen = freeze_decision(archive, cutoff)
            frozen["partition"] = frozen["state"]["partition"] = "holdout"
            frozen["data_version"]["visible_prefix_sha256"] = digest(frozen["state"])
            frozen["independent_validation_freeze"] = args.freeze_commit
            frozen.pop("decision_sha256")
            frozen["decision_sha256"] = digest(frozen)
            context = make_context(archive, frozen)
            records.append(frozen)
            contexts[frozen["decision_sha256"]] = context
            qualities.append(assess_prefix(frozen, context))
        for name, value in [
            ("decisions.json", records),
            ("contexts.json", contexts),
            ("candidate-predictions.json", qualities),
        ]:
            write_json(args.output / name, value)
            with (args.output / name).open("rb") as stream:
                os.fsync(stream.fileno())
        write_json(
            args.output / "prediction-freeze-receipt.json",
            {
                "before_any_scoring": True,
                "files": {
                    name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                    for name in ("decisions.json", "contexts.json", "candidate-predictions.json")
                },
            },
        )
        baseline = [evaluate_frozen(f, archive) for f in records]
        evaluated = [
            evaluate_quality(f, contexts[f["decision_sha256"]], archive, b)
            for f, b in zip(records, baseline)
        ]
        summary = summarize_quality(evaluated, reservation["acceptance_thresholds"])
        stale = 0
        future = 0
        for frozen, quality in zip(records, qualities):
            for driver in quality["drivers"].values():
                c = driver["candidate"]
                if c["value_seconds"] is None:
                    continue
                stale += int(
                    (dt(frozen["cutoff"]) - dt(c["sample_completion_times"][-1])).total_seconds()
                    > POLICY["lap_max_age_seconds"]
                )
                future += sum(
                    dt(t) + timedelta(seconds=3) > dt(frozen["cutoff"])
                    for t in c["sample_completion_times"]
                )
        summary["threshold_checks"].update(
            no_future_violations=future == 0, no_stale_predictions=stale == 0
        )
        summary["acceptance"] = (
            "passed_all_preregistered_thresholds"
            if all(summary["threshold_checks"].values())
            else "failed_preregistered_thresholds"
        )
        result = {
            "event": event,
            "freeze_commit": args.freeze_commit,
            "reservation_commit": manifest["reservation_commit"],
            "network_requests": requests,
            "source_manifest": loaded["source_manifest"],
            "metadata_receipts": metadata,
            "source_audit": archive["audit"],
            "baseline_summary_original_fixed_denominator": summarize(baseline),
            "candidate_summary": summary,
            "future_violations": future,
            "stale_predictions": stale,
            "evaluations": evaluated,
            "baseline_evaluations": baseline,
            "qualification": (
                "One reserved event; selective observational prediction, "
                "no calibrated probabilities or causal claims; no tuning after result"
            ),
        }
        write_json(args.output / "evaluation.json", result)
        print(json.dumps(summary, indent=2))
    except Exception as exc:
        write_json(
            args.output / "blocked.json",
            {
                "event": reservation["event"],
                "freeze_commit": args.freeze_commit,
                "action": "acquire/validate reserved event",
                "reason": str(exc),
                "no_substitution": True,
                "no_retries": True,
            },
        )
        raise


if __name__ == "__main__":
    main()
