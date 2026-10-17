"""Deterministic, model-relative pit strategy optimization. No import-time I/O."""

from .config import RaceConfig, RuleSet
from .models import ModelParameters, TyreCurve, TyreModel, fit_model
from .solver import InfeasibleStrategyError, PitStrategy, evaluate_strategy, solve

__version__ = "0.1.0"
__all__ = [
    "RaceConfig",
    "RuleSet",
    "ModelParameters",
    "TyreCurve",
    "TyreModel",
    "fit_model",
    "InfeasibleStrategyError",
    "PitStrategy",
    "evaluate_strategy",
    "solve",
]
