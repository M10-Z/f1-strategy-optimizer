"""Grouped tyre-age regression with explicit, inspectable modelling priors."""

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .config import finite_number, positive_int

DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")


@dataclass(frozen=True)
class ModelParameters:
    fuel_gain_per_lap: float = 0.035
    reference_temp: float = 35.0
    temperature_coefficient: float = 0.003
    min_degradation: dict[str, float] = field(
        default_factory=lambda: {
            "SOFT": 0.08,
            "MEDIUM": 0.04,
            "HARD": 0.02,
        }
    )
    # Optional scenario prior; zero disables forced compound ordering.
    compound_gap: float = 0.0

    def __post_init__(self):
        finite_number(self.fuel_gain_per_lap, "fuel_gain_per_lap", 0)
        finite_number(self.reference_temp, "reference_temp")
        finite_number(self.temperature_coefficient, "temperature_coefficient", 0)
        finite_number(self.compound_gap, "compound_gap", 0)
        if not isinstance(self.min_degradation, dict):
            raise ValueError("min_degradation must be a dictionary")
        if set(self.min_degradation) - set(DRY_COMPOUNDS):
            raise ValueError("Unknown compound in min_degradation")
        for rate in self.min_degradation.values():
            finite_number(rate, "minimum degradation", 0)


@dataclass(frozen=True)
class TyreCurve:
    base_time: float
    linear: float
    quadratic: float = 0.0
    max_observed_age: int = 50
    min_observed_age: int = 1

    def __post_init__(self):
        finite_number(self.base_time, "base_time", 0)
        if self.base_time == 0:
            raise ValueError("base_time must be positive")
        finite_number(self.linear, "linear")
        finite_number(self.quadratic, "quadratic")
        positive_int(self.max_observed_age, "max_observed_age")
        positive_int(self.min_observed_age, "min_observed_age")
        if self.min_observed_age > self.max_observed_age:
            raise ValueError("Observed age range is reversed")

    def raw_delta(self, age):
        return self.linear * (age - 1) + self.quadratic * (age * age - 1)


@dataclass
class TyreModel:
    curves: dict[str, TyreCurve]
    parameters: ModelParameters = field(default_factory=ModelParameters)
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.curves or set(self.curves) - set(DRY_COMPOUNDS):
            raise ValueError("TyreModel supports nonempty SOFT/MEDIUM/HARD curves only")

    @property
    def compounds(self) -> tuple[str, ...]:
        return tuple(c for c in DRY_COMPOUNDS if c in self.curves)

    def predict(self, compound: str, age: int, track_temp: float = 35.0) -> float:
        positive_int(age, "age")
        finite_number(track_temp, "track_temp")
        if compound not in self.curves:
            raise ValueError(f"No model for {compound}")
        curve = self.curves[compound]
        # Discrete monotone envelope avoids declining polynomial extrapolation.
        delta = max(0.0, max(curve.raw_delta(a) for a in range(1, age + 1)))
        delta = max(delta, self.parameters.min_degradation.get(compound, 0) * (age - 1))
        factor = max(
            0.5,
            min(
                2.0,
                1
                + self.parameters.temperature_coefficient
                * (track_temp - self.parameters.reference_temp),
            ),
        )
        return curve.base_time + delta * factor

    def to_dict(self) -> dict:
        return {
            "curves": {c: asdict(v) for c, v in self.curves.items()},
            "parameters": asdict(self.parameters),
            "diagnostics": self.diagnostics,
            "prior_notice": "Fuel, temperature and degradation floors are scenario priors, "
            "not measured FIA/Pirelli constants",
        }


def validate_laps(df: pd.DataFrame) -> pd.DataFrame:
    required = {"Compound", "TyreLife", "LapTimeSeconds", "LapNumber", "Year", "Driver", "Stint"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing lap columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("Lap dataset is empty")
    data = df.copy()
    for column in ("TyreLife", "LapTimeSeconds", "LapNumber", "Year", "Stint"):
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or (data[column] <= 0).any():
            raise ValueError(f"{column} must contain finite positive numbers")
        if column != "LapTimeSeconds" and (data[column] % 1 != 0).any():
            raise ValueError(f"{column} must contain integers")
    data["Compound"] = data["Compound"].astype("string").str.strip().str.upper()
    if not data["Compound"].isin(DRY_COMPOUNDS).all():
        raise ValueError("Only explicit SOFT/MEDIUM/HARD labels are supported")
    if data["Driver"].isna().any() or data["Driver"].astype(str).str.strip().eq("").any():
        raise ValueError("Driver cannot be missing")
    data["Driver"] = data["Driver"].astype("string").str.strip()
    event_keys = ["Event"] if "Event" in data else []
    if event_keys:
        data["Event"] = data["Event"].astype("string").str.strip()
        if data["Event"].isna().any() or data["Event"].eq("").any() or data["Event"].nunique() != 1:
            raise ValueError("Fit one nonempty event/track at a time")
    if data.duplicated(["Year", *event_keys, "Driver", "LapNumber"]).any():
        raise ValueError("Duplicate driver laps detected")
    return data


def fit_model(df: pd.DataFrame, parameters: ModelParameters | None = None) -> TyreModel:
    """Estimate slopes within Year/Driver/Stint groups, then median group baseline.

    No global state, plotting, downloads or writes. The fuel correction is applied
    consistently to regression targets AND baselines. Training scores are descriptive.
    """
    data = validate_laps(df)
    parameters = parameters or ModelParameters()
    curves, diagnostics = {}, {}
    for compound in DRY_COMPOUNDS:
        part = data[data.Compound == compound].copy()
        if part.empty:
            continue
        ages = part.TyreLife.to_numpy(dtype=float)
        target = (
            part.LapTimeSeconds + parameters.fuel_gain_per_lap * (part.LapNumber - 1)
        ).to_numpy()
        x = np.column_stack([ages - 1, ages**2 - 1])
        regression = pd.DataFrame(
            {
                "x1": x[:, 0],
                "x2": x[:, 1],
                "y": target,
                "Year": part.Year.to_numpy(),
                "Driver": part.Driver.to_numpy(),
                "Stint": part.Stint.to_numpy(),
            }
        )
        centered = regression[["x1", "x2", "y"]] - regression.groupby(["Year", "Driver", "Stint"])[
            ["x1", "x2", "y"]
        ].transform("mean")
        matrix = centered[["x1", "x2"]].to_numpy()
        if np.linalg.matrix_rank(matrix) < 2:
            raise ValueError(
                f"{compound}: insufficient within-stint age variation for quadratic fit"
            )
        coefficients = np.linalg.lstsq(matrix, centered.y.to_numpy(), rcond=None)[0]
        regression["baseline"] = target - x @ coefficients
        base = float(regression.groupby(["Year", "Driver", "Stint"]).baseline.median().median())
        curves[compound] = TyreCurve(
            base, float(coefficients[0]), float(coefficients[1]), int(max(ages)), int(min(ages))
        )
        diagnostics[compound] = {
            "samples": len(part),
            "groups": regression.groupby(["Year", "Driver", "Stint"]).ngroups,
            "raw_training_mae_seconds": float(np.abs(target - (base + x @ coefficients)).mean()),
            "raw_training_r2": _r2(target, base + x @ coefficients),
            "observed_age_range": [int(min(ages)), int(max(ages))],
        }
    if parameters.compound_gap > 0:
        previous = None
        for compound in DRY_COMPOUNDS:
            if compound not in curves:
                continue
            curve = curves[compound]
            base = (
                curve.base_time
                if previous is None
                else max(curve.base_time, previous + parameters.compound_gap)
            )
            curves[compound] = TyreCurve(
                base, curve.linear, curve.quadratic, curve.max_observed_age, curve.min_observed_age
            )
            previous = base
    model = TyreModel(
        curves,
        parameters,
        {
            "fit_method": "within-year-driver-stint quadratic regression; median group baseline",
            "source": data.attrs.get("source", "provided data"),
            "years": sorted(int(y) for y in data.Year.unique()),
            "compounds": diagnostics,
            "warnings": [
                "Training fit is not held-out validation",
                "Constant priors and pooled baselines do not establish causal tyre effects",
                "Predictions outside observed ages are extrapolations",
            ],
        },
    )
    for compound in model.compounds:
        part = data[data.Compound == compound]
        target = part.LapTimeSeconds + parameters.fuel_gain_per_lap * (part.LapNumber - 1)
        predicted = [
            model.predict(compound, int(age), parameters.reference_temp) for age in part.TyreLife
        ]
        diagnostics[compound]["effective_training_mae_seconds"] = float(
            np.abs(target.to_numpy() - predicted).mean()
        )
    return model


def _r2(actual, predicted) -> float | None:
    variance = float(np.sum((actual - np.mean(actual)) ** 2))
    return None if variance == 0 else float(1 - np.sum((actual - predicted) ** 2) / variance)


def synthetic_laps(seed: int = 42) -> pd.DataFrame:
    """Original synthetic data for reproducible offline examples; no real race claims."""
    rng = np.random.default_rng(seed)
    rows = []
    for year in (2022, 2023, 2024, 2025):
        for driver_id in range(4):
            driver_offset = rng.normal(0, 0.2)
            for stint, (compound, base, linear, quadratic) in enumerate(
                [
                    ("SOFT", 98.0, 0.09, 0.004),
                    ("MEDIUM", 98.5, 0.06, 0.002),
                    ("HARD", 99.0, 0.03, 0.001),
                ],
                start=1,
            ):
                for age in range(1, 19):
                    lap = (stint - 1) * 18 + age
                    time = (
                        base
                        + driver_offset
                        + 0.03 * (year - 2022)
                        + linear * (age - 1)
                        + quadratic * (age**2 - 1)
                        - 0.035 * (lap - 1)
                        + rng.normal(0, 0.06)
                    )
                    rows.append(
                        {
                            "Year": year,
                            "Driver": f"SYN{driver_id}",
                            "Stint": stint,
                            "LapNumber": lap,
                            "TyreLife": age,
                            "Compound": compound,
                            "LapTimeSeconds": time,
                            "TrackTemp": 35.0,
                            "Event": "SYNTHETIC",
                        }
                    )
    data = pd.DataFrame(rows)
    data.attrs.update(source="synthetic", seed=seed, track="SYNTHETIC")
    return data
