"""All 60 bundled Bahrain development selections, without opening outcome data.

Run ``pytest -q -s tests/test_workbench_driver_matrix.py`` to print one JSON status
row per selection. Every slot exercises the real forecast, default assumptions,
and spawned strategy worker. Failed strategies must identify an actually missing
input; an unrelated worker failure, timeout, or silently filled value fails QA.
"""

import builtins
import io
import json
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from f1_strategy_optimizer import workbench
from f1_strategy_optimizer.event_replay import digest

ROOT = Path(__file__).resolve().parents[1]
DATA = workbench.DEFAULT_DATA.resolve()
ALLOWED_INPUTS = {
    DATA / "catalog.json",
    DATA / "decisions.json.gz",
    DATA / "assumptions.json",
    DATA / "bahrain-prefix-context.json.gz",
}
DRIVERS = (
    "albon",
    "alonso",
    "bottas",
    "de_vries",
    "gasly",
    "hamilton",
    "hulkenberg",
    "kevin_magnussen",
    "leclerc",
    "max_verstappen",
    "norris",
    "ocon",
    "perez",
    "piastri",
    "russell",
    "sainz",
    "sargeant",
    "stroll",
    "tsunoda",
    "zhou",
)
SNAPSHOTS = (
    (
        "2023-03-05T15:18:00+00:00",
        "ab977a49e72b0c4bd1fe8580d21e064deb72918e3594b6bbc09cc682b7751ab7",
    ),
    (
        "2023-03-05T15:38:00+00:00",
        "46ceea154e8d618d237547b47476c483b79c02aa819929b80641b7c2ddae46bb",
    ),
    (
        "2023-03-05T16:13:00+00:00",
        "ff38509c97a1ecd4c309afb3c6c52d6e30c54ac44ed402db767023bf6bc98d53",
    ),
)
ABSTENTIONS = (
    {},
    {
        "norris": "segment_warmup_requires_three_completed_laps",
        "perez": "segment_warmup_requires_three_completed_laps",
        "piastri": "missing_or_stale_lap_evidence",
    },
    {
        driver: (
            "missing_or_stale_lap_evidence"
            if driver in {"leclerc", "piastri"}
            else "segment_warmup_requires_three_completed_laps"
        )
        for driver in DRIVERS
    },
)
STRATEGY_REJECTIONS = (
    {"max_verstappen", "perez"},
    {
        "de_vries",
        "leclerc",
        "max_verstappen",
        "norris",
        "ocon",
        "perez",
        "piastri",
        "sainz",
        "tsunoda",
    },
    set(DRIVERS),
)
REQUIRED_CAR_INPUTS = ("gap_seconds", "compound", "tyre_age", "base_lap_time")
REAL_WORKER = workbench._worker


def _check_input_path(file, opened):
    """Fail before opening any non-allowlisted repository data artifact.

    Python source/bytecode and environment metadata are not race inputs. Data
    reads through builtins, pathlib, or gzip are checked in both parent and child.
    Resolving paths also prevents relative-path and symlink allowlist escapes.
    """
    if isinstance(file, int):
        return
    path = Path(os.fsdecode(os.fspath(file))).resolve()
    if not path.is_relative_to(ROOT):
        return
    if path in ALLOWED_INPUTS:
        opened.append(path.name)
        return
    relative = path.relative_to(ROOT)
    if relative.parts[0] in {".venv", ".git", ".pytest_cache"}:
        return
    if path.suffix in {".py", ".pyc"} and relative.parts[0] in {"src", "tests"}:
        return
    raise AssertionError(f"Non-development input read blocked: {relative}")


@contextmanager
def _guard_input_reads():
    opened = []
    original_open, original_io_open = builtins.open, io.open

    def checked_open(file, *args, **kwargs):
        _check_input_path(file, opened)
        return original_open(file, *args, **kwargs)

    def checked_io_open(file, *args, **kwargs):
        _check_input_path(file, opened)
        return original_io_open(file, *args, **kwargs)

    with patch("builtins.open", checked_open), patch("io.open", checked_io_open):
        yield opened


class _GuardedConnection:
    def __init__(self, connection, opened):
        self.connection = connection
        self.opened = opened

    def send(self, result):
        self.connection.send({**result, "qa_worker_input_reads": sorted(set(self.opened))})

    def close(self):
        self.connection.close()


def _guarded_worker(connection, frozen, assumptions):
    """Install the same file boundary inside the actual spawned Python process."""
    with _guard_input_reads() as opened:
        REAL_WORKER(_GuardedConnection(connection, opened), frozen, assumptions)


@pytest.fixture
def guarded_app(monkeypatch):
    with _guard_input_reads() as opened:
        monkeypatch.setattr(workbench, "_worker", _guarded_worker)
        app = workbench.Workbench(
            timeout=10,
            expected_races={"bahrain-2023": "development"},
        )
        catalog = app.catalog()["races"]
        assert [(race["id"], race["partition"]) for race in catalog] == [
            ("bahrain-2023", "development")
        ]
        assert len(app.cases) == 3
        for cutoff, sha256 in SNAPSHOTS:
            race, frozen = app.cases[f"bahrain-2023:{sha256}"]
            assert race["partition"] == "development"
            assert frozen["cutoff"] == cutoff
            assert sorted(car["id"] for car in frozen["state"]["cars"]) == list(DRIVERS)
        yield app, opened
        assert app.revealed == {}
        assert set(opened) <= {path.name for path in ALLOWED_INPUTS}


def _wait(app, key):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = app.job(key)
        if result["status"] != "running":
            return result
        time.sleep(0.01)
    with app.lock:
        app.jobs[key]["cancel"] = True
    pytest.fail("The real default-strategy worker did not reach a terminal state")


@pytest.mark.parametrize("snapshot", range(3), ids=["15-18", "15-38", "16-13"])
@pytest.mark.parametrize("driver", DRIVERS)
def test_all_bundled_development_driver_selections(guarded_app, snapshot, driver):
    app, opened = guarded_app
    cutoff, sha256 = SNAPSHOTS[snapshot]
    case = f"bahrain-2023:{sha256}"
    frozen = app.cases[case][1]
    before_frozen = deepcopy(frozen)
    forecast = app.forecast(case, driver)
    assert forecast == app.forecast(case, driver)
    assert forecast["case"] == case
    assert forecast["decision_sha256"] == sha256
    assert forecast["cutoff"] == cutoff
    assert forecast["mode"] == "historical_replay"
    assert forecast["live_ready"] is False
    assert forecast["model"]["validation_status"] == "failed_acceptance"
    assert forecast["model"]["v2_default"] is False
    assert len(forecast["drivers"]) == 1
    row = forecast["drivers"][0]
    assert row["driver_id"] == driver
    assert row["reason"] == ABSTENTIONS[snapshot].get(driver)
    assert row["prediction_interval"] is None
    assert row["target_start_verified"] is False
    if driver in ABSTENTIONS[snapshot]:
        assert row["status"] == "abstained"
        assert row["predicted_lap_seconds"] is None
        assert row["reason_zh"]
        assert forecast["summary"]["abstained"] == 1
    else:
        assert row["status"] == "conditional_observation_forecast"
        assert row["predicted_lap_seconds"] > 0
        assert forecast["summary"]["available"] == 1
    assert (
        digest({k: v for k, v in forecast.items() if k not in {"case", "report_sha256"}})
        == (forecast["report_sha256"])
    )

    # Include both custom cardinalities: ego-only has no opponent, while an
    # explicit pair has exactly one. These are mapping checks, not alternative
    # simulations or a way to conceal missing default-nearby inputs.
    other = next(candidate for candidate in DRIVERS if candidate != driver)
    for field, selected_ids in (
        ("all", list(DRIVERS)),
        ("custom", [driver]),
        ("custom", [driver, other]),
    ):
        mapped = app.assumptions(case, driver, field, selected_ids)
        assert mapped == app.assumptions(case, driver, field, selected_ids)
        mapped_planning = mapped["planning"]
        assert mapped_planning["ego"] == driver
        assert {car["driver"] for car in mapped_planning["state"]["cars"]} == set(selected_ids)
        assert set(mapped_planning["opponents"]) == set(selected_ids) - {driver}
        assert set(mapped["model_subset"]["drivers"]) == set(selected_ids)
        assert mapped_planning["risk_top_k"] == min(3, len(selected_ids))
        assert mapped["model_subset"]["acknowledged"] is True
        source_cars = {car["id"]: car for car in frozen["state"]["cars"]}
        for car in mapped_planning["state"]["cars"]:
            source = source_cars[car["driver"]]
            assert car["compound"] == source["compound"]["value"]
            assert car["tyre_age"] == source["estimated_completed_tyre_age"]["value"]
            assert car["tyre_inventory"] is None
            if source["gap_seconds"]["value"] is None:
                assert car["gap_seconds"] is None

    assumptions = app.assumptions(case, driver)
    assert assumptions == app.assumptions(case, driver)
    planning = assumptions["planning"]
    assert planning["ego"] == driver
    modeled = planning["state"]["cars"]
    modeled_ids = {car["driver"] for car in modeled}
    assert driver in modeled_ids
    assert 2 <= len(modeled_ids) <= 7
    assert set(planning["opponents"]) == modeled_ids - {driver}
    assert set(assumptions["model_subset"]["drivers"]) == modeled_ids
    assert assumptions["model_subset"]["acknowledged"] is True
    quality = app.quality(case)["drivers"]
    observed = {car["id"]: car for car in frozen["state"]["cars"]}
    missing = {}
    for car in modeled:
        source = observed[car["driver"]]
        assert car["compound"] == source["compound"]["value"]
        assert car["tyre_age"] == source["estimated_completed_tyre_age"]["value"]
        assert car["tyre_inventory"] is None
        if source["gap_seconds"]["value"] is None:
            assert car["gap_seconds"] is None
        if quality[car["driver"]]["candidate"]["value_seconds"] is None:
            assert car["base_lap_time"] is None
        missing_fields = [name for name in REQUIRED_CAR_INPUTS if car[name] is None]
        if missing_fields:
            missing[car["driver"]] = missing_fields
    assert bool(missing) == (driver in STRATEGY_REJECTIONS[snapshot])

    document = {"case": case, "driver": driver, "acknowledged": True, "assumptions": assumptions}
    before_document = deepcopy(document)
    result = _wait(app, app.start(document)["id"])
    assert result["case"] == case and result["driver"] == driver
    assert result["assumptions_sha256"] == digest(assumptions)
    # The solver consumes its supplied frozen prefix, not another data source.
    assert result["qa_worker_input_reads"] == []
    if missing:
        assert result["status"] == "failed", result
        assert result["error"].startswith("ValueError: ")
        assert "缺少间距、配方、胎龄或基础圈时" in result["error"]
        assert "未知值不会自动补齐" in result["error"]
        assert any(f"{missing_driver} 缺少" in result["error"] for missing_driver in missing)
        assert "report" not in result
        strategy_status = "explicit_missing_data_rejection"
    else:
        assert result["status"] == "succeeded", result
        report = result["report"]
        assert report["status"] == "feasible"
        assert report["decision_sha256"] == sha256
        assert report["assumptions_sha256"] == digest(assumptions)
        assert len(report["top3"]) == 3
        assert report["stay_out"]["status"] == "feasible"
        assert set(report["model_scope"]["drivers"]) == modeled_ids
        assert report["model_scope"]["frozen_driver_count"] == 20
        assert report["budget"]["rollouts_executed"] > 0
        strategy_status = "feasible"
    assert document == before_document
    assert frozen == before_frozen
    assert '"actual":' not in json.dumps({"forecast": forecast, "result": result})
    assert set(opened) == {path.name for path in ALLOWED_INPUTS}
    print(
        "MATRIX "
        + json.dumps(
            {
                "cutoff": cutoff,
                "driver": driver,
                "forecast": row["status"],
                "reason": row["reason"],
                "assumptions": "generated_with_missing_values" if missing else "generated_complete",
                "assumption_mappings": 4,
                "strategy": strategy_status,
                "missing": missing,
                "error": result.get("error"),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
    )


@pytest.mark.parametrize(
    "relative",
    [
        "src/f1_strategy_optimizer/workbench_data/reveals.json.gz",
        "src/f1_strategy_optimizer/workbench_data/bahrain-quality-reveals.json.gz",
        "src/f1_strategy_optimizer/workbench_data/evidence.json.gz",
        "examples/whole-race-holdout-lock.json",
        "output/forbidden-outcome.json",
    ],
)
@pytest.mark.parametrize("reader", ["builtins", "pathlib"])
def test_input_guard_blocks_forbidden_reads_before_open(relative, reader):
    path = ROOT / relative
    with _guard_input_reads(), pytest.raises(AssertionError, match="input read blocked"):
        if reader == "pathlib":
            path.read_bytes()
        else:
            with open(path, "rb"):
                pytest.fail("Forbidden data was opened")


def test_matrix_covers_exactly_sixty_slots():
    assert len(SNAPSHOTS) * len(DRIVERS) == 60
    assert [20 - len(rows) for rows in ABSTENTIONS] == [20, 17, 0]
    assert [20 - len(rows) for rows in STRATEGY_REJECTIONS] == [18, 11, 0]
