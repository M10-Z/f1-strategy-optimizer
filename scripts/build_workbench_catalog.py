"""Add evaluated real-event snapshots to an offline UI catalog without fitting models.

Both report and decisions must come from the same completed holdout run. Existing
output is never overwritten. Numerical exploration assumptions remain illustrative.
"""

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

from f1_strategy_optimizer.event_replay import verify_frozen
from f1_strategy_optimizer.workbench import DEFAULT_DATA, Workbench


def write_gzip(path, value):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output directory already exists; do not overwrite")
    report = json.loads(args.report.read_text())
    packets = json.loads(args.decisions.read_text())
    by_slug = {packet["slug"]: packet["decisions"] for packet in packets}
    shutil.copytree(DEFAULT_DATA, args.output_dir)
    catalog = json.loads((args.output_dir / "catalog.json").read_text())
    for race in report["races"]:
        if race["status"] != "evaluated":
            continue
        slug = race["slug"]
        frozen = by_slug[slug]
        for record in frozen:
            verify_frozen(record)
        evaluated = {r["decision_sha256"]: r for r in race["evaluations"]}
        if set(evaluated) != {r["decision_sha256"] for r in frozen}:
            raise ValueError(f"Evaluation and frozen records differ: {slug}")
        decisions, reveals, evidence, assumptions = (
            f"{slug}-{name}"
            for name in (
                "decisions.json.gz",
                "reveals.json.gz",
                "evidence.json.gz",
                "assumptions.json",
            )
        )
        write_gzip(args.output_dir / decisions, frozen)
        write_gzip(args.output_dir / reveals, evaluated)
        write_gzip(
            args.output_dir / evidence,
            {
                "source_manifest": race["source_manifest"],
                "source_audit": race["source_audit"],
                "freeze_commit": report["freeze_commit"],
                "partition": "holdout",
                "protocol_errata": {
                    key: value for key, value in report.items() if "erratum" in key
                },
                "scope": "Fixed whole-event holdout; no numerical assumption calibration",
            },
        )
        template = json.loads((DEFAULT_DATA / "assumptions.json").read_text())
        template["planning"]["state"].update(
            season=race["season"], event=f"{race['season']}-{slug}-manual-short-horizon"
        )
        explanation = (
            f"Manual illustrative four-driver after-lap-8 model for {race['season']} "
            f"{race['event']}. Numerical inputs are unchanged from the Bahrain UI template. "
            "They are not inferred or calibrated from this race's outcomes. Exact historical "
            "availability and pit-action boundary remain unknown."
        )
        template["planning"]["source"] = explanation
        template["action_boundary"]["rationale"] = explanation
        template["model_subset"]["rationale"] = explanation
        template["field_assumptions"]["state_alignment"]["rationale"] = explanation
        (args.output_dir / assumptions).write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n"
        )
        catalog["races"].append(
            {
                "id": f"{slug}-{race['season']}",
                "name": f"{race['season']} {race['event']} · 独立留出",
                "partition": "holdout",
                "decisions": decisions,
                "reveals": reveals,
                "evidence": evidence,
                "assumptions": assumptions,
            }
        )
    catalog["file_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.output_dir.iterdir())
        if path.name != "catalog.json"
    }
    (args.output_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    )
    app = Workbench(args.output_dir)
    print(
        json.dumps(
            {
                "output": str(args.output_dir),
                "races": len(app.races),
                "frozen_snapshots": len(app.cases),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
