from dataclasses import replace

import numpy as np
import pytest

from f1_strategy_optimizer.analysis import backtest, compare_scenarios
from f1_strategy_optimizer.config import RaceConfig
from f1_strategy_optimizer.models import (
    ModelParameters,
    TyreCurve,
    TyreModel,
    fit_model,
    synthetic_laps,
)


def test_grouped_fit_recovers_synthetic_slopes_and_no_cross_model_state():
    data = synthetic_laps()
    first = fit_model(data)
    before = first.predict("SOFT", 10)
    changed = data.copy()
    changed["LapTimeSeconds"] += 10
    second = fit_model(changed)
    assert first.predict("SOFT", 10) == before
    assert second.predict("SOFT", 10) == pytest.approx(before + 10)
    assert first.curves["SOFT"].linear == pytest.approx(0.09, abs=0.015)
    assert first.curves["SOFT"].quadratic == pytest.approx(0.004, abs=0.001)


def test_holdout_is_not_used_for_training():
    data = synthetic_laps()
    original = backtest(data)
    data.loc[data.Year == 2025, "LapTimeSeconds"] += 100
    perturbed = backtest(data)
    assert original["model"] == perturbed["model"]
    assert original["training_years"] == [2022, 2023, 2024]
    assert perturbed["compounds"]["SOFT"]["mae_seconds"] > 90
    with pytest.raises(ValueError):
        backtest(data, 2022)


def test_backtest_reports_split_and_coverage_without_using_future_laps():
    data = synthetic_laps()
    data = data[~((data.Year < 2024) & (data.Compound == "SOFT"))].copy()
    original = backtest(data, 2024)
    assert original["data_split"] == {
        "training_samples": 288,
        "holdout_samples": 216,
        "ignored_future_samples": 216,
        "ignored_future_years": [2025],
    }
    assert original["coverage"] == {"evaluated_samples": 144, "unmodeled_samples": 72}
    assert original["compounds"]["SOFT"] == {"status": "no_training_model", "samples": 72}
    data.loc[data.Year == 2025, "LapTimeSeconds"] += 100
    assert backtest(data, 2024) == original


def test_monotone_envelope_and_temperature_only_affects_degradation():
    m = TyreModel({"SOFT": TyreCurve(100, 2, -0.2)})
    predictions = [m.predict("SOFT", age) for age in range(1, 50)]
    assert np.all(np.diff(predictions) >= 0)
    assert m.predict("SOFT", 1, 10) == m.predict("SOFT", 1, 60) == 100
    assert m.predict("SOFT", 10, 60) > m.predict("SOFT", 10, 10)


@pytest.mark.parametrize("kind", ["empty", "duplicate", "nan", "missing", "no_variation"])
def test_reject_bad_datasets(kind):
    data = synthetic_laps()
    if kind == "empty":
        data = data.iloc[:0]
    elif kind == "duplicate":
        import pandas as pd

        data = pd.concat([data, data.iloc[:1]])
    elif kind == "nan":
        data.loc[0, "LapTimeSeconds"] = np.nan
    elif kind == "missing":
        data = data.drop(columns="Stint")
    else:
        data["TyreLife"] = 1
    with pytest.raises(ValueError):
        fit_model(data)


def test_scenario_gains_use_same_environment():
    m = fit_model(synthetic_laps())
    rows = compare_scenarios(m, RaceConfig(total_laps=12))
    assert len(rows) == 11
    assert rows[0]["difference_vs_baseline_schedule_seconds"] == pytest.approx(0)
    for row in rows:
        if not row["scenario"].startswith("start-"):
            assert row["difference_vs_baseline_schedule_seconds"] <= 1e-8


def test_parameters_validated_and_no_forced_order_by_default():
    with pytest.raises(ValueError):
        replace(ModelParameters(), fuel_gain_per_lap=float("nan"))
    assert ModelParameters().compound_gap == 0
