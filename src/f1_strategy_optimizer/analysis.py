"""Time-ordered validation and explicit counterfactual scenario comparisons."""

from dataclasses import replace

import numpy as np

from .config import RaceConfig
from .models import ModelParameters, TyreModel, fit_model, validate_laps
from .solver import evaluate_strategy, solve


def backtest(
    df, holdout_year: int | None = None, parameters: ModelParameters | None = None
) -> dict:
    """Train strictly before the held-out season. Never fit on held-out lap times.

    This evaluates lap-time predictions, not a counterfactual race win or ranking.
    """
    data = validate_laps(df)
    years = sorted(int(year) for year in data.Year.unique())
    year = holdout_year if holdout_year is not None else years[-1]
    train, test = data[data.Year < year], data[data.Year == year]
    if train.empty or test.empty:
        raise ValueError("Backtest requires prior training seasons and a nonempty held-out year")
    model = fit_model(train, parameters)
    metrics = {}
    for compound in sorted(test.Compound.unique()):
        part = test[test.Compound == compound]
        if compound not in model.compounds:
            metrics[compound] = {"status": "no_training_model", "samples": len(part)}
            continue
        target = (
            part.LapTimeSeconds + model.parameters.fuel_gain_per_lap * (part.LapNumber - 1)
        ).to_numpy()
        predictions = np.array(
            [
                model.predict(compound, int(age), model.parameters.reference_temp)
                for age in part.TyreLife
            ]
        )
        error = predictions - target
        curve = model.curves[compound]
        metrics[compound] = {
            "status": "evaluated",
            "samples": len(part),
            "mae_seconds": float(np.abs(error).mean()),
            "rmse_seconds": float(np.sqrt(np.mean(error**2))),
            "bias_seconds": float(error.mean()),
            "outside_training_age_range": int(
                (
                    (part.TyreLife < curve.min_observed_age)
                    | (part.TyreLife > curve.max_observed_age)
                ).sum()
            ),
        }
    evaluated_samples = sum(
        metric["samples"] for metric in metrics.values() if metric["status"] == "evaluated"
    )
    future = data[data.Year > year]
    return {
        "training_years": sorted(int(y) for y in train.Year.unique()),
        "holdout_year": year,
        "data_split": {
            "training_samples": len(train),
            "holdout_samples": len(test),
            "ignored_future_samples": len(future),
            "ignored_future_years": sorted(int(y) for y in future.Year.unique()),
        },
        "coverage": {
            "evaluated_samples": evaluated_samples,
            "unmodeled_samples": len(test) - evaluated_samples,
        },
        "compounds": metrics,
        "model": model.to_dict(),
        "interpretation": "Held-out lap prediction errors at reference temperature with "
        "fixed fuel prior; not validation of counterfactual race outcomes",
    }


def compare_scenarios(model: TyreModel, config: RaceConfig) -> list[dict]:
    """Reoptimize starting compound, pit loss, temperature and degradation priors."""
    scenarios = [("baseline", config, model)]
    for compound in model.compounds:
        scenarios.append((f"start-{compound}", replace(config, starting_compound=compound), model))
    for change in (-5.0, 5.0):
        scenarios.append(
            (
                f"pit-loss-{max(0, config.pit_loss + change):g}s",
                replace(config, pit_loss=max(0, config.pit_loss + change)),
                model,
            )
        )
    for change in (-10.0, 10.0):
        scenarios.append(
            (
                f"temperature-{config.track_temp + change:g}C",
                replace(config, track_temp=config.track_temp + change),
                model,
            )
        )
    for scale in (0.5, 1.5):
        parameters = replace(
            model.parameters,
            min_degradation={
                c: rate * scale for c, rate in model.parameters.min_degradation.items()
            },
        )
        scenarios.append(
            (
                f"degradation-floor-x{scale:g}",
                config,
                TyreModel(dict(model.curves), parameters, model.diagnostics),
            )
        )
    if config.total_laps > 1:
        lap = max(1, config.total_laps // 2)
        scenario = replace(
            config, pit_loss_overrides={**config.pit_loss_overrides, lap: config.pit_loss * 0.5}
        )
        scenarios.append((f"known-reduced-pit-loss-lap-{lap}", scenario, model))
    baseline = solve(model, config)
    results = []
    for name, scenario, scenario_model in scenarios:
        optimum = solve(scenario_model, scenario)
        # Evaluate baseline in the same scenario, so differences are interpretable.
        reference_config = replace(scenario, starting_compound=None)
        baseline_cost = evaluate_strategy(
            scenario_model, reference_config, baseline.compounds_used, baseline.stint_lengths
        ).total_time
        results.append(
            {
                "scenario": name,
                **optimum.to_dict(),
                "baseline_schedule_time_in_scenario": baseline_cost,
                "difference_vs_baseline_schedule_seconds": optimum.total_time - baseline_cost,
                "pit_loss": scenario.pit_loss,
                "track_temp": scenario.track_temp,
                "pit_loss_overrides": scenario.pit_loss_overrides,
                "min_degradation": scenario_model.parameters.min_degradation,
            }
        )
    return results
