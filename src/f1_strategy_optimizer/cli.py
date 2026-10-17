"""Offline-first command line interface with UTF-8 machine-readable exports."""

import argparse
import csv
import hashlib
import json
import platform
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from .analysis import backtest, compare_scenarios
from .config import RaceConfig, RuleSet
from .data import fetch_cycle_data
from .models import ModelParameters, fit_model, synthetic_laps
from .plotting import plot_model, plot_strategies
from .solver import solve


def _versions() -> dict:
    result = {"python": platform.python_version()}
    for name in ("f1-strategy-optimizer", "numpy", "pandas", "matplotlib", "fastf1"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not installed"
    return result


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Model-relative F1 strategy research (offline default)"
    )
    parser.add_argument(
        "command", nargs="?", choices=["demo", "optimize", "backtest", "menu"], default="demo"
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    parser.add_argument("--csv", type=Path, help="Normalized input laps; no network access")
    parser.add_argument("--track", default="Bahrain")
    parser.add_argument("--start", type=int, default=2022)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--holdout-year", type=int)
    parser.add_argument("--laps", type=int, default=57)
    parser.add_argument("--pit-loss", type=float, default=24.0)
    parser.add_argument("--temp", type=float, default=35.0)
    parser.add_argument("--max-tyre-age", type=int, default=50)
    parser.add_argument("--starting-compound", choices=["SOFT", "MEDIUM", "HARD"])
    parser.add_argument("--rules", type=Path, help="JSON RuleSet with explicit research scope")
    parser.add_argument(
        "--scenario", type=Path, help="JSON pit_loss_overrides / compound_age_limits"
    )
    parser.add_argument("--model-parameters", type=Path, help="JSON explicit fitting priors")
    parser.add_argument("--cache-dir", type=Path, default=Path("cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/run"))
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--offline", action="store_true", help="FastF1 cache only; no data requests"
    )
    parser.add_argument(
        "--compare", action="store_true", help="Export sensitivity and pit-loss scenarios"
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "menu":
        from .terminal import main as menu

        return menu()
    try:

        def read(path):
            value = json.loads(path.read_text(encoding="utf-8-sig")) if path else {}
            if not isinstance(value, dict):
                raise ValueError("Configuration files must contain JSON objects")
            return value

        output = args.output_dir.expanduser()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output directory is not empty; choose a new --output-dir")
        rules = RuleSet(**read(args.rules))
        parameters = ModelParameters(**read(args.model_parameters))
        scenario = read(args.scenario)
        if set(scenario) - {"pit_loss_overrides", "compound_age_limits"}:
            raise ValueError("Unknown scenario keys")
        overrides = scenario.get("pit_loss_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("pit_loss_overrides must be an object")
        if any(str(int(key)) != str(key) for key in overrides):
            raise ValueError("Override laps must be canonical integer strings")
        scenario["pit_loss_overrides"] = {int(k): v for k, v in overrides.items()}
        config = RaceConfig(
            args.laps,
            args.pit_loss,
            args.temp,
            args.max_tyre_age,
            args.starting_compound,
            rules,
            **scenario,
        )
        if args.csv:
            data = pd.read_csv(args.csv)
            provenance = {
                "source": "user CSV",
                "filename": args.csv.name,
                "sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
            }
            data.attrs["source"] = "user CSV (provenance not independently verified)"
        elif args.command == "demo":
            data = synthetic_laps(args.seed)
            provenance = dict(data.attrs)
        else:
            data = fetch_cycle_data(
                args.start,
                args.end,
                args.track,
                cache_dir=args.cache_dir,
                allow_partial=args.allow_partial,
                offline=args.offline,
            )
            provenance = dict(data.attrs)
        model = fit_model(data, parameters)
        result = solve(model, config) if args.command != "backtest" else None
        validation = None
        if args.command == "backtest" or args.holdout_year is not None:
            validation = backtest(data, args.holdout_year, parameters)
        comparisons = compare_scenarios(model, config) if args.compare and result else []
        # Do not silently overwrite another run, including a partial failed export.
        output.mkdir(parents=True, exist_ok=True)
        data.to_csv(output / "laps.csv", index=False, encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "source": provenance,
            "versions": _versions(),
            "race": asdict(config),
            "model": model.to_dict(),
            "normalized_laps_sha256": hashlib.sha256(
                (output / "laps.csv").read_bytes()
            ).hexdigest(),
            "scope": "Deterministic dry-tyre research; not full sporting compliance",
            "extrapolation": {
                c: (
                    min(config.total_laps, config.age_limit(c)) > curve.max_observed_age
                    or curve.min_observed_age > 1
                )
                for c, curve in model.curves.items()
            },
        }
        write_json(output / "manifest.json", manifest)
        if result:
            write_json(output / "strategy.json", result.to_dict())
            with (output / "strategy.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["stint", "compound", "start_lap", "end_lap", "length"])
                start = 1
                for i, (compound, length) in enumerate(
                    zip(result.compounds_used, result.stint_lengths), 1
                ):
                    writer.writerow([i, compound, start, start + length - 1, length])
                    start += length
            print(result)
        if validation:
            write_json(output / "backtest.json", validation)
            print(f"Held-out season: {validation['holdout_year']}")
        plot_model(model, output / "model.png", min(config.total_laps, config.max_tyre_age))
        if comparisons:
            write_json(output / "scenarios.json", comparisons)
            plot_strategies(comparisons, output / "strategies.png", source=provenance["source"])
        print(f"Source: {provenance['source']} | Results: {output.resolve()}")
        return 0
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
