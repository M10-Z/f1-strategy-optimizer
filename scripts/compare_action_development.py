"""Exactly two preregistered candidates on four observed development events."""

import gzip
import hashlib
import json
import statistics
from pathlib import Path

from build_freshness_development import load_development

from f1_strategy_optimizer.action_evaluation import score_prediction, summarize
from f1_strategy_optimizer.action_model import (
    CANDIDATES,
    completed_pit_residuals,
    fit_pit_prior,
    predict,
)
from f1_strategy_optimizer.artifacts import write_json
from f1_strategy_optimizer.prefix_quality import assess_prefix

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("bahrain", "monaco", "british", "italian")


def read(path):
    return json.loads(
        gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    )


def main():
    out = ROOT / "output/action-development-v2"
    if out.exists():
        raise ValueError("Development comparison already exists; preserve bounded comparison")
    out.mkdir()
    data, pits = {}, {}
    for event in EVENTS:
        root = ROOT / "output/freshness-development"
        frozen = read(
            root / ("decisions.json.gz" if event == "bahrain" else f"{event}-decisions.json.gz")
        )
        contexts = read(root / f"{event}-prefix-context.json.gz")
        archive = load_development(event, ROOT.parent / "real-data")
        data[event] = (frozen, contexts, archive)
        latest = frozen[-1]
        pits[event] = completed_pit_residuals(
            latest["state"]["cars"], latest["cutoff"], latest["state"]["visible_race_control"]
        )
    forecasts, priors = {}, {}
    for event in EVENTS:
        training = [e for e in EVENTS if e != event]
        priors[event] = fit_pit_prior([x for e in training for x in pits[e]], training)
        frozen, contexts, _ = data[event]
        forecasts[event] = {
            candidate: [
                predict(f, contexts[f["decision_sha256"]], candidate, priors[event]) for f in frozen
            ]
            for candidate in CANDIDATES
        }
    write_json(out / "frozen-predictions.json", forecasts)
    write_json(out / "fold-priors.json", priors)
    write_json(
        out / "prediction-receipt.json",
        {
            "before_scoring": True,
            "sha256": hashlib.sha256((out / "frozen-predictions.json").read_bytes()).hexdigest(),
            "candidate_count": 2,
            "Belgium_accessed": False,
        },
    )
    results, selection = {}, {}
    for candidate in CANDIDATES:
        results[candidate] = {}
        all_rows = []
        for event in EVENTS:
            frozen, contexts, archive = data[event]
            rows = []
            for pred, f in zip(forecasts[event][candidate], frozen):
                rows.extend(
                    score_prediction(
                        pred, f, assess_prefix(f, contexts[f["decision_sha256"]]), archive
                    )
                )
            results[candidate][event] = summarize(rows)
            write_json(out / f"{candidate}-{event}-rows.json", rows)
            all_rows.extend(rows)
        summaries = list(results[candidate].values())
        ratio = statistics.mean(
            s["paired_candidate"]["mae"] / s["paired_baseline"]["mae"] for s in summaries
        )
        tail_ratio = statistics.mean(
            s["paired_candidate"]["p95"] / s["paired_baseline"]["p95"] for s in summaries
        )
        coverage = sum(s["all_scored"]["n"] for s in summaries) / sum(
            s["applicable_slots"] for s in summaries
        )
        checks = {
            "no_event_coverage_loss_vs_v1": all(
                s["coverage"] >= s["v1_coverage"] for s in summaries
            ),
            "pooled_coverage_at_least_half": coverage >= 0.5,
            "macro_p95_ratio_at_most_1_10": tail_ratio <= 1.1,
            "macro_mae_not_worse": ratio <= 1.0,
        }
        selection[candidate] = {
            "macro_paired_mae_ratio": ratio,
            "macro_paired_p95_ratio": tail_ratio,
            "pooled_coverage": coverage,
            "checks": checks,
            "eligible": all(checks.values()),
        }
    eligible = [c for c in CANDIDATES if selection[c]["eligible"]]
    selected = (
        min(eligible, key=lambda c: selection[c]["macro_paired_mae_ratio"]) if eligible else None
    )
    if (
        selected
        and "guarded_last" in eligible
        and selection["guarded_last"]["macro_paired_mae_ratio"]
        <= selection[selected]["macro_paired_mae_ratio"] + 0.01
    ):
        selected = "guarded_last"
    final_prior = fit_pit_prior([x for event in EVENTS for x in pits[event]], list(EVENTS))
    write_json(
        out / "comparison.json",
        {
            "results": results,
            "selection": selection,
            "selected": selected,
            "candidate_budget_exhausted": True,
        },
    )
    write_json(out / "selected-prior.json", final_prior)
    print(
        json.dumps(
            {"selection": selection, "selected": selected, "final_prior": final_prior}, indent=2
        )
    )


if __name__ == "__main__":
    main()
