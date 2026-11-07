"""Offline, paired exact-output comparison with a saved pre-change solver.

Run from the checkout, passing an explicitly saved reference source file. No
race data, held-out scores or network access are used by this benchmark.
"""

import argparse
import hashlib
import importlib.util
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1_strategy_optimizer import solver  # noqa: E402
from f1_strategy_optimizer.config import RaceConfig, RuleSet  # noqa: E402
from f1_strategy_optimizer.models import fit_model, synthetic_laps  # noqa: E402


class TableModel:
    """Positive arbitrary costs, including irregular and exactly tied inputs."""

    def __init__(self, compounds, costs):
        self.compounds, self.costs = compounds, costs

    def predict(self, compound, age, track_temp=35.0):
        return self.costs[compound][age - 1]


def load_reference(path):
    name = "f1_strategy_optimizer._solver_benchmark_reference"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def outcome(function, model, config):
    try:
        return {"status": "feasible", "strategy": function(model, config).to_dict()}
    except ValueError as exc:
        return {"status": type(exc).__name__, "message": str(exc)}


def differential_cases(reference, count):
    rng = random.Random(20261107)
    feasible = infeasible = 0
    for index in range(count):
        laps = rng.randint(1, 18)
        compounds = tuple(rng.sample(("Z", "A", "WET", "HARD"), rng.randint(1, 4)))
        tied = index % 3 == 0
        costs = {
            c: [
                rng.choice((1.0, 1.0 + 2**-52, 2.0)) if tied else rng.uniform(1, 100)
                for _ in range(laps)
            ]
            for c in compounds
        }
        model = TableModel(compounds, costs)
        config = RaceConfig(
            total_laps=laps,
            pit_loss=rng.choice((0.0, 24.0, 1e16)),
            max_tyre_age=rng.randint(1, laps),
            compound_age_limits={c: rng.randint(1, laps) for c in compounds},
            rules=RuleSet(
                min_compounds=rng.randint(1, len(compounds)),
                min_stints=rng.randint(1, laps),
            ),
            starting_compound=rng.choice((None, *compounds)),
            pit_loss_overrides={
                lap: rng.choice((0.0, 0.5, 40.0)) for lap in range(1, laps) if rng.random() < 0.2
            },
        )
        before = outcome(reference.solve, model, config)
        after = outcome(solver.solve, model, config)
        if before != after:
            raise AssertionError(f"Full output mismatch for seeded case {index}")
        feasible += before["status"] == "feasible"
        infeasible += before["status"] != "feasible"
    return {"cases": count, "exact_matches": count, "feasible": feasible, "infeasible": infeasible}


def timed_case(reference, model, name, config, repeats):
    before = reference.solve(model, config).to_dict()
    after = solver.solve(model, config).to_dict()
    if before != after:
        raise AssertionError(f"Benchmark output mismatch: {name}")
    timings = {"before": [], "after": []}
    functions = {"before": reference.solve, "after": solver.solve}
    for repeat in range(repeats + 2):
        order = ("before", "after") if repeat % 2 == 0 else ("after", "before")
        for label in order:
            start = time.perf_counter()
            result = functions[label](model, config).to_dict()
            elapsed = time.perf_counter() - start
            if result != before:
                raise AssertionError(f"Repeated output mismatch: {name}")
            if repeat >= 2:
                timings[label].append(elapsed)
    medians = {key: statistics.median(values) for key, values in timings.items()}
    return {
        "name": name,
        "laps": config.total_laps,
        "minimum_stints": config.rules.min_stints,
        "exact_output_match": True,
        "samples_seconds": timings,
        "median_seconds": medians,
        "median_speedup": medians["before"] / medians["after"],
        "strategy": after,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=400)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if args.cases < 1 or args.repeats < 1:
        parser.error("cases and repeats must be positive")
    if args.output.exists():
        parser.error("Output exists; select a new file")
    reference = load_reference(args.reference)
    comparisons = differential_cases(reference, args.cases)
    model = fit_model(synthetic_laps(seed=42))
    cases = [
        ("synthetic_57_laps", RaceConfig()),
        ("synthetic_78_laps", RaceConfig(total_laps=78)),
        ("synthetic_57_laps_12_stints", RaceConfig(rules=RuleSet(min_stints=12))),
    ]
    report = {
        "scope": "Deterministic solver runtime, not forecast accuracy or real strategy gains",
        "data": "Original synthetic_laps(seed=42), plus seeded arbitrary positive cost tables",
        "python": sys.version,
        "platform": platform.platform(),
        "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(Path(solver.__file__).read_bytes()).hexdigest(),
        "comparison": comparisons,
        "timing_protocol": "Two warmups then alternating before/after order; same process/model",
        "benchmarks": [timed_case(reference, model, n, c, args.repeats) for n, c in cases],
        "limits": "One local machine; timings are noisy and not an end-to-end workbench benchmark",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
