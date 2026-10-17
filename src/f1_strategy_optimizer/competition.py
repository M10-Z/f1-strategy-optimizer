"""Lap-resolution multi-car scenario planning, without calibrated race probabilities.

Policies receive only the visible race state and past pit records. Future events stay
inside the simulator. The existing LapTimeModel interface supplies tyre pace; vehicle
base pace, traffic and event effects are explicit, separately supplied assumptions.
"""

from dataclasses import asdict, dataclass, field, replace
from math import sqrt
from typing import Protocol

from .config import finite_number, positive_int
from .race_constraints import CompetitionRules, InfeasibleRacePlan, nonnegative_int
from .solver import LapTimeModel


@dataclass(frozen=True)
class CarState:
    driver: str
    base_lap_time: float
    compound: str
    tyre_age: int
    elapsed: float = 0.0  # At input: gap to leader; thereafter includes simulated lap costs.
    team: str | None = None
    tyre_inventory: tuple[tuple[str, int], ...] | None = None  # Fresh spare sets, not mounted set.
    used_compounds: tuple[str, ...] = ()
    pit_stops: int = 0

    def __post_init__(self):
        if not self.driver or not self.compound:
            raise ValueError("driver and compound are required")
        finite_number(self.base_lap_time, "base_lap_time", 0.001)
        finite_number(self.elapsed, "elapsed", 0)
        nonnegative_int(self.tyre_age, "tyre_age")
        nonnegative_int(self.pit_stops, "pit_stops")
        if self.team is not None and (not isinstance(self.team, str) or not self.team):
            raise ValueError("team must be a nonempty name or null")
        used = tuple(self.used_compounds)
        if any(not isinstance(c, str) or not c for c in used):
            raise ValueError("used_compounds must contain compound names")
        if self.tyre_age > 0:
            used += (self.compound,)
        object.__setattr__(self, "used_compounds", tuple(sorted(set(used))))
        if self.tyre_inventory is not None:
            items = (
                tuple(self.tyre_inventory.items())
                if isinstance(self.tyre_inventory, dict)
                else tuple(tuple(pair) for pair in self.tyre_inventory)
            )
            if len(dict(items)) != len(items):
                raise ValueError("Inventory compound keys must be unique")
            for compound, count in items:
                if not isinstance(compound, str) or not compound:
                    raise ValueError("Inventory keys must be compound names")
                nonnegative_int(count, "spare tyre sets")
            object.__setattr__(self, "tyre_inventory", tuple(sorted(items)))


@dataclass(frozen=True)
class RaceState:
    completed_laps: int
    total_laps: int
    cars: tuple[CarState, ...]
    track_status: str = "GREEN"
    weather: str = "DRY"
    track_temp: float = 35.0
    season: int | None = None
    event: str = "unspecified"

    def __post_init__(self):
        nonnegative_int(self.completed_laps, "completed_laps")
        positive_int(self.total_laps, "total_laps")
        if self.completed_laps > self.total_laps:
            raise ValueError("completed_laps cannot exceed total_laps")
        if not self.cars or len({c.driver for c in self.cars}) != len(self.cars):
            raise ValueError("Cars must have unique driver identifiers")
        if self.track_status not in {"GREEN", "SC", "VSC"}:
            raise ValueError("track_status must be GREEN, SC or VSC")
        if self.weather not in {"DRY", "WET"}:
            raise ValueError("weather must be DRY or WET")
        finite_number(self.track_temp, "track_temp")
        if self.season is not None:
            positive_int(self.season, "snapshot season")
        if not isinstance(self.event, str) or not self.event:
            raise ValueError("Snapshot event must be named")

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(c.driver for c in sorted(self.cars, key=lambda c: c.elapsed))

    def car(self, driver: str) -> CarState:
        for car in self.cars:
            if car.driver == driver:
                return car
        raise ValueError(f"Unknown driver: {driver}")

    def gaps(self) -> dict[str, float]:
        leader = min(c.elapsed for c in self.cars)
        return {c.driver: c.elapsed - leader for c in self.cars}


@dataclass(frozen=True)
class PitRecord:
    driver: str
    after_lap: int
    compound: str


@dataclass(frozen=True)
class Observation:
    state: RaceState
    pit_history: tuple[PitRecord, ...] = ()


class OpponentPolicy(Protocol):
    def choose(self, observation: Observation, driver: str) -> str | None: ...


@dataclass(frozen=True)
class PitAction:
    after_lap: int | None = None
    compound: str | None = None

    def __post_init__(self):
        if (self.after_lap is None) != (self.compound is None):
            raise ValueError("A pit action requires both lap and compound")
        if self.after_lap is not None:
            nonnegative_int(self.after_lap, "after_lap")
            if not self.compound:
                raise ValueError("A pit action needs a compound")

    @property
    def label(self):
        return (
            "stay-out" if self.after_lap is None else f"pit-after-{self.after_lap}-{self.compound}"
        )


@dataclass(frozen=True)
class FixedPolicy:
    stops: tuple[PitAction, ...] = ()

    def choose(self, observation: Observation, driver: str) -> str | None:
        for stop in self.stops:
            if stop.after_lap == observation.state.completed_laps:
                return stop.compound
        return None


@dataclass(frozen=True)
class PitPlan:
    stops: tuple[PitAction, ...] = ()

    def __post_init__(self):
        if any(stop.after_lap is None for stop in self.stops):
            raise ValueError("PitPlan stops must be actual pit actions")
        laps = [stop.after_lap for stop in self.stops]
        if laps != sorted(set(laps)):
            raise ValueError("PitPlan laps must be strictly increasing")

    @property
    def label(self):
        return ";".join(stop.label for stop in self.stops) or "stay-out"


def _stops(action):
    return (
        action.stops
        if isinstance(action, PitPlan)
        else (() if action.after_lap is None else (action,))
    )


@dataclass(frozen=True)
class PlanningObjective:
    mode: str = "driver_position"
    team: str | None = None

    def __post_init__(self):
        if self.mode not in {"driver_position", "team_rank_sum"}:
            raise ValueError("Objective must be driver_position or team_rank_sum")
        if self.mode == "team_rank_sum" and not self.team:
            raise ValueError("Team objective requires a named team")


@dataclass(frozen=True)
class ReactivePolicy:
    """One upcoming stop: cover an observed undercut or extend for an overcut.

    An opponent's current simultaneous action is NOT visible. A pit completed at
    boundary L is first visible to other drivers at boundary L+1. Reactions are
    bounded by a supplied pit window; no hidden future plan/event is inspected.
    """

    rival: str
    compound: str
    planned_lap: int
    window_start: int
    window_end: int
    mode: str = "cover_undercut"
    overcut_laps: int = 1
    response_gap: float = 10.0

    def __post_init__(self):
        for name in ("planned_lap", "window_start", "window_end", "overcut_laps"):
            nonnegative_int(getattr(self, name), name)
        if not self.window_start <= self.planned_lap <= self.window_end:
            raise ValueError("planned_lap must be inside the response window")
        if self.mode not in {"cover_undercut", "overcut"}:
            raise ValueError("Unknown reactive opponent mode")
        finite_number(self.response_gap, "response_gap", 0)

    def choose(self, observation: Observation, driver: str) -> str | None:
        state = observation.state
        if any(
            p.driver == driver and p.after_lap >= self.window_start for p in observation.pit_history
        ):
            return None
        lap = state.completed_laps
        if not self.window_start <= lap <= self.window_end:
            return None
        rival_pits = [
            p
            for p in observation.pit_history
            if p.driver == self.rival and p.after_lap >= self.window_start - 1
        ]
        target = self.planned_lap
        if rival_pits:
            # Compare observed current gaps, including the rival's completed pit loss.
            gap = abs(state.car(driver).elapsed - state.car(self.rival).elapsed)
            if gap <= self.response_gap:
                observed_at = rival_pits[-1].after_lap + 1
                target = (
                    min(target, observed_at)
                    if self.mode == "cover_undercut"
                    else max(target, observed_at + self.overcut_laps)
                )
        target = min(self.window_end, max(self.window_start, target))
        return self.compound if lap >= target else None


@dataclass(frozen=True)
class Physics:
    reference_lap_time: float = 100.0
    pit_loss: float = 20.0
    following_gap: float = 0.2
    passing_advantage: float = 0.8
    passing_cost: float = 0.3
    sc_pace_factor: float = 1.4
    vsc_pace_factor: float = 1.25
    sc_pit_factor: float = 0.5
    vsc_pit_factor: float = 0.7
    sc_gap: float = 1.0
    sc_catchup_per_lap: float = 5.0
    wet_penalties: dict[str, float] = field(default_factory=dict)
    pit_service_time: float = 0.0  # Resource occupancy; already included in net pit_loss.

    def __post_init__(self):
        for name in (
            "reference_lap_time",
            "pit_loss",
            "following_gap",
            "passing_advantage",
            "passing_cost",
            "sc_gap",
            "sc_catchup_per_lap",
            "sc_pit_factor",
            "vsc_pit_factor",
            "pit_service_time",
        ):
            finite_number(getattr(self, name), name, 0)
        for name in ("sc_pace_factor", "vsc_pace_factor"):
            finite_number(getattr(self, name), name, 1)
        if self.sc_gap < self.following_gap:
            raise ValueError("sc_gap must be >= following_gap")
        for value in self.wet_penalties.values():
            finite_number(value, "wet penalty", 0)

    def pit_cost(self, status):
        return (
            self.pit_loss
            * {"GREEN": 1, "SC": self.sc_pit_factor, "VSC": self.vsc_pit_factor}[status]
        )


@dataclass(frozen=True)
class RaceEvent:
    lap: int  # Revealed AFTER pit decisions at the previous boundary.
    track_status: str | None = None
    weather: str | None = None
    track_temp: float | None = None

    def __post_init__(self):
        positive_int(self.lap, "event lap")
        if self.track_status is not None and self.track_status not in {"GREEN", "SC", "VSC"}:
            raise ValueError("Invalid event track status")
        if self.weather is not None and self.weather not in {"DRY", "WET"}:
            raise ValueError("Invalid event weather")
        if self.track_temp is not None:
            finite_number(self.track_temp, "event track_temp")


@dataclass(frozen=True)
class Scenario:
    name: str
    weight: float
    available_at_lap: int
    events: tuple[RaceEvent, ...] = ()
    kind: str = "hypothetical"
    weight_kind: str = "user_supplied"

    def __post_init__(self):
        if not self.name:
            raise ValueError("Scenario name is required")
        if self.weight_kind != "user_supplied":
            raise ValueError(
                "Only user_supplied weights are supported; no empirical probabilities fitted"
            )
        finite_number(self.weight, "scenario weight", 0.001)
        nonnegative_int(self.available_at_lap, "available_at_lap")
        if self.kind != "hypothetical":
            raise ValueError(
                "Only declared hypothetical scenarios are supported; no future replay data"
            )
        if len({e.lap for e in self.events}) != len(self.events):
            raise ValueError("Combine same-lap changes into a single event")


def _validate_inputs(model, initial, physics, policies, scenario):
    if initial.completed_laps == initial.total_laps:
        raise ValueError("The race has already finished")
    if scenario.available_at_lap > initial.completed_laps:
        raise ValueError("Scenario assumptions were not available at the decision lap")
    if any(not initial.completed_laps < e.lap <= initial.total_laps for e in scenario.events):
        raise ValueError("Scenario events must be after the decision and before race end")
    if set(policies) != set(initial.order):
        raise ValueError("Exactly one policy is required for each driver")
    for car in initial.cars:
        if car.compound not in model.compounds:
            raise ValueError(f"No tyre model for {car.compound}")
    if initial.weather == "WET" or any(e.weather == "WET" for e in scenario.events):
        if set(model.compounds) - set(physics.wet_penalties):
            raise ValueError("Wet scenarios need explicit penalties for every model compound")
    for driver, policy in policies.items():
        stops = policy.stops if isinstance(policy, FixedPolicy) else ()
        if len({s.after_lap for s in stops}) != len(stops):
            raise ValueError("Only one stop per driver per lap is supported")
        for stop in stops:
            if stop.after_lap is not None and not (
                0 <= stop.after_lap < initial.total_laps and stop.compound in model.compounds
            ):
                raise ValueError(
                    "Pit plans need an available tyre and a boundary before the finish"
                )
        if isinstance(policy, ReactivePolicy):
            if policy.rival not in initial.order or policy.rival == driver:
                raise ValueError("Reactive policy requires a different, present rival")
            if policy.compound not in model.compounds:
                raise ValueError("Reactive policy compound is unavailable")
            if not 0 <= policy.window_start <= policy.window_end < initial.total_laps:
                raise ValueError("Reaction window must precede the finish")


@dataclass
class SimulationResult:
    final_state: RaceState
    pit_history: tuple[PitRecord, ...]
    trace: list[dict]


def simulate(
    model: LapTimeModel,
    initial: RaceState,
    physics: Physics,
    policies: dict[str, OpponentPolicy],
    scenario: Scenario,
    observed_pits: tuple[PitRecord, ...] = (),
    rules: CompetitionRules | None = None,
    end_lap: int | None = None,
) -> SimulationResult:
    """Advance same-lap cars. At most one on-track pass per car per lap.

    Pit changes are simultaneous; a stopped car rejoins according to its paid time
    loss. SC/VSC prohibit on-track passing but allow pit-induced order changes.
    SC catch-up is bounded, cannot exceed green-pace travel, and is a scenario
    approximation rather than a safety-car deployment or pit-lane simulator.
    """
    _validate_inputs(model, initial, physics, policies, scenario)
    rules = rules or CompetitionRules()
    rules.check_scope(initial)
    end_lap = initial.total_laps if end_lap is None else end_lap
    positive_int(end_lap, "end_lap")
    if not initial.completed_laps < end_lap <= initial.total_laps:
        raise ValueError("end_lap must be a future lap within the race")
    for pit in observed_pits:
        nonnegative_int(pit.after_lap, "observed pit lap")
        if pit.driver not in initial.order or pit.after_lap >= initial.completed_laps:
            raise ValueError("Observed pit history must precede the decision lap")
    state, history, trace = initial, tuple(sorted(observed_pits, key=lambda p: p.after_lap)), []
    events = {event.lap: event for event in scenario.events}
    while state.completed_laps < end_lap:
        view = Observation(state, history)
        # Collect every action BEFORE exposing any action or advancing an event.
        actions = {driver: policies[driver].choose(view, driver) for driver in state.order}
        if any(c is not None and c not in model.compounds for c in actions.values()):
            raise ValueError("Policy selected an unavailable compound")
        prepared = []
        new_pits = []
        box_ready, waits = {}, {}
        for car in sorted(state.cars, key=lambda c: c.elapsed):
            if actions[car.driver] is None:
                continue
            box = ("team", car.team) if car.team else ("driver", car.driver)
            wait = max(0.0, box_ready.get(box, car.elapsed) - car.elapsed)
            waits[car.driver] = wait
            box_ready[box] = car.elapsed + wait + physics.pit_service_time
        for car in state.cars:
            compound = actions[car.driver]
            if compound is not None:
                inventory = car.tyre_inventory
                if inventory is not None:
                    spare = dict(inventory)
                    if spare.get(compound, 0) < 1:
                        raise InfeasibleRacePlan(f"{car.driver}: no spare {compound} tyre set")
                    spare[compound] -= 1
                    inventory = tuple(sorted(spare.items()))
                new_pits.append(PitRecord(car.driver, state.completed_laps, compound))
                car = replace(
                    car,
                    compound=compound,
                    tyre_age=0,
                    elapsed=car.elapsed + physics.pit_cost(state.track_status) + waits[car.driver],
                    tyre_inventory=inventory,
                    pit_stops=car.pit_stops + 1,
                )
            prepared.append(car)
        lap = state.completed_laps + 1
        event = events.get(lap)
        conditions = state
        if event:
            changes = {k: v for k, v in asdict(event).items() if k != "lap" and v is not None}
            conditions = replace(state, **changes)
        factor = {
            "GREEN": 1,
            "SC": physics.sc_pace_factor,
            "VSC": physics.vsc_pace_factor,
        }[conditions.track_status]
        rows = []
        for car in sorted(prepared, key=lambda c: c.elapsed):
            age = car.tyre_age + 1
            rules.check_lap(car, age)
            tyre_time = model.predict(car.compound, age, conditions.track_temp)
            finite_number(tyre_time, "tyre prediction", 0.001)
            pace = car.base_lap_time + tyre_time - physics.reference_lap_time
            if conditions.weather == "WET":
                pace += physics.wet_penalties[car.compound]
            finite_number(pace, "green-equivalent lap time", 0.001)
            duration = pace * factor
            free_end = car.elapsed + duration
            finish = free_end
            passed = None
            if rows:
                ahead = rows[-1]
                if conditions.track_status == "SC":
                    catchup = min(physics.sc_catchup_per_lap, duration - pace)
                    finish = max(
                        ahead["finish"] + physics.sc_gap,
                        free_end
                        - min(catchup, max(0, free_end - ahead["finish"] - physics.sc_gap)),
                    )
                elif conditions.track_status == "GREEN":
                    pass_end = free_end + physics.passing_cost
                    if len(rows) > 1:
                        pass_end = max(pass_end, rows[-2]["finish"] + physics.following_gap)
                    can_pass = (
                        ahead["duration"] - duration >= physics.passing_advantage
                        and pass_end + physics.following_gap < ahead["finish"]
                    )
                    if can_pass:
                        finish, passed = pass_end, ahead["car"].driver
                    else:
                        finish = max(finish, ahead["finish"] + physics.following_gap)
                else:  # VSC: retain running order and do not compress gaps deliberately.
                    finish = max(finish, ahead["finish"] + physics.following_gap)
            row = {
                "car": replace(car, elapsed=finish, tyre_age=age),
                "finish": finish,
                "duration": duration,
                "adjustment": finish - free_end,
                "passed": passed,
            }
            if passed:
                rows.insert(len(rows) - 1, row)
            else:
                rows.append(row)
        history += tuple(new_pits)
        next_state = replace(conditions, completed_laps=lap, cars=tuple(r["car"] for r in rows))
        trace.append(
            {
                "lap": lap,
                "decision_track_status": state.track_status,
                "decision_weather": state.weather,
                "pit_actions": {d: c for d, c in actions.items() if c is not None},
                "pit_queue_wait_seconds": waits,
                "track_status": next_state.track_status,
                "weather": next_state.weather,
                "order": list(next_state.order),
                "gaps_seconds": next_state.gaps(),
                "tyre_ages": {c.driver: c.tyre_age for c in next_state.cars},
                "remaining_inventory": {
                    c.driver: dict(c.tyre_inventory) if c.tyre_inventory is not None else None
                    for c in next_state.cars
                },
                "pit_counts": {c.driver: c.pit_stops for c in next_state.cars},
                "traffic_adjustment_seconds": {r["car"].driver: r["adjustment"] for r in rows},
                "passes": [
                    {"driver": r["car"].driver, "passed": r["passed"]} for r in rows if r["passed"]
                ],
            }
        )
        state = next_state
    if state.completed_laps == state.total_laps:
        for car in state.cars:
            rules.check_finish(car)
    return SimulationResult(state, history, trace)


def candidate_actions(
    state: RaceState, compounds: tuple[str, ...], pit_laps: tuple[int, ...]
) -> tuple[PitAction, ...]:
    """Generate stay-out and one-stop plans using only visible state and user choices."""
    _check_candidate_grid(state, compounds, pit_laps)
    return (PitAction(),) + tuple(PitAction(lap, c) for lap in pit_laps for c in compounds)


def _check_candidate_grid(state, compounds, pit_laps):
    if not compounds or len(set(compounds)) != len(compounds):
        raise ValueError("Candidate compounds must be nonempty and unique")
    if len(set(pit_laps)) != len(pit_laps):
        raise ValueError("Candidate pit laps must be unique")
    for lap in pit_laps:
        nonnegative_int(lap, "candidate pit lap")
        if not state.completed_laps <= lap < state.total_laps:
            raise ValueError("Candidate pit laps must precede the finish and not be in the past")


def candidate_plans(
    state: RaceState,
    compounds: tuple[str, ...],
    pit_laps: tuple[int, ...],
    max_stops: int = 2,
    max_candidates: int = 500,
) -> tuple[PitPlan, ...]:
    """Bounded zero/one/two-stop grid; reject oversize searches before enumeration."""
    from itertools import combinations, product
    from math import comb

    _check_candidate_grid(state, compounds, pit_laps)
    nonnegative_int(max_stops, "max_stops")
    positive_int(max_candidates, "max_candidates")
    if max_stops > 2:
        raise ValueError("Bounded planning currently supports at most two future stops")
    size = sum(
        comb(len(pit_laps), k) * len(compounds) ** k
        for k in range(min(max_stops, len(pit_laps)) + 1)
    )
    if size > max_candidates:
        raise ValueError(
            f"Candidate grid has {size} plans, exceeding budget {max_candidates}; narrow the grid"
        )
    plans = []
    for count in range(min(max_stops, len(pit_laps)) + 1):
        for laps in combinations(sorted(pit_laps), count):
            for tyres in product(compounds, repeat=count):
                plans.append(PitPlan(tuple(PitAction(lap, tyre) for lap, tyre in zip(laps, tyres))))
    return tuple(plans)


def plan_positions(
    model: LapTimeModel,
    initial: RaceState,
    physics: Physics,
    ego: str,
    opponents: dict[str, OpponentPolicy],
    actions: tuple[PitAction | PitPlan, ...],
    scenarios: tuple[Scenario, ...],
    risk_top_k: int = 3,
    observed_pits: tuple[PitRecord, ...] = (),
    rules: CompetitionRules | None = None,
    objective: PlanningObjective | None = None,
    max_rollouts: int = 2000,
) -> dict:
    """Rank common plans across all declared cases; never reweight infeasible cases.

    v1 PitAction inputs and action serialization remain valid. PitPlan adds two
    stops. Team objectives optimize the ego's schedule for a declared team rank
    sum, not joint control of teammates or championship points.
    """
    from copy import deepcopy
    from time import perf_counter

    started = perf_counter()
    initial.car(ego)
    positive_int(risk_top_k, "risk_top_k")
    positive_int(max_rollouts, "max_rollouts")
    rules = rules or CompetitionRules()
    rules.check_scope(initial)
    objective = objective or PlanningObjective()
    team_drivers = (
        [c.driver for c in initial.cars if c.team == objective.team] if objective.team else []
    )
    if objective.mode == "team_rank_sum" and (ego not in team_drivers or len(team_drivers) < 2):
        raise ValueError("Team objective requires the ego and at least one teammate in the field")
    if set(opponents) != set(initial.order) - {ego}:
        raise ValueError("Provide a policy for every opponent and none for the ego")
    if not actions or len({a.label for a in actions}) != len(actions):
        raise ValueError("Candidate actions must be nonempty and unique")
    if not scenarios or len({s.name for s in scenarios}) != len(scenarios):
        raise ValueError("Scenarios must be nonempty and uniquely named")
    if len(actions) * len(scenarios) > max_rollouts:
        raise ValueError("Candidate/scenario product exceeds the rollout budget")
    for action in actions:
        stops = _stops(action)
        if len(stops) > 2 or any(
            not initial.completed_laps <= s.after_lap < initial.total_laps for s in stops
        ):
            raise ValueError("Candidates allow at most two future stops before the finish")
    weight_sum = sum(s.weight for s in scenarios)
    finite_number(weight_sum, "total scenario weight", 0.001)
    results, rejected, rollout_count = [], [], 0
    for action in actions:
        outcomes, distribution, failure = [], {}, None
        for scenario in scenarios:
            policies = deepcopy(opponents)
            policies[ego] = FixedPolicy(_stops(action))
            rollout_count += 1
            try:
                rollout = simulate(
                    model, initial, physics, policies, scenario, observed_pits, rules
                )
            except InfeasibleRacePlan as exc:
                failure = {"scenario": scenario.name, "reason": str(exc)}
                break
            order = rollout.final_state.order
            position = order.index(ego) + 1
            team_positions = {d: order.index(d) + 1 for d in team_drivers}
            score = sum(team_positions.values()) if objective.mode == "team_rank_sum" else position
            weight = scenario.weight / weight_sum
            distribution[position] = distribution.get(position, 0) + weight
            outcomes.append(
                {
                    "scenario": scenario.name,
                    "weight": weight,
                    "finish_position": position,
                    "objective_value": score,
                    "team_finish_positions": team_positions,
                    "finish_order": list(order),
                    "finish_gap_seconds": rollout.final_state.gaps()[ego],
                    "ego_elapsed_seconds": rollout.final_state.car(ego).elapsed
                    - initial.car(ego).elapsed,
                    "driver_elapsed_seconds": {
                        c.driver: c.elapsed - initial.car(c.driver).elapsed
                        for c in rollout.final_state.cars
                    },
                    "pit_history": [asdict(p) for p in rollout.pit_history],
                    "final_resources": {
                        c.driver: {
                            "inventory": dict(c.tyre_inventory)
                            if c.tyre_inventory is not None
                            else None,
                            "used_compounds": list(c.used_compounds),
                            "pit_stops": c.pit_stops,
                        }
                        for c in rollout.final_state.cars
                    },
                    "trace": rollout.trace,
                }
            )
        if failure:
            rejected.append(
                {"label": action.label, "action": asdict(action), "first_failure": failure}
            )
            continue
        expected = sum(position * weight for position, weight in distribution.items())
        variance = sum(
            weight * (position - expected) ** 2 for position, weight in distribution.items()
        )
        results.append(
            {
                "action": asdict(action),
                "stops": [asdict(s) for s in _stops(action)],
                "label": action.label,
                "expected_finish_position": expected,
                "worst_finish_position": max(distribution),
                "expected_objective": sum(o["weight"] * o["objective_value"] for o in outcomes),
                "worst_objective": max(o["objective_value"] for o in outcomes),
                "expected_elapsed_seconds": sum(
                    o["weight"] * o["ego_elapsed_seconds"] for o in outcomes
                ),
                "position_std": sqrt(variance),
                "weighted_share_outside_top_k": sum(
                    w for p, w in distribution.items() if p > risk_top_k
                ),
                "position_distribution": {str(p): w for p, w in sorted(distribution.items())},
                "outcomes": outcomes,
            }
        )
    results.sort(
        key=lambda row: (
            row["expected_objective"],
            row["worst_objective"],
            row["expected_finish_position"],
            len(row["stops"]),
            row["label"],
        )
    )
    return {
        "schema_version": 1 if all(isinstance(action, PitAction) for action in actions) else 2,
        "status": "feasible" if results else "no_feasible_candidate",
        "objective": (
            "scenario-weighted objective, then worst objective and ego position; "
            "ties prefer fewer stops then label"
        ),
        "objective_config": asdict(objective),
        "claim": "Scenario simulation, not calibrated probabilities or a guaranteed optimum",
        "weight_interpretation": (
            "user_supplied_scenario_weights; no empirical probability estimate"
        ),
        "feasibility": (
            "Configured inventory and race-rule subset checked for every car in every "
            "supplied scenario; not full FIA compliance"
        ),
        "rules": asdict(rules),
        "inventory_scope": {
            c.driver: "finite_fresh_spares"
            if c.tyre_inventory is not None
            else "unspecified_unlimited"
            for c in initial.cars
        },
        "decision_lap": initial.completed_laps,
        "ego": ego,
        "risk_top_k": risk_top_k,
        "recommended_action": results[0]["action"] if results else None,
        "recommended_stops": results[0]["stops"] if results else None,
        "ranking": results,
        "rejected_candidates": rejected,
        "search": {
            "candidate_count": len(actions),
            "scenario_count": len(scenarios),
            "rollout_budget": max_rollouts,
            "rollouts_executed": rollout_count,
            "feasible_candidates": len(results),
            "elapsed_seconds": perf_counter() - started,
        },
        "limits": [
            "Same-lap field and assumed vehicle pace; no causal telemetry identification",
            "At most one on-track pass per car per lap; pit-box arrivals use boundary gaps",
            "Finite fresh spares only when supplied; removed sets are not returned to stock",
            "Declared rule subset only; no automatic rules, red flags or wet-start directives",
            "User weights, not empirical probabilities; worst result covers supplied cases only",
            "Team objective changes ego plan only; no joint search, team orders, DNF or penalties",
        ],
    }
