"""Optional FastF1 adapter. Caches are created only on explicit fetch requests."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .models import DRY_COMPOUNDS, validate_laps

logger = logging.getLogger(__name__)


def clean_session_laps(laps: pd.DataFrame, year: int, event: str) -> pd.DataFrame:
    required = {
        "LapTime",
        "LapNumber",
        "Compound",
        "TyreLife",
        "Driver",
        "Stint",
        "PitInTime",
        "PitOutTime",
        "IsAccurate",
        "TrackStatus",
    }
    if required - set(laps.columns):
        raise ValueError(f"FastF1 lap metadata missing: {sorted(required - set(laps.columns))}")
    if "Deleted" not in laps or laps.Deleted.isna().any():
        raise ValueError(
            "Deleted lap flags are unavailable; load race control messages (messages=True)"
        )
    data = laps.copy()
    data["Compound"] = data.Compound.astype("string").str.strip().str.upper()
    # Drop explicit pit laps and non-green/uncertain timing; no timing-threshold guess.
    excluded = {
        "pit_in": data.PitInTime.notna(),
        "pit_out": data.PitOutTime.notna(),
        "inaccurate_or_unknown": ~data.IsAccurate.eq(True).fillna(False),
        "non_green_or_unknown": ~data.TrackStatus.astype(str).eq("1"),
        "unsupported_compound": ~data.Compound.isin(DRY_COMPOUNDS),
        "deleted": data.Deleted.astype("boolean"),
    }
    mask = ~pd.DataFrame(excluded).any(axis=1)
    data = data.loc[mask].copy()
    data["LapTimeSeconds"] = data.LapTime.dt.total_seconds()
    numeric = ["LapTimeSeconds", "LapNumber", "TyreLife", "Stint"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid_numeric = np.isfinite(data[numeric]).all(axis=1) & data[numeric].gt(0).all(axis=1)
    invalid_numeric_rows = int((~valid_numeric).sum())
    data = data.loc[valid_numeric].copy()
    data["Year"], data["Event"] = year, event
    if "TrackTemp" not in data:
        data["TrackTemp"] = np.nan
    data = validate_laps(data)
    columns = [
        "Year",
        "Event",
        "Driver",
        "Stint",
        "LapNumber",
        "TyreLife",
        "Compound",
        "LapTimeSeconds",
        "TrackTemp",
    ]
    result = data[columns].reset_index(drop=True)
    result.attrs["cleaning"] = {
        "input_rows": len(laps),
        "kept_rows": len(result),
        "removed_rows": len(laps) - len(result),
        "excluded_by_metadata_reason": {key: int(value.sum()) for key, value in excluded.items()},
        "invalid_numeric_after_metadata": invalid_numeric_rows,
        "counting_note": "Metadata reasons overlap; numeric exclusions apply after metadata",
        "deleted_flags_verified": True,
    }
    return result


def fetch_cycle_data(
    start_year: int = 2022,
    end_year: int = 2025,
    track: str = "Bahrain",
    session_type: str = "R",
    pit_loss_time: float = 24.0,
    cache_dir: str | Path = "cache",
    allow_partial: bool = False,
    offline: bool = False,
) -> pd.DataFrame:
    from .config import finite_number, positive_int

    positive_int(start_year, "start_year")
    positive_int(end_year, "end_year")
    finite_number(pit_loss_time, "pit_loss_time", 0)
    if start_year > end_year:
        raise ValueError("start_year must not exceed end_year")
    if session_type != "R":
        raise ValueError("Only race sessions (R) are supported")
    if not track.strip():
        raise ValueError("track cannot be empty")
    try:
        import fastf1
    except ImportError as exc:
        raise RuntimeError('Install the data extra: pip install ".[data]"') from exc
    cache = Path(cache_dir).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))
    fastf1.Cache.offline_mode(offline)
    frames, failed, cleaning = [], {}, {}
    for year in range(start_year, end_year + 1):
        try:
            session = fastf1.get_session(year, track, "R")
            session.load(laps=True, telemetry=False, weather=True, messages=True)
            laps = session.laps.copy()
            # FastF1 computes weather per lap. Retain missing values explicitly.
            if hasattr(session.laps, "get_weather_data"):
                weather = session.laps.get_weather_data()
                if len(weather) == len(laps) and "TrackTemp" in weather:
                    laps["TrackTemp"] = weather.TrackTemp.to_numpy()
            clean = clean_session_laps(laps, year, track)
            cleaning[str(year)] = clean.attrs["cleaning"]
            frames.append(clean)
        except Exception as exc:
            if not allow_partial:
                raise RuntimeError(f"Failed to load/clean {year} {track}: {exc}") from exc
            failed[str(year)] = f"{type(exc).__name__}: {exc}"
            logger.warning("Skipping %s %s: %s", year, track, exc)
    if not frames:
        raise RuntimeError("No usable race data; inspect cache, event name and connection")
    result = pd.concat(frames, ignore_index=True)
    result.attrs.update(
        source="FastF1",
        track=track,
        requested_years=list(range(start_year, end_year + 1)),
        loaded_years=sorted(int(y) for y in result.Year.unique()),
        failed_years=failed,
        offline=offline,
        cleaning=cleaning,
        pit_loss_time=pit_loss_time,
    )
    return result
