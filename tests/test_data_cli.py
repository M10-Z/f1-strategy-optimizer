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
