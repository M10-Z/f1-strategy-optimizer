"""Explicit plotting functions using a headless canvas; no global pyplot state."""

from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .models import TyreModel

COLORS = {"SOFT": "#d55e00", "MEDIUM": "#0072b2", "HARD": "#666666"}


def plot_model(model: TyreModel, destination: str | Path, max_age: int = 50) -> Path:
    figure = Figure(figsize=(11, 3.6 * len(model.compounds)), layout="constrained")
    FigureCanvasAgg(figure)
    axes = np.atleast_1d(figure.subplots(len(model.compounds), 1))
    for axis, compound in zip(axes, model.compounds):
        curve = model.curves[compound]
        ages = np.arange(1, max_age + 1)
        raw = curve.base_time + curve.raw_delta(ages)
        effective = [model.predict(compound, int(a), model.parameters.reference_temp) for a in ages]
        axis.plot(ages, raw, "--", color=COLORS[compound], label="Raw fitted shape + baseline")
        axis.plot(ages, effective, color=COLORS[compound], label="Effective optimization curve")
        axis.axvspan(
            curve.min_observed_age,
            curve.max_observed_age,
            color="#009e73",
            alpha=0.10,
            label="Observed training age range",
        )
        axis.set(title=compound, xlabel="Tyre age (laps)", ylabel="Reference lap time (s)")
        axis.legend(loc="best", fontsize=9)
        axis.grid(alpha=0.2)
        axis.set_xlim(0.5, max_age + 0.5)
    source = model.diagnostics.get("source", "provided model")
    figure.suptitle(f"Tyre model | {source} | explicit modelling priors", fontsize=13)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160, bbox_inches="tight")
    return path


def plot_strategies(
    results: list[dict], destination: str | Path, source: str = "provided model"
) -> Path:
    figure = Figure(figsize=(12, max(4, len(results) * 0.65)), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    for row, result in enumerate(results):
        start = 0
        for compound, length in zip(result["compounds_used"], result["stint_lengths"]):
            axis.barh(
                row, length, left=start, color=COLORS[compound], edgecolor="white", height=0.7
            )
            if length >= 4:
                axis.text(
                    start + length / 2,
                    row,
                    f"{compound[0]} {length}",
                    color="white",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
            start += length
    axis.set_yticks(range(len(results)), [r["scenario"] for r in results])
    axis.invert_yaxis()
    axis.set(xlabel="Completed race laps", title="Optimal schedules under separate model scenarios")
    axis.grid(axis="x", alpha=0.2)
    figure.suptitle(
        f"Source: {source} | Model-relative scenarios, not observed race outcomes", fontsize=11
    )
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160, bbox_inches="tight")
    return path
