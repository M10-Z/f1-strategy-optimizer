"""Transparent metadata-only British country-alias correction; frozen model unchanged.

The original run remains immutable. This wrapper fixes only Great Britain ->
United Kingdom for session 9558, before its first outcome GET. The original
adapter, policy, 23 cutoffs, drivers, prediction and scoring kernels are reused.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

from . import holdout_evaluation as evaluation
from .artifacts import write_json
from .holdout_sources import (
    MAX_PAGES,
    OPENF1_KINDS,
    BoundedFetcher,
    _page,
    _schedule_rows,
    _try_read,
    sha_file,
    verify_freeze,
)
from .replay import timestamp

ORIGINAL_FREEZE_COMMIT = "8d7926c32d1ffe31a7e9d1a15c48a2baba7eb7e7"


def corrected_event(data_root, protocol, correction):
    """Resolve one exact schedule/session pair from previously fetched metadata."""
    root = Path(data_root) / "holdout-2024-metadata"
    files, availability = [], {}
    schedule = _try_read(root, "jolpica-schedule", "metadata", files, availability)
    sessions = _try_read(root, "openf1-sessions", "metadata", files, availability)
    if schedule is None or sessions is None:
        raise ValueError("Alias correction requires the originally saved metadata")
    reserved = next(e for e in protocol["events"] if e["slug"] == "british")
    if (
        correction["event"] != reserved["name"]
        or correction["from_country"] != reserved["country"]
        or correction["to_country"] != "United Kingdom"
    ):
        raise ValueError("Only the predeclared British country alias may be corrected")
    races = [
        r
        for r in _schedule_rows(schedule[0])
        if r["raceName"] == reserved["name"] and r["Circuit"]["circuitId"] == reserved["circuit"]
    ]
    if len(races) != 1:
        raise ValueError("British scheduled event is not unique")
    race = races[0]
    scheduled = timestamp(f"{race['date']}T{race['time']}", "scheduled start")
    candidates = [
        s
        for s in sessions[0]
        if s["year"] == 2024
        and s["session_type"] == s["session_name"] == "Race"
        and s["country_name"] == correction["to_country"]
        and timestamp(s["date_start"], "session start") == scheduled
        and s["session_key"] == correction["session_key"]
        and s["meeting_key"] == correction["meeting_key"]
    ]
    if len(candidates) != 1 or scheduled != timestamp(correction["scheduled_start"], "fixed start"):
        raise ValueError("Alias correction does not resolve exactly the predeclared session/start")
    return {
        **reserved,
        "country": correction["to_country"],
        "round": int(race["round"]),
        "scheduled_start": scheduled.isoformat(),
        "session": candidates[0],
        "status": "selected",
    }


def verify_erratum(erratum_file, erratum_commit, data_root, repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[2])
    path = Path(erratum_file).resolve()
    document = json.loads(path.read_bytes())
    if (
        document["original_freeze_commit"] != ORIGINAL_FREEZE_COMMIT
        or document["schema_version"] != 1
    ):
        raise ValueError("Erratum does not bind the original acquisition freeze")
    protocol_file = repo / document["original_protocol_file"]
    protocol = verify_freeze(protocol_file, ORIGINAL_FREEZE_COMMIT, repo)
    if sha_file(protocol_file) != document["original_protocol_sha256"]:
        raise ValueError("Original protocol hash mismatch")
    if document["policy"] != protocol["policy"] or document["sampling"] != protocol["sampling"]:
        raise ValueError("Identity erratum cannot change any policy or sampling setting")
    if document["model_source_sha256"] != protocol["source_sha256"]:
        raise ValueError("Identity erratum cannot change frozen source/model hashes")
    for name, expected in document["metadata_sha256"].items():
        if sha_file(Path(data_root) / "holdout-2024-metadata" / name) != expected:
            raise ValueError(f"Original metadata hash mismatch: {name}")
    for name, expected in document["erratum_source_sha256"].items():
        if sha_file(repo / name) != expected:
            raise ValueError(f"Erratum source hash mismatch: {name}")
        committed = subprocess.run(
            ["git", "show", f"{erratum_commit}:{name}"], cwd=repo, check=True, capture_output=True
        ).stdout
        if hashlib.sha256(committed).hexdigest() != expected:
            raise ValueError("Erratum commit does not bind correction source bytes")
    committed = subprocess.run(
        ["git", "show", f"{erratum_commit}:{path.relative_to(repo).as_posix()}"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    if committed != path.read_bytes():
        raise ValueError("Erratum must be committed before British outcome acquisition")
    for name, expected in document["original_run_sha256"].items():
        if sha_file(repo / document["original_run_dir"] / name) != expected:
            raise ValueError("The original rejected-selection run was changed")
    event = corrected_event(data_root, protocol, document["correction"])
    return document, protocol, event


def acquire_british(data_root, erratum_file, erratum_commit):
    document, protocol, event = verify_erratum(erratum_file, erratum_commit, data_root)
    root = Path(data_root) / "holdout-2024-british"
    # Any existing outcome receipt must come from this committed erratum; no other run is reused.
    for path in root.glob("*.meta.json"):
        if json.loads(path.read_bytes()).get("freeze_commit") != erratum_commit:
            raise ValueError("British outcomes existed outside the pre-acquisition erratum")
    fetcher = BoundedFetcher(erratum_commit)
    existing = len(list(Path(data_root).glob("holdout-2024-*/*.meta.json")))
    fetcher.requests = existing  # Preserve the original global 150-request ceiling.
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "event.json", event)
    for kind in OPENF1_KINDS:
        url = (
            "https://api.openf1.org/v1/"
            + kind
            + "?"
            + urlencode({"session_key": event["session"]["session_key"]})
        )
        fetcher.fetch(root, f"openf1-{kind}", url)
    for endpoint in ("results", "laps", "pitstops"):
        offset, expected = 0, None
        for _ in range(MAX_PAGES):
            url = f"https://api.jolpi.ca/ergast/f1/2024/{event['round']}/{endpoint}/?" + urlencode(
                {"limit": 100, "offset": offset}
            )
            stem = f"jolpica-{endpoint}-{offset:04d}"
            receipt = fetcher.fetch(root, stem, url)
            if (
                receipt["http_and_connect"] not in {"200 200", "200 000"}
                or receipt["curl_exit_code"]
            ):
                break
            source = json.loads((root / f"{stem}.body").read_bytes())
            race, returned_offset, limit, total = _page(source, receipt, event, endpoint)
            if returned_offset != offset or (expected is not None and expected != total):
                raise ValueError("British pagination changed; no retry")
            expected = total
            count = (
                sum(len(lap["Timings"]) for lap in race["Laps"])
                if endpoint == "laps"
                else len(race["Results" if endpoint == "results" else "PitStops"])
            )
            if count > limit or (not count and total):
                raise ValueError("British pagination count invalid; no retry")
            offset += count
            if offset == total:
                break
            if offset > total:
                raise ValueError("British pagination overrun; no retry")
        else:
            raise ValueError("British pagination page budget exceeded")
    receipt = {
        "original_freeze_commit": ORIGINAL_FREEZE_COMMIT,
        "erratum_commit": erratum_commit,
        "erratum_sha256": sha_file(erratum_file),
        "new_requests": fetcher.requests - existing,
        "event": event,
        "model_policy_sampling_changed": False,
    }
    write_json(root / "identity-erratum-acquisition.json", receipt)
    return receipt


def corrected_selection(data_root, protocol, correction, original_selector):
    events, receipts = original_selector(data_root, protocol)
    replacements = [i for i, event in enumerate(events) if event["slug"] == "british"]
    if len(replacements) != 1:
        raise ValueError("Original reserved British event is not unique")
    index = replacements[0]
    if (
        events[index]["status"] != "missing"
        or events[index]["reason"] != "session_identity_not_unique"
    ):
        raise ValueError("Erratum must correct only the documented original metadata rejection")
    events[index] = corrected_event(data_root, protocol, correction)
    return events, receipts


def run_corrected(data_root, output_dir, erratum_file, erratum_commit):
    document, protocol, event = verify_erratum(erratum_file, erratum_commit, data_root)
    repo = Path(__file__).resolve().parents[2]
    original = evaluation.selected_metadata
    try:
        evaluation.selected_metadata = lambda root, frozen_protocol: corrected_selection(
            root, frozen_protocol, document["correction"], original
        )
        report = evaluation.run_holdouts(
            data_root, output_dir, repo / document["original_protocol_file"], ORIGINAL_FREEZE_COMMIT
        )
    finally:
        evaluation.selected_metadata = original
    baseline_dir = repo / document["original_run_dir"]
    baseline = json.loads((baseline_dir / "evaluation.json").read_bytes())
    old_packets = {
        p["slug"]: p["decisions"]
        for p in json.loads((baseline_dir / "decisions.json").read_bytes())
    }
    new_packets = {
        p["slug"]: p["decisions"]
        for p in json.loads((Path(output_dir) / "decisions.json").read_bytes())
    }
    for slug in ("monaco", "italian"):
        old = next(r for r in baseline["races"] if r["slug"] == slug)
        new = next(r for r in report["races"] if r["slug"] == slug)
        if (
            old_packets[slug] != new_packets[slug]
            or old["evaluations"] != new["evaluations"]
            or old["summary"] != new["summary"]
            or old["source_manifest"] != new["source_manifest"]
        ):
            raise ValueError("Country alias erratum changed a previously evaluated event")
    report["identity_erratum"] = {
        "erratum_commit": erratum_commit,
        "erratum_sha256": sha_file(erratum_file),
        "correction": document["correction"],
        "original_run_preserved": True,
        "other_event_decisions_predictions_scores_identical": True,
        "version_selection": (
            "Corrected event identity fixed before British results; no score-based selection"
        ),
    }
    write_json(Path(output_dir) / "evaluation.json", report)
    write_json(Path(output_dir) / "identity-erratum-run.json", report["identity_erratum"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("acquire", "evaluate"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--erratum", type=Path, required=True)
    parser.add_argument("--erratum-commit", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "acquire":
            acquire_british(args.data_root, args.erratum, args.erratum_commit)
        else:
            if args.output_dir is None:
                raise ValueError("evaluate requires --output-dir")
            report = run_corrected(
                args.data_root, args.output_dir, args.erratum, args.erratum_commit
            )
            print(json.dumps(report["equal_race_aggregate"], indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
