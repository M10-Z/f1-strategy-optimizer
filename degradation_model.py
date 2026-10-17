"""Compatibility helpers. Models are now explicit and fitting has no file side effects."""

import _compat  # noqa: F401
from f1_strategy_optimizer.models import TyreModel, fit_model


def fit_tyre_degradation(df) -> TyreModel:
    return fit_model(df)


def get_expected_lap_time(compound, lap_age, track_temp=None, *, model: TyreModel):
    return model.predict(
        compound.upper(),
        lap_age,
        model.parameters.reference_temp if track_temp is None else track_temp,
    )
