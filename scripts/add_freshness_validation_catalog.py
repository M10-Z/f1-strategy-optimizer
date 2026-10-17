"""Add the completed reserved validation to a new offline research catalog."""

import gzip
import hashlib
import json
import shutil
from pathlib import Path


def main():
    source = Path("output/freshness-development")
    dest = Path("output/freshness-all-events")
    if dest.exists():
        raise ValueError("Do not overwrite an existing catalog")
    shutil.copytree(source, dest)
    catalog = json.loads((dest / "catalog.json").read_text())
    root = Path("output/freshness-belgian-validation")
    report = json.loads((root / "evaluation.json").read_text())
    records = json.loads((root / "decisions.json").read_text())
    contexts = json.loads((root / "contexts.json").read_text())
    reveals = {r["decision_sha256"]: r for r in report["baseline_evaluations"]}
    for e in report["evaluations"]:
        by_id = {r["driver_id"]: r for r in e["drivers"]}
        for row in reveals[e["decision_sha256"]]["drivers"]:
            row["freshness_evaluation"] = by_id[row["driver_id"]]
            row["posthoc_event_end_proxy"] = e["posthoc_event_end_proxy"]
    files = {
        "belgian-decisions.json.gz": records,
        "belgian-contexts.json.gz": contexts,
        "belgian-reveals.json.gz": reveals,
        "belgian-evidence.json.gz": {
            "source_manifest": report["source_manifest"],
            "source_audit": report["source_audit"],
            "freeze_commit": report["freeze_commit"],
            "reservation_commit": report["reservation_commit"],
        },
    }
    for name, value in files.items():
        with gzip.open(dest / name, "wt", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
    catalog["races"].append(
        {
            "id": "belgian-2024",
            "name": "2024 Belgian GP · 已完成独立验证，现已观察",
            "partition": "holdout",
            "decisions": "belgian-decisions.json.gz",
            "quality_context": "belgian-contexts.json.gz",
            "reveals": "belgian-reveals.json.gz",
            "evidence": "belgian-evidence.json.gz",
            "assumptions": "assumptions.json",
        }
    )
    catalog["file_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in dest.iterdir()
        if p.name != "catalog.json"
    }
    (dest / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(dest)


if __name__ == "__main__":
    main()
