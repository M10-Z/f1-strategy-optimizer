import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from f1_strategy_optimizer.cli import main
from f1_strategy_optimizer.data import clean_session_laps, fetch_cycle_data
from f1_strategy_optimizer.models import synthetic_laps


def raw_laps():
    data = pd.DataFrame(
        {
            "LapNumber": range(1, 7),
            "LapTime": pd.to_timedelta([90] * 6, unit="s"),
            "TyreLife": range(1, 7),
            "Compound": ["SOFT"] * 6,
            "Driver": ["A"] * 6,
            "Stint": [1] * 6,
            "PitInTime": pd.to_timedelta([None] * 6),
            "PitOutTime": pd.to_timedelta([None] * 6),
            "IsAccurate": [True] * 6,
            "TrackStatus": ["1"] * 6,
            "Deleted": [False] * 6,
        }
    )
    data.loc[1, "PitInTime"] = pd.Timedelta(seconds=1)
    data.loc[2, "PitOutTime"] = pd.Timedelta(seconds=1)
    data.loc[3, "TrackStatus"] = "14"
    data.loc[4, "IsAccurate"] = False
    return data


def test_metadata_cleaning_preserves_valid_laps():
    result = clean_session_laps(raw_laps(), 2025, "Test")
    assert result.LapNumber.tolist() == [1, 6]
    assert result.attrs["cleaning"]["removed_rows"] == 4


def test_fetch_initializes_cache_and_partial_failures_are_explicit(tmp_path):
    session = Mock()
    session.laps = raw_laps()
    api = Mock()
    api.get_session.side_effect = [session, RuntimeError("offline")]
    with patch.dict(sys.modules, {"fastf1": api}):
        data = fetch_cycle_data(
            2024, 2025, cache_dir=tmp_path / "new-cache", allow_partial=True, offline=True
        )
        api.Cache.offline_mode.assert_called_once_with(True)
        assert (tmp_path / "new-cache").is_dir()
        assert data.attrs["loaded_years"] == [2024]
        assert "2025" in data.attrs["failed_years"]
        api.get_session.side_effect = RuntimeError("offline")
        with pytest.raises(RuntimeError, match="Failed to load"):
            fetch_cycle_data(2024, 2025, cache_dir=tmp_path / "new-cache")


def test_import_has_no_disk_side_effects(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", "import f1_strategy_optimizer; import f1_strategy_optimizer.data"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_offline_cli_exports_and_refuses_overwrite(tmp_path):
    output = tmp_path / "中文结果"
    with patch("f1_strategy_optimizer.cli.fetch_cycle_data", side_effect=AssertionError("network")):
        assert (
            main(
                [
                    "demo",
                    "--laps",
                    "12",
                    "--compare",
                    "--holdout-year",
                    "2025",
                    "--output-dir",
                    str(output),
                ]
            )
            == 0
        )
    result = json.loads((output / "strategy.json").read_text(encoding="utf-8"))
    assert sum(result["stint_lengths"]) == 12
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["source"] == "synthetic"
    assert manifest["model_role"] == "exploratory_all_input"
    assert manifest["model"]["diagnostics"]["years"] == [2022, 2023, 2024, 2025]
    validation = json.loads((output / "backtest.json").read_text(encoding="utf-8"))
    assert validation["model"]["diagnostics"]["years"] == [2022, 2023, 2024]
    assert (output / "strategies.png").stat().st_size > 1000
    before = (output / "strategy.json").read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["demo", "--output-dir", str(output)])
    assert exc.value.code == 2
    assert (output / "strategy.json").read_bytes() == before


def test_cli_invalid_rules_fail_before_fetch(tmp_path):
    rule = tmp_path / "bad.json"
    rule.write_text('{"min_compounds": 0}', encoding="utf-8")
    with patch("f1_strategy_optimizer.cli.fetch_cycle_data", side_effect=AssertionError("network")):
        with pytest.raises(SystemExit) as exc:
            main(["optimize", "--rules", str(rule)])
        assert exc.value.code == 2


@pytest.mark.parametrize("content", ["[]", '{"min_compounds": null}'])
def test_cli_rejects_malformed_rule_structure(tmp_path, content):
    path = tmp_path / "invalid.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["demo", "--rules", str(path), "--output-dir", str(tmp_path / "results")])
    assert exc.value.code == 2


@pytest.mark.parametrize("holdout_year", [None, 2024])
def test_backtest_exports_only_prior_year_model(tmp_path, holdout_year):
    data = synthetic_laps()
    source = tmp_path / "laps.csv"
    output = tmp_path / "validation"
    data.to_csv(source, index=False)
    args = ["backtest", "--csv", str(source), "--output-dir", str(output)]
    if holdout_year is not None:
        args += ["--holdout-year", str(holdout_year)]
    with patch("f1_strategy_optimizer.cli.plot_model") as plot:
        assert main(args) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    validation = json.loads((output / "backtest.json").read_text())
    assert manifest["model"] == validation["model"]
    assert plot.call_args.args[0].to_dict() == validation["model"]
    assert manifest["model_role"] == "holdout_training"
    assert validation["holdout_year"] == (holdout_year or 2025)
    assert len(pd.read_csv(output / "laps.csv")) == len(data)
    assert not (output / "strategy.json").exists()


def test_backtest_handles_sparse_unseen_holdout_compound(tmp_path, capsys):
    data = synthetic_laps()
    # SOFT is observed only once in the test year: evaluation must disclose
    # missing training coverage, without trying to fit that held-out compound.
    train = data[(data.Year < 2025) & (data.Compound != "SOFT")]
    test = data[(data.Year == 2025) & (data.Compound == "SOFT")].iloc[:1]
    source = tmp_path / "laps.csv"
    pd.concat([train, test]).to_csv(source, index=False)
    output = tmp_path / "validation"
    assert main(["backtest", "--csv", str(source), "--output-dir", str(output)]) == 0
    validation = json.loads((output / "backtest.json").read_text())
    assert validation["compounds"]["SOFT"] == {"status": "no_training_model", "samples": 1}
    assert validation["coverage"] == {"evaluated_samples": 0, "unmodeled_samples": 1}
    assert "Evaluated held-out laps: 0/1" in capsys.readouterr().out
    manifest = json.loads((output / "manifest.json").read_text())
    assert set(manifest["model"]["curves"]) == {"MEDIUM", "HARD"}
    assert (output / "model.png").stat().st_size > 1000


def test_backtest_export_model_is_invariant_to_heldout_and_future_times(tmp_path):
    data = synthetic_laps()
    exported = []
    for label, delta in (("original", 0), ("perturbed", 100)):
        changed = data.copy()
        changed.loc[changed.Year >= 2024, "LapTimeSeconds"] += delta
        source = tmp_path / f"{label}.csv"
        changed.to_csv(source, index=False)
        output = tmp_path / label
        with patch("f1_strategy_optimizer.cli.plot_model"):
            assert (
                main(
                    [
                        "backtest",
                        "--csv",
                        str(source),
                        "--holdout-year",
                        "2024",
                        "--output-dir",
                        str(output),
                    ]
                )
                == 0
            )
        exported.append(
            (
                json.loads((output / "manifest.json").read_text()),
                json.loads((output / "backtest.json").read_text()),
            )
        )
    assert exported[0][0]["model"] == exported[1][0]["model"]
    assert exported[1][1]["compounds"]["SOFT"]["mae_seconds"] > 90


def test_csv_export_normalizes_compounds_and_preserves_source_hash(tmp_path):
    import hashlib

    data = synthetic_laps()
    data["Compound"] = data.Compound.str.lower().map(lambda value: f" {value} ")
    source = tmp_path / "laps.csv"
    data.to_csv(source, index=False)
    output = tmp_path / "validation"
    with patch("f1_strategy_optimizer.cli.plot_model"):
        assert main(["backtest", "--csv", str(source), "--output-dir", str(output)]) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        manifest["normalized_laps_sha256"]
        == hashlib.sha256((output / "laps.csv").read_bytes()).hexdigest()
    )
    assert set(pd.read_csv(output / "laps.csv").Compound) == {"SOFT", "MEDIUM", "HARD"}


@pytest.mark.parametrize("year", [2022, 2026])
def test_backtest_invalid_split_leaves_no_outputs(tmp_path, year):
    source = tmp_path / "laps.csv"
    synthetic_laps().to_csv(source, index=False)
    output = tmp_path / "validation"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "backtest",
                "--csv",
                str(source),
                "--holdout-year",
                str(year),
                "--output-dir",
                str(output),
            ]
        )
    assert exc.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("metadata", ["missing", "unknown"])
def test_cleaning_requires_known_deleted_flags(metadata):
    data = raw_laps()
    if metadata == "unknown":
        data["Deleted"] = pd.Series([False] * len(data), dtype="boolean")
        data.loc[0, "Deleted"] = pd.NA
    elif "Deleted" in data:
        data = data.drop(columns="Deleted")
    with pytest.raises(ValueError, match="race control messages"):
        clean_session_laps(data, 2024, "Test")


def test_fetch_loads_messages_for_deleted_lap_detection(tmp_path):
    session = Mock()
    session.laps = raw_laps()
    session.laps["Deleted"] = False
    session.laps.loc[0, "Deleted"] = True
    api = Mock()
    api.get_session.return_value = session
    with patch.dict(sys.modules, {"fastf1": api}):
        result = fetch_cycle_data(2024, 2024, cache_dir=tmp_path / "cache")
    session.load.assert_called_once_with(laps=True, telemetry=False, weather=True, messages=True)
    assert result.LapNumber.tolist() == [6]


def test_cleaning_reports_overlapping_metadata_and_separate_numeric_exclusions():
    data = raw_laps()
    extra = data.iloc[[0]].copy()
    extra["LapNumber"] = 7
    data = pd.concat([data, extra], ignore_index=True)
    data.loc[0, "LapTime"] = pd.NaT
    data.loc[1, "Deleted"] = True  # Already excluded as pit-in; do not double count removed_rows.
    result = clean_session_laps(data, 2024, "Test")
    assert result.LapNumber.tolist() == [6, 7]
    cleaning = result.attrs["cleaning"]
    assert cleaning["input_rows"] == 7
    assert cleaning["kept_rows"] == 2
    assert cleaning["removed_rows"] == 5
    assert cleaning["excluded_by_metadata_reason"] == {
        "pit_in": 1,
        "pit_out": 1,
        "inaccurate_or_unknown": 1,
        "non_green_or_unknown": 1,
        "unsupported_compound": 0,
        "deleted": 1,
    }
    assert cleaning["invalid_numeric_after_metadata"] == 1
    assert cleaning["deleted_flags_verified"] is True


def test_fetch_reports_unknown_deleted_flags_as_failed_year(tmp_path):
    unavailable, available = Mock(), Mock()
    unavailable.laps = raw_laps().drop(columns="Deleted")
    available.laps = raw_laps()
    api = Mock()
    api.get_session.side_effect = [unavailable, available]
    with patch.dict(sys.modules, {"fastf1": api}):
        data = fetch_cycle_data(2023, 2024, cache_dir=tmp_path / "cache", allow_partial=True)
    assert data.attrs["loaded_years"] == [2024]
    assert "race control messages" in data.attrs["failed_years"]["2023"]
