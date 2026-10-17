"""Bounded receding-horizon controller: beliefs see observations, not realized futures."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from time import perf_counter
from typing import Callable

from .competition import (
    FixedPolicy,
    Observation,
    Physics,
    PitAction,
    PitRecord,
    PlanningObjective,
    RaceState,
    Scenario,
    candidate_plans,
    plan_positions,
    simulate,
)
from .config import positive_int
from .race_constraints import CompetitionRules, InfeasibleRacePlan, nonnegative_int


@dataclass
class RollingResult:
    status: str
    final_state: RaceState
    pit_history: tuple[PitRecord, ...]
    trace: list[dict]
    decisions: list[dict]
    rollouts_executed: int
    elapsed_seconds: float
    reason: str | None = None


def rolling_plan(
    model,
    initial: RaceState,
    physics: Physics,
    ego: str,
    opponents: dict,
    belief_provider: Callable[[Observation], tuple[Scenario, ...]],
    realization: Scenario,
    compounds: tuple[str, ...],
    pit_offsets: tuple[int, ...] = (0, 2, 4),
    max_stops: int = 2,
    max_candidates: int = 500,
    max_rollouts: int = 2000,
    total_rollout_budget: int = 10000,
    max_decisions: int = 100,
    observed_pits: tuple[PitRecord, ...] = (),
    rules: CompetitionRules | None = None,
    objective: PlanningObjective | None = None,
    risk_top_k: int = 3,
) -> RollingResult:
    """Execute one boundary action, advance one lap, then discard and rebuild the plan.

    The simulator receives the realization. belief_provider receives only the
    current state/past pits and must construct assumptions available at that time.
    No empirical probability update or inference from unobserved events is performed.
    """
    started = perf_counter()
    for name, value in (
        ("max_decisions", max_decisions),
        ("total_rollout_budget", total_rollout_budget),
    ):
        positive_int(value, name)
    for offset in pit_offsets:
        nonnegative_int(offset, "pit offset")
    if len(set(pit_offsets)) != len(pit_offsets):
        raise ValueError("Rolling pit offsets must be unique")
    if realization.available_at_lap > initial.completed_laps:
        raise ValueError("Realization must be an explicitly supplied hypothetical test path")
    if any(not initial.completed_laps < e.lap <= initial.total_laps for e in realization.events):
        raise ValueError("Realization events must be in the remaining race")
    state, history, trace, decisions, rollouts = initial, observed_pits, [], [], 0
    actual_opponents = deepcopy(opponents)
    status, reason = "decision_limit_reached", None
    for _ in range(max_decisions):
        if state.completed_laps == state.total_laps:
            break
        beliefs = tuple(belief_provider(Observation(state, history)))
        laps = tuple(
            state.completed_laps + d
            for d in pit_offsets
            if state.completed_laps + d < state.total_laps
        )
        actions = candidate_plans(state, compounds, laps, max_stops, max_candidates)
        if rollouts + len(actions) * len(beliefs) > total_rollout_budget:
            status, reason = (
                "rollout_budget_exhausted",
                "Next decision exceeds total rollout budget",
            )
            break
        report = plan_positions(
            model,
            state,
            physics,
            ego,
            actual_opponents,
            actions,
            beliefs,
            risk_top_k,
            history,
            rules,
            objective,
            max_rollouts,
        )
        rollouts += report["search"]["rollouts_executed"]
        decision = {
            "after_lap": state.completed_laps,
            "visible_track_status": state.track_status,
            "visible_weather": state.weather,
            "visible_inventory": {
                c.driver: dict(c.tyre_inventory) if c.tyre_inventory is not None else None
                for c in state.cars
            },
            "beliefs": [asdict(s) for s in beliefs],
            "status": report["status"],
            "recommended_stops": report["recommended_stops"],
            "search": report["search"],
            "rejected_candidates": report["rejected_candidates"],
        }
        decisions.append(decision)
        if not report["ranking"]:
            status, reason = "no_feasible_plan", "No common feasible candidate for supplied beliefs"
            break
        best = report["ranking"][0]
        decision["expected_finish_position"] = best["expected_finish_position"]
        decision["expected_objective"] = best["expected_objective"]
        # Only the action at THIS boundary is executed. Later stops are not committed.
        now = tuple(PitAction(**s) for s in best["stops"] if s["after_lap"] == state.completed_laps)
        policies = {**actual_opponents, ego: FixedPolicy(now)}
        remaining_path = replace(
            realization, events=tuple(e for e in realization.events if e.lap > state.completed_laps)
        )
        try:
            step = simulate(
                model,
                state,
                physics,
                policies,
                remaining_path,
                history,
                rules,
                state.completed_laps + 1,
            )
        except InfeasibleRacePlan as exc:
            status, reason = "realized_constraint_violation", str(exc)
            break
        state, history = step.final_state, step.pit_history
        trace.extend(step.trace)
    if state.completed_laps == state.total_laps:
        status = "finished"
    return RollingResult(
        status, state, history, trace, decisions, rollouts, perf_counter() - started, reason
    )
