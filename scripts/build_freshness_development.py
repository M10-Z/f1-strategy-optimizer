"""Build additive diagnostics/catalog from only the four already observed races."""

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

from f1_strategy_optimizer import holdout_sources as sources
from f1_strategy_optimizer.event_sources import load_archive
from f1_strategy_optimizer.freshness_evaluation import evaluate_quality, summarize_quality
from f1_strategy_optimizer.holdout_audit_erratum import nullable_pit_wrapper
from f1_strategy_optimizer.prefix_quality import make_context
from f1_strategy_optimizer.workbench import Workbench


def load_development(slug, data):
    if slug == "bahrain":
        return load_archive(data / "openf1-2023-bahrain", data / "jolpica-2023-bahrain")
    if slug not in {"british", "monaco", "italian"}:
        raise ValueError("Only the four observed development races allowed")
    root = data / f"holdout-2024-{slug}"
    original = sources._jolpica_rows
    try:
        if slug == "british":
            sources._jolpica_rows = nullable_pit_wrapper(
                original, json.loads(Path("examples/holdout-audit-erratum.json").read_text())
            )
        return sources.load_holdout_archive(root, json.loads((root / "event.json").read_text()))[
            "archive"
        ]
    finally:
        sources._jolpica_rows = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/freshness-development"))
    parser.add_argument(
        "--data-root", type=Path, default=Path(__file__).resolve().parents[2] / "real-data"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve prior evidence")
    app = Workbench("output/workbench-all-events")
    shutil.copytree(app.root, args.output)
    catalog = json.loads((args.output / "catalog.json").read_text())
    summaries = {}
    for race in catalog["races"]:
        slug = race["id"].split("-")[0]
        archive = load_development(slug, args.data_root)
        contexts = {}
        reveals = app._data(race["reveals"])
        scores = []
        for key, (r, frozen) in app.cases.items():
            if r["id"] != race["id"]:
                continue
            ctx = make_context(archive, frozen)
            contexts[frozen["decision_sha256"]] = ctx
            old = reveals[frozen["decision_sha256"]]
            result = evaluate_quality(frozen, ctx, archive, old)
            scores.append(result)
            by_id = {x["driver_id"]: x for x in result["drivers"]}
            for row in old["drivers"]:
                row["freshness_evaluation"] = by_id[row["driver_id"]]
                row["posthoc_event_end_proxy"] = result["posthoc_event_end_proxy"]
        quality_name = slug + "-prefix-context.json.gz"
        reveal_name = slug + "-quality-reveals.json.gz"
        for name, value in [(quality_name, contexts), (reveal_name, reveals)]:
            with gzip.open(args.output / name, "wt", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
        race["quality_context"] = quality_name
        race["reveals"] = reveal_name
        if race["partition"] == "holdout":
            race["name"] = race["name"].replace("独立留出", "已观察开发数据")
        summaries[slug] = summarize_quality(scores)
        (args.output / (slug + "-quality-evaluation.json")).write_text(
            json.dumps(scores, indent=2) + "\n"
        )
    catalog["file_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in args.output.iterdir()
        if p.name != "catalog.json"
    }
    (args.output / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    )
    (args.output / "development-summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
