import json
from types import SimpleNamespace

import pandas as pd
import pytest

from f1_strategy_optimizer.driver_analysis import (
    AnalysisRequest,
    actual_schedule,
    analyze_driver,
    fit_driver_model,
    resolve_driver,
    save_analysis,
    select_event,
)
from f1_strategy_optimizer.models import synthetic_laps


def roster():
    return pd.DataFrame(
        [
            {
                "FullName": "Driver One",
                "Abbreviation": "SYN0",
                "DriverNumber": "16",
                "TeamName": "Example Team",
            },
            {
                "FullName": "Driver Two",
                "Abbreviation": "SYN1",
                "DriverNumber": "55",
                "TeamName": "Example Team",
            },
            {
                "FullName": "Driver Three",
                "Abbreviation": "SYN2",
                "DriverNumber": "4",
                "TeamName": "Other Team",
            },
            {
                "FullName": "Driver Four",
                "Abbreviation": "SYN3",
                "DriverNumber": "81",
                "TeamName": "Other Team",
            },
        ]
    )


def calendar(year):
    return pd.DataFrame(
        [
            {
                "RoundNumber": 1,
                "EventName": "Example Grand Prix",
                "Country": "Example",
                "Location": "Example Circuit",
                "Session1": "Practice 1",
                "Session1DateUtc": f"{year}-03-01 10:00:00",
                "Session5": "Race",
                "Session5DateUtc": f"{year}-03-03 10:00:00",
            }
        ]
    )


class Provider:
    def __init__(self):
        self.calls = []

    def schedule(self, year):
        return calendar(year)

    def load(self, year, round_number, kind="R"):
        self.calls.append((year, kind))
        data = synthetic_laps()
        data = data[data.Year == year].copy()
        data["LapTime"] = pd.to_timedelta(data.LapTimeSeconds, unit="s")
        data["PitInTime"] = pd.NaT
        data["PitOutTime"] = pd.NaT
        data["IsAccurate"] = True
        data["TrackStatus"] = "1"
        data["Deleted"] = False
        return SimpleNamespace(laps=data, results=roster())


@pytest.mark.parametrize("query", ["Driver One", "driver one", "SYN0", "16"])
def test_resolve_names_numbers_and_membership(query):
    assert resolve_driver(roster(), "example team", query)["Abbreviation"] == "SYN0"
    with pytest.raises(ValueError, match="represents"):
        resolve_driver(roster(), "Other Team", query)


def test_ambiguous_and_missing_entries_fail():
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_driver(pd.concat([roster(), roster()]), "Example Team", "16")
    with pytest.raises(ValueError, match="Available"):
        resolve_driver(roster(), "Example Team", "Someone Else")
    with pytest.raises(ValueError, match="eligible"):
        select_event(calendar(2025), "Example", now="2025-03-03T11:00:00Z")
    with pytest.raises(ValueError, match="Ambiguous"):
        select_event(
            pd.concat([calendar(2025), calendar(2025)]), "Example", now="2025-04-01T00:00:00Z"
        )


def test_review_reports_sources_and_actual_stints(tmp_path):
    request = AnalysisRequest("Example", "Example Team", "Driver One", 2025)
    report, data = analyze_driver(request, Provider(), now="2025-04-01T00:00:00Z")
    assert report["event"]["year"] == 2025
    assert report["training_years"] == [2023, 2024, 2025]
    assert report["actual"]["status"] == "observed"
    assert report["race_config"]["total_laps"] == 54
    assert report["validation"]["training_years"] == [2023, 2024]
    assert report["validation"]["holdout_year"] == 2025
    assert sum(report["strategy"]["stint_lengths"]) == 54
    assert all(s["tier"] == "driver" for s in report["model"]["diagnostics"]["sources"].values())
    output = tmp_path / "中文报告"
    save_analysis(report, data, output)
    saved = json.loads((output / "driver-analysis.json").read_text(encoding="utf-8"))
    assert len(saved["data_sha256"]) == 64
    assert (output / "driver-model.png").stat().st_size > 1000
    assert (output / "driver-strategies.png").stat().st_size > 1000
    with pytest.raises(ValueError, match="empty"):
        save_analysis(report, data, output)


def test_prediction_never_loads_target_race_or_trains_on_it():
    provider = Provider()
    request = AnalysisRequest(
        "Example", "Example Team", "SYN0", 2025, mode="predict", total_laps=54
    )
    report, data = analyze_driver(request, provider, now="2025-03-02T00:00:00Z")
    assert (2025, "R") not in provider.calls
    assert (2025, "FP1") in provider.calls
    assert set(data.Year) == {2023, 2024}
    assert report["actual"]["status"] == "not_loaded"
    with pytest.raises(ValueError, match="FP1"):
        analyze_driver(request, Provider(), now="2025-02-01T00:00:00Z")


def test_prediction_distance_not_inferred_from_results():
    with pytest.raises(ValueError, match="--laps"):
        analyze_driver(
            AnalysisRequest("Example", "Example Team", "SYN0", mode="predict"), Provider()
        )


def test_missing_compound_fallback_requires_explicit_choice():
    data = synthetic_laps()
    data = data.merge(roster(), left_on="Driver", right_on="Abbreviation")
    identity = resolve_driver(roster(), "Example Team", "SYN0")
    data = data[~((data.Driver == "SYN0") & data.Compound.isin(["MEDIUM", "HARD"]))]
    with pytest.raises(ValueError, match="Insufficient"):
        fit_driver_model(data, identity)
    model = fit_driver_model(data, identity, fallback="team")
    sources = model.diagnostics["sources"]
    assert sources["SOFT"]["tier"] == "driver"
    assert sources["HARD"]["tier"] == "team"
    assert sources["HARD"]["drivers"] == ["Driver Two"]


def test_dnf_and_used_tyres_are_not_silently_compared():
    session = Provider().load(2025, 1)
    assert actual_schedule(session.laps, "SYN0", 55)["status"] == "partial"
    session.laps.loc[
        (session.laps.Driver == "SYN0") & (session.laps.LapNumber == 1), "TyreLife"
    ] = 4
    assert actual_schedule(session.laps, "SYN0", 54)["stints"][0]["start_age"] == 4


def test_omitted_year_chooses_latest_eligible_calendar():
    request = AnalysisRequest("Example", "Example Team", "SYN0")
    report, _ = analyze_driver(request, Provider(), now="2025-01-01T00:00:00Z")
    assert report["event"]["year"] == 2024


def test_fastf1_driver_provider_loads_race_control_messages(tmp_path):
    import sys
    from unittest.mock import Mock, patch

    from f1_strategy_optimizer.driver_analysis import FastF1Provider

    api = Mock()
    with patch.dict(sys.modules, {"fastf1": api}):
        provider = FastF1Provider(tmp_path / "cache", offline=True)
        provider.load(2024, 1)
    api.get_session.return_value.load.assert_called_once_with(
        laps=True, telemetry=False, weather=True, messages=True
    )
