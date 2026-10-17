"""Offline entry point for position-oriented, explicitly hypothetical race planning."""

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifacts import _versions, write_json
from .competition import (
    CarState,
    FixedPolicy,
    Physics,
    PitAction,
    PitRecord,
    RaceEvent,
    RaceState,
    ReactivePolicy,
    Scenario,
    candidate_actions,
    plan_positions,
)
from .config import finite_number, positive_int


@dataclass(frozen=True)
class ExplicitTyrePace:
    base_time: float
    degradation: float

    def __post_init__(self):
        finite_number(self.base_time, "base_time", 0.001)
        finite_number(self.degradation, "degradation", 0)


@dataclass
class ScenarioTyreModel:
    """User-supplied linear curves, including wet tyres; not a fitted physical model.

    Implements the same LapTimeModel protocol as the existing fitted dry TyreModel.
    The simulator can use that existing model directly through the Python API.
    """

    curves: dict[str, ExplicitTyrePace]

    def __post_init__(self):
        if not self.curves or any(not isinstance(c, str) or not c for c in self.curves):
            raise ValueError("Nonempty named tyre curves are required")

    @property
    def compounds(self):
        return tuple(self.curves)

    def predict(self, compound, age, track_temp=35.0):
        positive_int(age, "age")
        finite_number(track_temp, "track_temp")
        curve = self.curves[compound]
        return curve.base_time + curve.degradation * (age - 1)


def plan_from_document(document: dict) -> dict:
    required = {
        "source",
        "state",
        "physics",
        "tyres",
        "ego",
        "opponents",
        "scenarios",
        "candidates",
    }
    if required - set(document) or set(document) - required - {"risk_top_k", "observed_pits"}:
        raise ValueError(
            "Scenario document needs source/state/physics/tyres/ego/opponents/scenarios/candidates"
        )
    if not isinstance(document["source"], str) or not document["source"].strip():
        raise ValueError("State the source and whether the snapshot is synthetic or observed")
    raw_state = dict(document["state"])
    cars = []
    for raw_car in raw_state.pop("cars"):
        values = dict(raw_car)
        values["elapsed"] = values.pop("gap_seconds")
        cars.append(CarState(**values))
    if min(c.elapsed for c in cars) != 0:
        raise ValueError("The leading car must have gap_seconds=0")
    state = RaceState(cars=tuple(cars), **raw_state)
    model = ScenarioTyreModel(
        {c: ExplicitTyrePace(**spec) for c, spec in document["tyres"].items()}
    )
    physics = Physics(**document["physics"])
    opponents = {}
    for driver, raw_policy in document["opponents"].items():
        policy = dict(raw_policy)
        kind = policy.pop("kind")
        if kind == "fixed":
            if set(policy) != {"stops"}:
                raise ValueError("Fixed policies accept only stops")
            opponents[driver] = FixedPolicy(tuple(PitAction(**s) for s in policy["stops"]))
        elif kind == "reactive":
            opponents[driver] = ReactivePolicy(**policy)
        else:
            raise ValueError("Opponent kind must be fixed or reactive")
    scenarios = []
    for raw_scenario in document["scenarios"]:
        scenario = dict(raw_scenario)
        events = tuple(RaceEvent(**event) for event in scenario.pop("events", []))
        scenarios.append(Scenario(events=events, **scenario))
    candidates = document["candidates"]
    if set(candidates) != {"compounds", "pit_laps"}:
        raise ValueError("Candidate settings accept compounds and pit_laps")
    actions = candidate_actions(
        state, tuple(candidates["compounds"]), tuple(candidates["pit_laps"])
    )
    result = plan_positions(
        model,
        state,
        physics,
        document["ego"],
        opponents,
        actions,
        tuple(scenarios),
        document.get("risk_top_k", 3),
        tuple(PitRecord(**p) for p in document.get("observed_pits", [])),
    )
    result["source"] = document["source"]
    result["initial_order"] = list(state.order)
    result["initial_gaps_seconds"] = state.gaps()
    result["scenario_assumptions"] = [asdict(s) for s in scenarios]
    result["pace_notice"] = (
        "Vehicle base pace and tyre curves are supplied assumptions. Public timing estimates "
        "are confounded by traffic, fuel, track evolution and driver behavior. "
        "The CLI linear tyre model has no temperature response; Python API models may supply one."
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Position-oriented multi-car scenario planning")
    parser.add_argument(
        "--scenario",
        type=Path,
        required=True,
        help="Current snapshot and hypothetical scenarios JSON",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.expanduser()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output directory must be empty; choose a new run directory")
        raw = args.scenario.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Scenario document must be an object")
        report = plan_from_document(document)
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "race-plan.json", report)
        write_json(
            output / "manifest.json",
            {
                "schema_version": 1,
                "versions": _versions(),
                "input_sha256": hashlib.sha256(raw).hexdigest(),
                "input": document,
                "scope": "Hypothetical multi-car simulation; uncalibrated scenario weights",
            },
        )
        lines = [
            "# Position-oriented scenario plan",
            "",
            report["claim"],
            report["feasibility"],
            "",
            f"Source: {report['source']}",
            f"Driver: {report['ego']}",
            f"Decision after lap: {report['decision_lap']}",
            "",
            "Ranking uses scenario-weighted position, then worst position. "
            "Weights are assumptions.",
            "",
            "| Plan | Weighted position | Worst position | Position SD | Share outside top k |",
            "|---|---:|---:|---:|---:|",
        ]
        for row in report["ranking"]:
            lines.append(
                f"| {row['label']} | {row['expected_finish_position']:.3f} | "
                f"{row['worst_finish_position']} | {row['position_std']:.3f} | "
                f"{row['weighted_share_outside_top_k']:.3f} |"
            )
        lines += ["", f"k = {report['risk_top_k']}", "", report["pace_notice"], "", "## Limits", ""]
        lines += [f"- {limit}" for limit in report["limits"]]
        lines += [
            "",
            "Per-scenario finish orders, opponent responses and visible-state traces: "
            "race-plan.json",
            "",
        ]
        (output / "race-plan.md").write_text("\n".join(lines), encoding="utf-8")
        best = report["ranking"][0]
        print(
            f"Scenario-ranked plan: {best['label']} | "
            f"weighted position: {best['expected_finish_position']:.3f}"
        )
        print(report["claim"])
        print(report["feasibility"])
        print(f"Results: {output.resolve()}")
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
