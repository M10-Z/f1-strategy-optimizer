"""All 60 development selections × 8 horizon/time modes, with no outcome reads."""

from itertools import product

import pytest

from f1_strategy_optimizer.workbench import Workbench
from f1_strategy_optimizer.workbench_horizon import build_horizon_report

HORIZONS = ("immediate_post_pit", "first_unstarted_after_confirmation")
CLOCKS = (
    ("historical_approximation", 0),
    ("historical_approximation", 3),
    ("historical_approximation", 180),
    ("recorded_receipts", None),
)


@pytest.fixture(scope="module")
def frozen_cases():
    app = Workbench()
    assert set(app.races) == {"bahrain-2023"}
    assert all(race["partition"] == "development" for race in app.races.values())
    cases = [frozen for _, frozen in app.cases.values()]
    assert len(cases) == 3 and all(len(frozen["state"]["cars"]) == 20 for frozen in cases)
    return cases


@pytest.mark.parametrize("case_index,driver_index", product(range(3), range(20)))
@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("mode,delay", CLOCKS)
def test_every_archive_selection_keeps_operational_predictions_blocked(
    frozen_cases, case_index, driver_index, horizon, mode, delay
):
    frozen = frozen_cases[case_index]
    driver = frozen["state"]["cars"][driver_index]["id"]
    report = build_horizon_report(
        frozen,
        driver,
        {"horizon": horizon, "mode": mode, "assumed_delay_seconds": delay},
    )
    assert report["driver"] == driver
    assert report["decision_sha256"] == frozen["decision_sha256"]
    assert report["selection"]["requested_horizon"] == horizon
    assert report["selection"]["prediction"] is None
    assert report["selection"]["model_eligible"] is False
    assert report["data_label"] == "cached_archive"
