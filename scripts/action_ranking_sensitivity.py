"""Twelve fixed development snapshots; same assumptions, only prefix pace differs."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

from f1_strategy_optimizer.artifacts import write_json
from f1_strategy_optimizer.prefix_quality import assess_prefix
from f1_strategy_optimizer.strategy_exploration import propose_exploration
from f1_strategy_optimizer.workbench_inputs import prefix_assumptions


def read(path):
    return json.loads(
        gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    )


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "output/action-development-v2/ranking-sensitivity.json"
    if output.exists():
        raise ValueError("Preserve existing ranking comparison")
    forecasts = read(root / "output/action-development-v2/frozen-predictions.json")
    selected = read(root / "output/action-development-v2/comparison.json")["selected"]
    rows = []
    for event in ["bahrain", "monaco", "british", "italian"]:
        source = root / "output/freshness-development"
        fs = read(
            source / ("decisions.json.gz" if event == "bahrain" else f"{event}-decisions.json.gz")
        )
        ctx = read(source / f"{event}-prefix-context.json.gz")
        template = read(
            source / ("assumptions.json" if event == "bahrain" else f"{event}-assumptions.json")
        )
        for i in [0, 1, 2] if event == "bahrain" else [0, 7, 12]:
            f = fs[i]
            old = assess_prefix(f, ctx[f["decision_sha256"]])
            new = deepcopy(old)
            for driver in forecasts[event][selected][i]["drivers"]:
                new["drivers"][driver["driver_id"]]["candidate"]["value_seconds"] = driver[
                    "stay_seconds"
                ]
            entry = {
                "event": event,
                "cutoff": f["cutoff"],
                "fixed_case_index": i,
                "driver": "leclerc",
            }
            reports = {}
            for label, quality in [("shipped_v1", old), ("selected_v2", new)]:
                try:
                    assumptions = prefix_assumptions(f, template, "leclerc", quality=quality)
                    # Preserve every manual condition, scenario, pit penalty and opponent policy.
                    report = propose_exploration(f, assumptions)
                    reports[label] = {
                        "status": report["status"],
                        "top3": [
                            {
                                k: x[k]
                                for k in [
                                    "label",
                                    "stops",
                                    "expected_finish_position",
                                    "worst_finish_position",
                                    "expected_elapsed_seconds",
                                ]
                            }
                            for x in report["top3"]
                        ],
                        "model_scope": report["model_scope"],
                        "assumptions_sha256": report["assumptions_sha256"],
                    }
                except (ValueError, KeyError, TypeError) as exc:
                    reports[label] = {"status": "unavailable", "reason": str(exc)}
            entry["reports"] = reports
            paired = all(r.get("top3") for r in reports.values())
            entry["paired"] = paired
            entry["top_choice_changed"] = (
                reports["shipped_v1"]["top3"][0]["stops"]
                != reports["selected_v2"]["top3"][0]["stops"]
                if paired
                else None
            )
            entry["top3_order_changed"] = (
                [x["stops"] for x in reports["shipped_v1"]["top3"]]
                != [x["stops"] for x in reports["selected_v2"]["top3"]]
                if paired
                else None
            )
            rows.append(entry)
    write_json(
        output,
        {
            "cases": rows,
            "fixed_cases": len(rows),
            "paired_available": sum(x["paired"] for x in rows),
            "top_choice_changed": sum(x["top_choice_changed"] is True for x in rows),
            "top3_order_changed": sum(x["top3_order_changed"] is True for x in rows),
            "claim": "Sensitivity of hypothetical subset simulation only; no causal strategy benefit or actual race rank",
        },
    )
    print(output.read_text())


if __name__ == "__main__":
    main()
