"""Position-oriented scenario planning and deterministic strategy research baselines."""

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
