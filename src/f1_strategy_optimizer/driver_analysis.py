"""Track/team/driver analysis, independently callable without changing the main CLI.

Run: python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari
     --driver LEC --year 2025
"""

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .analysis import compare_scenarios
from .config import RaceConfig, RuleSet, finite_number, positive_int
from .data import clean_session_laps
from .models import DRY_COMPOUNDS, ModelParameters, TyreCurve, TyreModel, fit_model
from .solver import evaluate_strategy, solve


def normalize(value) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return re.sub(r"[^\w]", "", "".join(c for c in text if not unicodedata.combining(c)))


def resolve_driver(results: pd.DataFrame, team: str, driver: str) -> dict:
    """Resolve exact normalized full name, abbreviation or number; never fuzzy-pick."""
    required = {"TeamName", "FullName", "Abbreviation", "DriverNumber"}
    if required - set(results):
        raise ValueError("Session entry list is missing driver/team metadata")
    key = normalize(driver)
    if not key or not normalize(team):
        raise ValueError("Driver and team cannot be empty")
    selected = results.loc[
        results.apply(
            lambda row: (
                key in {normalize(row[c]) for c in ("FullName", "Abbreviation", "DriverNumber")}
            ),
            axis=1,
        )
    ]
    if len(selected) != 1:
        choices = ", ".join(results.Abbreviation.dropna().astype(str).unique())
        raise ValueError(f"Driver is unknown or ambiguous. Available drivers: {choices}")
    row = selected.iloc[0]
    if normalize(team) != normalize(row.TeamName):
        raise ValueError(f"{row.FullName} represents {row.TeamName} in this session, not {team}")
    return {c: str(row[c]) for c in required}


def select_event(schedule: pd.DataFrame, track: str, now=None, completed=True) -> pd.Series:
    """Require unambiguous exact calendar name/location/country; no fuzzy event fallback."""
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    key = normalize(track)
    if not key:
        raise ValueError("track cannot be empty")
    matches = []
    for _, event in schedule.iterrows():
        if event.get("RoundNumber", 0) <= 0:
            continue
        names = {
            normalize(event.get(c, ""))
            for c in ("EventName", "OfficialEventName", "Location", "Country")
        }
        if key not in names:
            continue
        race_date = None
        for slot in range(1, 6):
            if event.get(f"Session{slot}") == "Race":
                race_date = pd.to_datetime(event.get(f"Session{slot}DateUtc"), utc=True)
                break
        if race_date is None or pd.isna(race_date):
            continue
        # A calendar slot is not proof that race data exists; loading below must succeed.
        if completed and race_date + pd.Timedelta(hours=6) > now:
            continue
        entry = event.copy()
        entry["RaceDateUtc"] = race_date
        matches.append(entry)
    if not matches:
        raise ValueError(
            f"No eligible event for {track!r}; use a calendar event/location/country name"
        )
    if len(matches) != 1:
        raise ValueError(f"Ambiguous track {track!r}; specify the exact EventName")
    return matches[0]


@dataclass
class AnalysisRequest:
    track: str
    team: str
    driver: str
    year: int | None = None
    mode: str = "review"
    history_years: int = 3
    fallback: str = "none"
    pit_loss: float = 24.0
    total_laps: int | None = None
    max_tyre_age: int = 50

    def __post_init__(self):
        if not all(str(s).strip() for s in (self.track, self.team, self.driver)):
            raise ValueError("track, team and driver are required")
        if self.year is not None:
            positive_int(self.year, "year")
        if self.mode not in ("review", "predict") or self.fallback not in ("none", "team", "field"):
            raise ValueError("Invalid analysis mode or fallback policy")
        positive_int(self.history_years, "history_years")
        positive_int(self.max_tyre_age, "max_tyre_age")
        finite_number(self.pit_loss, "pit_loss", 0)
        if self.total_laps is not None:
            positive_int(self.total_laps, "total_laps")


class FastF1Provider:
    """Lazy optional dependency; cache initialization happens only when constructed."""

    def __init__(self, cache_dir="cache", offline=False):
        try:
            import fastf1
        except ImportError as exc:
            raise RuntimeError('Install FastF1 with pip install ".[data]"') from exc
        self.api = fastf1
        cache = Path(cache_dir).expanduser()
        cache.mkdir(parents=True, exist_ok=True)
        self.api.Cache.enable_cache(str(cache))
        self.api.Cache.offline_mode(offline)

    def schedule(self, year):
        return self.api.get_event_schedule(year, include_testing=False)

    def load(self, year, round_number, kind="R"):
        session = self.api.get_session(year, int(round_number), kind)
        session.load(laps=True, telemetry=False, weather=True, messages=False)
        return session


def fit_driver_model(data, identity, fallback="none", minimum_samples=6):
    """Fit each compound separately, disclosing every broader-data substitution."""
    tiers = [
        (
            "driver",
            data[(data.FullName == identity["FullName"]) & (data.TeamName == identity["TeamName"])],
        )
    ]
    if fallback in ("team", "field"):
        tiers.append(("team", data[data.TeamName == identity["TeamName"]]))
    if fallback == "field":
        tiers.append(("field", data))
    curves, sources, diagnostics, failures = {}, {}, {}, {}
    parameters = ModelParameters()
    for compound in DRY_COMPOUNDS:
        failures[compound] = []
        for tier, candidates in tiers:
            part = candidates[candidates.Compound == compound]
            if len(part) < minimum_samples:
                failures[compound].append(f"{tier}: fewer than {minimum_samples} usable laps")
                continue
            try:
                fitted = fit_model(part, parameters)
            except ValueError as exc:
                failures[compound].append(f"{tier}: {exc}")
                continue
            curves[compound] = fitted.curves[compound]
            diagnostics[compound] = fitted.diagnostics
            sources[compound] = {
                "tier": tier,
                "laps": len(part),
                "drivers": sorted(part.FullName.unique().tolist()),
                "teams": sorted(part.TeamName.unique().tolist()),
                "years": sorted(int(y) for y in part.Year.unique()),
            }
            break
    if len(curves) < 2:
        raise ValueError(
            "Insufficient data for two dry compounds. Add history or explicitly allow "
            f"--fallback team/field. Details: {failures}"
        )
    return TyreModel(
        curves,
        parameters,
        {
            "sources": sources,
            "fits": diagnostics,
            "unavailable": {c: failures[c] for c in failures if c not in curves},
        },
    )


def actual_schedule(laps: pd.DataFrame, driver: str, total_laps: int) -> dict:
    """Describe observed stints before cleaning. Do not invent DNF/missing laps."""
    target = laps[laps.Driver == driver].sort_values("LapNumber").copy()
    if target.empty or target.LapNumber.duplicated().any():
        return {"status": "unavailable", "reason": "Missing or duplicate driver laps"}
    if target.LapNumber.tolist() != list(range(1, total_laps + 1)):
        return {
            "status": "partial",
            "reason": "Driver did not record every race lap (DNF/lapped/gaps)",
        }
    groups = []
    for _, part in target.groupby((target.Stint != target.Stint.shift()).cumsum()):
        if part.Compound.nunique() != 1 or pd.isna(part.Stint.iloc[0]):
            return {"status": "unavailable", "reason": "Inconsistent stint metadata"}
        groups.append(
            {
                "compound": str(part.Compound.iloc[0]),
                "length": len(part),
                "start_age": None
                if pd.isna(part.TyreLife.iloc[0])
                else float(part.TyreLife.iloc[0]),
            }
        )
    return {
        "status": "observed",
        "stints": groups,
        "note": "Stint transitions can include red-flag changes; they are not always pit stops",
    }


def validate_driver_year(data, identity, target_year, fallback):
    """Evaluate target driver on a held-out year, rebuilding only from earlier years."""
    train = data[data.Year < target_year]
    test = data[
        (data.Year == target_year)
        & (data.FullName == identity["FullName"])
        & (data.TeamName == identity["TeamName"])
    ]
    if train.empty or test.empty:
        return {
            "status": "unavailable",
            "reason": "Need earlier seasons and target-year driver laps",
        }
    try:
        model = fit_driver_model(train, identity, fallback)
    except ValueError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    metrics = {}
    for compound in test.Compound.unique():
        part = test[test.Compound == compound]
        if compound not in model.compounds:
            metrics[compound] = {"status": "no_prior_model", "samples": len(part)}
            continue
        actual = part.LapTimeSeconds + model.parameters.fuel_gain_per_lap * (part.LapNumber - 1)
        predicted = pd.Series(
            [model.predict(compound, int(age)) for age in part.TyreLife], index=part.index
        )
        error = predicted - actual
        metrics[compound] = {
            "status": "evaluated",
            "samples": len(part),
            "mae_seconds": float(error.abs().mean()),
            "rmse_seconds": float((error.pow(2).mean()) ** 0.5),
        }
    return {
        "status": "evaluated",
        "holdout_year": target_year,
        "training_years": sorted(int(y) for y in train.Year.unique()),
        "compounds": metrics,
        "sources": model.diagnostics["sources"],
        "interpretation": "Lap-time validation only, not proof of counterfactual strategy gains",
    }


def analyze_driver(request: AnalysisRequest, provider=None, now=None) -> tuple[dict, pd.DataFrame]:
    """Review may use target-race data. Predict NEVER loads the target race session.

    Predict uses the target FP1 entry list, prior-year race laps and explicit race
    distance; unavailable practice/entries fail clearly instead of guessing transfers.
    """
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    if request.mode == "predict" and request.total_laps is None:
        raise ValueError(
            "Prediction requires --laps (planned race distance; never read target results)"
        )
    provider = provider or FastF1Provider()
    years = [request.year] if request.year else list(range(now.year, now.year - 3, -1))
    event = None
    for year in years:
        schedule = provider.schedule(year)
        try:
            event = select_event(schedule, request.track, now, completed=request.mode == "review")
        except ValueError as exc:
            if "Ambiguous" in str(exc) or request.year:
                raise
            continue
        break
    if event is None:
        raise ValueError("No matching event found in the last three calendar years; specify --year")
    target_year, round_number = int(year), int(event.RoundNumber)
    if request.mode == "predict":
        practice = None
        for slot in range(1, 6):
            if event.get(f"Session{slot}") == "Practice 1":
                practice = pd.to_datetime(event.get(f"Session{slot}DateUtc"), utc=True)
        if practice is None or pd.isna(practice) or practice + pd.Timedelta(hours=2) > now:
            raise ValueError("Prediction entry-list verification requires completed FP1 data")
    target = provider.load(target_year, round_number, "R" if request.mode == "review" else "FP1")
    identity = resolve_driver(target.results, request.team, request.driver)
    frames, skipped = [], []
    for historical_year in range(target_year - request.history_years + 1, target_year + 1):
        if historical_year == target_year and request.mode == "predict":
            continue
        try:
            if historical_year == target_year:
                session = target
            else:
                previous = select_event(
                    provider.schedule(historical_year),
                    request.track,
                    event.RaceDateUtc,
                    completed=True,
                )
                session = provider.load(historical_year, int(previous.RoundNumber), "R")
            cleaned = clean_session_laps(session.laps, historical_year, str(event.EventName))
            roster = session.results[["Abbreviation", "FullName", "TeamName"]].drop_duplicates()
            cleaned = cleaned.merge(
                roster,
                left_on="Driver",
                right_on="Abbreviation",
                validate="many_to_one",
                how="left",
            )
            if cleaned[["FullName", "TeamName"]].isna().any().any():
                raise ValueError("Unresolved historical driver/team metadata")
            frames.append(cleaned)
        except (ValueError, RuntimeError, OSError) as exc:
            if historical_year == target_year:
                raise
            skipped.append({"year": historical_year, "reason": str(exc)})
    if not frames:
        raise ValueError("No eligible prior race data")
    data = pd.concat(frames, ignore_index=True)
    model = fit_driver_model(data, identity, request.fallback)
    total_laps = request.total_laps or int(pd.to_numeric(target.laps.LapNumber).max())
    config = RaceConfig(
        total_laps=total_laps,
        pit_loss=request.pit_loss,
        max_tyre_age=request.max_tyre_age,
        rules=RuleSet(season=target_year, event=str(event.EventName)),
    )
    optimum = solve(model, config)
    actual = {"status": "not_loaded", "reason": "Prediction excludes target race outcomes"}
    if request.mode == "review":
        actual = actual_schedule(target.laps, identity["Abbreviation"], total_laps)
        if actual["status"] == "observed":
            stints = actual["stints"]
            if any(s["start_age"] != 1 for s in stints):
                actual["comparison_status"] = "not_scored: used/unknown starting tyre ages"
            else:
                try:
                    evaluated = evaluate_strategy(
                        model,
                        config,
                        [s["compound"] for s in stints],
                        [s["length"] for s in stints],
                    )
                    actual["same_model_time_seconds"] = evaluated.total_time
                    actual["model_gap_seconds"] = evaluated.total_time - optimum.total_time
                    actual["comparison_status"] = (
                        "hypothetical: each stint transition priced as a stop"
                    )
                except ValueError as exc:
                    actual["comparison_status"] = f"not_scored: {exc}"
    warnings = [
        "Model-relative dry-tyre research; not full FIA compliance or a guaranteed race result",
        "Fuel, temperature, pit loss and tyre availability are not fully observed",
        f"{request.pit_loss:g} seconds is a pit-loss prior, not a measured event-specific loss",
        "Age extrapolation and pooling across years can distort strategy rankings",
    ]
    if request.mode == "review":
        warnings.append(
            "Retrospective fit may include the target race; this is not a pre-race forecast"
        )
    if any(source["tier"] != "driver" for source in model.diagnostics["sources"].values()):
        warnings.append(
            "Explicit fallback supplied some compounds from other drivers; inspect sources"
        )
    report = {
        "schema_version": 1,
        "request": asdict(request),
        "identity": identity,
        "event": {
            "year": target_year,
            "name": str(event.EventName),
            "round": round_number,
            "race_date_utc": event.RaceDateUtc.isoformat(),
        },
        "training_years": sorted(int(y) for y in data.Year.unique()),
        "skipped_years": skipped,
        "race_config": asdict(config),
        "distance_source": "explicit"
        if request.total_laps
        else "maximum recorded race lap (actual historical distance)",
        "model": model.to_dict(),
        "strategy": optimum.to_dict(),
        "actual": actual,
        "validation": validate_driver_year(data, identity, target_year, request.fallback)
        if request.mode == "review"
        else {"status": "not_run", "reason": "Target race excluded"},
        "scenarios": compare_scenarios(model, config),
        "warnings": warnings,
    }
    return report, data


def save_analysis(report, data, output_dir):
    """Publish one local, inspectable run; never overwrite earlier output."""
    path = Path(output_dir).expanduser()
    if path.exists() and any(path.iterdir()):
        raise ValueError("Output directory must be empty")
    path.mkdir(parents=True, exist_ok=True)
    data.to_csv(path / "analysis-laps.csv", index=False, encoding="utf-8")
    report = dict(report)
    report["data_sha256"] = hashlib.sha256((path / "analysis-laps.csv").read_bytes()).hexdigest()
    from .plotting import plot_model, plot_strategies

    model = TyreModel(
        {c: TyreCurve(**curve) for c, curve in report["model"]["curves"].items()},
        ModelParameters(**report["model"]["parameters"]),
        report["model"]["diagnostics"],
    )
    plot_model(
        model,
        path / "driver-model.png",
        min(report["race_config"]["total_laps"], report["race_config"]["max_tyre_age"]),
    )
    plot_strategies(report["scenarios"], path / "driver-strategies.png")
    (path / "driver-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Driver strategy analysis",
        "",
        f"Mode: **{report['request']['mode']}**",
        f"Event: {report['event']['year']} {report['event']['name']}",
        f"Driver: {report['identity']['FullName']} | Team: {report['identity']['TeamName']}",
        "",
        "## Model-relative strategy",
        "",
        "| Compound | Laps |",
        "|---|---:|",
    ]
    result = report["strategy"]
    lines += [f"| {c} | {n} |" for c, n in zip(result["compounds_used"], result["stint_lengths"])]
    lines += [
        "",
        f"Pit after laps: {result['pit_laps']}",
        f"Model time: {result['total_time']:.3f} seconds",
        "",
        "## Data sources",
        "",
    ]
    for compound, source in report["model"]["diagnostics"]["sources"].items():
        lines.append(
            f"- {compound}: {source['tier']}; {source['laps']} laps; "
            f"years {source['years']}; drivers {source['drivers']}"
        )
    lines += [
        "",
        "## Plots",
        "",
        "![Tyre model](driver-model.png)",
        "",
        "![Scenario strategies](driver-strategies.png)",
        "",
        "## Held-out validation",
        "",
        f"Status: {report['validation']['status']}",
    ]
    for compound, metric in report["validation"].get("compounds", {}).items():
        lines.append(f"- {compound}: {metric}")
    if "reason" in report["validation"]:
        lines.append(report["validation"]["reason"])
    lines += ["", "## Actual strategy", "", f"Status: {report['actual']['status']}"]
    for stint in report["actual"].get("stints", []):
        lines.append(
            f"- {stint['compound']} x {stint['length']} laps; starting age {stint['start_age']}"
        )
    lines.append(report["actual"].get("comparison_status", report["actual"].get("reason", "")))
    if "model_gap_seconds" in report["actual"]:
        lines.append(f"Hypothetical same-model gap: {report['actual']['model_gap_seconds']:.3f} s")
    lines += ["", "## Limits", "", *[f"- {w}" for w in report["warnings"]]]
    lines += [
        "",
        "Full actual-stint details, skipped years and model parameters: driver-analysis.json",
        "",
    ]
    (path / "driver-analysis.md").write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Automatic track/team/driver strategy analysis")
    parser.add_argument("--track", required=True, help="Exact calendar name, location or country")
    parser.add_argument("--team", required=True, help="Session team name, e.g. Ferrari")
    parser.add_argument("--driver", required=True, help="Full name, abbreviation or car number")
    parser.add_argument("--year", type=int, help="Default: most recent eligible event")
    parser.add_argument("--mode", choices=["review", "predict"], default="review")
    parser.add_argument("--history-years", type=int, default=3)
    parser.add_argument("--fallback", choices=["none", "team", "field"], default="none")
    parser.add_argument("--pit-loss", type=float, default=24.0)
    parser.add_argument("--laps", type=int)
    parser.add_argument("--max-tyre-age", type=int, default=50)
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--offline", action="store_true", help="Use existing cache only")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    try:
        request = AnalysisRequest(
            args.track,
            args.team,
            args.driver,
            args.year,
            args.mode,
            args.history_years,
            args.fallback,
            args.pit_loss,
            args.laps,
            args.max_tyre_age,
        )
        if request.mode == "predict" and request.total_laps is None:
            raise ValueError("Prediction requires --laps")
        output = (
            Path(args.output_dir)
            if args.output_dir
            else Path("output")
            / ("driver-analysis-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        )
        if output.exists() and any(output.iterdir()):
            raise ValueError("Output directory must be empty")
        report, data = analyze_driver(request, FastF1Provider(args.cache_dir, offline=args.offline))
        save_analysis(report, data, output)
        print(
            f"{report['event']['year']} {report['event']['name']} | "
            f"{report['identity']['TeamName']} | {report['identity']['FullName']}"
        )
        print(f"Mode: {args.mode}; data years: {report['training_years']}")
        print(f"Pit after laps: {report['strategy']['pit_laps']}")
        print(f"Report: {output.resolve() / 'driver-analysis.md'}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
