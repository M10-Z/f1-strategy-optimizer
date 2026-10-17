"""Explicit hypothetical strategy exploration from a verified frozen observation.

No archive or outcome is accepted. A supplied same-lap model is a research
abstraction of asynchronous observations, with no verified action boundary or
historical availability claim. Every simulated value comes from the frozen
record, user assumptions or a disclosed model default.
"""

import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from math import comb
from pathlib import Path

from .artifacts import write_json
from .competition import Physics
from .config import finite_number, positive_int
from .event_replay import digest, verify_frozen
from .race_constraints import CompetitionRules, nonnegative_int
from .race_planner import ExplicitTyrePace, plan_from_document
from .replay import timestamp

ACKNOWLEDGEMENTS = (
    "exploratory_only",
    "same_lap_abstraction",
    "asynchronous_gap_projection",
    "no_verified_action_boundary",
    "no_actual_future_used",
    "uncalibrated_scenarios",
)
ASSUMPTION_GROUPS = (
    "state_alignment",
    "conditions",
    "pace_and_physics",
    "tyres",
    "inventory",
    "opponents",
    "scenarios",
    "rules",
)
MAX_TOTAL_ROLLOUTS = 10_000
MAX_SENSITIVITIES = 5


def _engine_manifest():
    package = Path(__file__).resolve().parent
    names = (
        "strategy_exploration.py",
        "competition.py",
        "race_planner.py",
        "config.py",
        "race_constraints.py",
        "event_replay.py",
        "replay.py",
        "artifacts.py",
    )
    return {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in names}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires an explicit nonempty explanation")
    return value


def _utc(value, name):
    parsed = timestamp(value, name)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return parsed


def _required(document, keys, name):
    if not isinstance(document, dict) or set(keys) - set(document):
        raise ValueError(f"{name} requires explicit fields: {', '.join(keys)}")


def _scope(frozen, assumptions, planning):
    observed = frozen["state"]["cars"]
    ids = [car["id"] for car in observed]
    model_ids = [car["driver"] for car in planning["state"]["cars"]]
    if not ids or len(ids) != len(set(ids)) or len(model_ids) != len(set(model_ids)):
        raise ValueError("Frozen and modeled fields require unique driver IDs")
    if not model_ids or set(model_ids) - set(ids):
        raise ValueError("Modeled drivers must belong to the frozen field")
    subset = assumptions.get("model_subset")
    if set(model_ids) != set(ids) and subset is None:
        raise ValueError("A reduced field requires an explicit model_subset acknowledgement")
    if subset is not None:
        _required(subset, ("drivers", "acknowledged", "rationale"), "model_subset")
        if (
            subset["acknowledged"] is not True
            or len(subset["drivers"]) != len(model_ids)
            or set(subset["drivers"]) != set(model_ids)
        ):
            raise ValueError("model_subset must explicitly acknowledge exactly the modeled field")
        _text(subset["rationale"], "model_subset.rationale")
    reduced = set(model_ids) != set(ids)
    return {
        "kind": "model_subset" if reduced else "all_frozen_drivers",
        "drivers": sorted(model_ids),
        "excluded_drivers": sorted(set(ids) - set(model_ids)),
        "modeled_driver_count": len(model_ids),
        "frozen_driver_count": len(ids),
        "rank_semantics": "WITHIN MODEL SUBSET ONLY; NOT FULL RACE CLASSIFICATION"
        if reduced
        else "Within the user-assumed modeled field; not observed race classification",
        "rationale": subset["rationale"] if subset else "Every frozen driver modeled explicitly",
    }


def _validate(frozen, assumptions):
    verify_frozen(frozen)
    if {
        "archive",
        "outcome",
        "actual_future",
        "source_manifest",
        "source_audit",
        "evaluations",
    } & set(frozen):
        raise ValueError(
            "Exploration accepts a frozen decision only, never archive/outcome evidence"
        )
    _required(frozen, ("cutoff", "state", "decision_sha256"), "frozen decision")
    cutoff = _utc(frozen["cutoff"], "frozen.cutoff")
    if timestamp(frozen["state"]["cutoff"], "state.cutoff") != cutoff:
        raise ValueError("Frozen record and state cutoffs differ")
    allowed = {
        "schema_version",
        "acknowledgement",
        "action_boundary",
        "planning",
        "field_assumptions",
        "inventory_policy",
        "model_subset",
        "sensitivity",
        "max_total_rollouts",
        "selection_preference",
    }
    _required(assumptions, allowed - {"model_subset", "selection_preference"}, "assumptions")
    if set(assumptions) - allowed or assumptions["schema_version"] != 1:
        raise ValueError(
            "Unsupported exploration schema or unknown inputs (archives/outcomes forbidden)"
        )
    ack = assumptions["acknowledgement"]
    if not isinstance(ack, dict) or any(ack.get(k) is not True for k in ACKNOWLEDGEMENTS):
        raise ValueError("All exploration acknowledgements must be explicitly true")
    reasons = assumptions["field_assumptions"]
    _required(reasons, ASSUMPTION_GROUPS, "field_assumptions")
    for group in ASSUMPTION_GROUPS:
        _required(reasons[group], ("source", "rationale"), f"field_assumptions.{group}")
        _text(reasons[group]["source"], f"{group}.source")
        _text(reasons[group]["rationale"], f"{group}.rationale")
    planning = deepcopy(assumptions["planning"])
    _required(
        planning,
        (
            "state",
            "source",
            "ego",
            "physics",
            "tyres",
            "opponents",
            "scenarios",
            "candidates",
            "rules",
            "objective",
        ),
        "planning",
    )
    if "rolling" in planning or "joint" in planning:
        raise ValueError("Exploration supports bounded single-ego snapshots, not rolling or joint")
    if planning.get("observed_pits"):
        raise ValueError(
            "Do not inject historical pit actions; declare hypothetical opponent policies"
        )
    if planning["objective"] != {"mode": "driver_position"}:
        raise ValueError("Exploration v1 requires the individual driver_position objective")
    state = planning["state"]
    _required(
        state,
        (
            "season",
            "event",
            "completed_laps",
            "total_laps",
            "cars",
            "track_status",
            "weather",
            "track_temp",
        ),
        "planning.state",
    )
    positive_int(state["season"], "season")
    if state["season"] != frozen["state"]["session"]["year"]:
        raise ValueError("Assumed season must match the frozen event")
    if _text(state["event"], "event") == "unspecified":
        raise ValueError("A named event is required")
    nonnegative_int(state["completed_laps"], "completed_laps")
    positive_int(state["total_laps"], "total_laps")
    if not 1 <= state["total_laps"] - state["completed_laps"] <= 30:
        raise ValueError("Exploration horizon must contain 1..30 modeled laps")
    if not isinstance(state["cars"], list) or not 1 <= len(state["cars"]) <= 30:
        raise ValueError("Provide 1..30 explicit modeled cars")
    inventory = assumptions["inventory_policy"]
    _required(inventory, ("kind", "acknowledged"), "inventory_policy")
    if inventory["kind"] not in {"finite", "unknown_unlimited_model"} or (
        inventory["acknowledged"] is not True
    ):
        raise ValueError(
            "Explicit finite or acknowledged unknown_unlimited_model inventory required"
        )
    for car in state["cars"]:
        _required(
            car,
            (
                "driver",
                "team",
                "gap_seconds",
                "compound",
                "tyre_age",
                "base_lap_time",
                "tyre_inventory",
                "used_compounds",
                "pit_stops",
            ),
            "planning car",
        )
        _text(car["team"], "car.team")
        if any(car[k] is None for k in ("gap_seconds", "compound", "tyre_age", "base_lap_time")):
            raise ValueError(
                f"{car['driver']} 缺少间距、配方、胎龄或基础圈时；"
                "请手工填写并注明假设，或调整参与车阵。未知值不会自动补齐"
            )
        if inventory["kind"] == "finite":
            if not isinstance(car["tyre_inventory"], dict):
                raise ValueError(
                    "Finite inventory requires an explicit spare-set dictionary per car"
                )
        elif car["tyre_inventory"] is not None:
            raise ValueError(
                "unknown_unlimited_model requires explicit null inventories for every car"
            )
    scope = _scope(frozen, assumptions, planning)
    preference = assumptions.get("selection_preference", {"mode": "mean_position"})
    if preference not in ({"mode": "mean_position"}, {"mode": "conservative"}):
        raise ValueError("selection_preference must be mean_position or conservative")
    positive_int(planning.get("risk_top_k", 3), "risk_top_k")
    if "selection_preference" in assumptions and planning["risk_top_k"] > len(state["cars"]):
        raise ValueError("目标名次不能超过参与车辆数；名次仅在所选模型车阵内有效")
    if set(planning["opponents"]) != set(scope["drivers"]) - {planning["ego"]}:
        raise ValueError("Supply an explicit hypothetical policy for every opponent")
    boundary = assumptions["action_boundary"]
    _required(boundary, ("kind", "effective_at", "after_lap", "rationale"), "action_boundary")
    if boundary["kind"] != "abstract_next_pit_entry_boundary":
        raise ValueError("action_boundary must be abstract_next_pit_entry_boundary")
    nonnegative_int(boundary["after_lap"], "action_boundary.after_lap")
    if boundary["after_lap"] != state["completed_laps"]:
        raise ValueError("Action boundary must match the modeled completed_laps")
    if (
        boundary["effective_at"] is not None
        and _utc(boundary["effective_at"], "action_boundary.effective_at") < cutoff
    ):
        raise ValueError("Assumed action effective_at precedes the frozen cutoff")
    _text(boundary["rationale"], "action_boundary.rationale")
    _required(planning["physics"], ("pit_loss", "reference_lap_time"), "planning.physics")
    # Disclose every resolved default; user values are never inferred from future data.
    planning["physics"] = asdict(Physics(**planning["physics"]))
    planning["rules"] = asdict(CompetitionRules(**planning["rules"]))
    planning.setdefault("risk_top_k", 3)
    scenarios = planning["scenarios"]
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 8:
        raise ValueError("Provide 1..8 explicitly hypothetical scenarios")
    for scenario in scenarios:
        _required(scenario, ("name", "weight", "available_at_lap", "events"), "scenario")
        if scenario["available_at_lap"] != state["completed_laps"]:
            raise ValueError(
                "available_at_lap is the declared research model boundary, not historic UTC"
            )
        if scenario.get("kind", "hypothetical") != "hypothetical":
            raise ValueError("Actual-future scenarios are forbidden")
    grid = planning["candidates"]
    _required(
        grid,
        ("pit_laps", "compounds", "max_stops", "max_candidates", "max_rollouts"),
        "planning.candidates",
    )
    laps, compounds = grid["pit_laps"], grid["compounds"]
    if len(laps) != len(set(laps)) or len(compounds) != len(set(compounds)) or not compounds:
        raise ValueError("Candidate laps and compounds must be unique; compounds cannot be empty")
    nonnegative_int(grid["max_stops"], "max_stops")
    if grid["max_stops"] > 2:
        raise ValueError("At most two future stops supported")
    for lap in laps:
        nonnegative_int(lap, "candidate pit lap")
        if not state["completed_laps"] <= lap < state["total_laps"]:
            raise ValueError("Candidate pit boundaries must lie within the declared model horizon")
    count = sum(
        comb(len(laps), k) * len(compounds) ** k
        for k in range(min(grid["max_stops"], len(laps)) + 1)
    )
    positive_int(grid["max_candidates"], "max_candidates")
    positive_int(grid["max_rollouts"], "max_rollouts")
    if count > min(grid["max_candidates"], 500) or count * len(scenarios) > grid["max_rollouts"]:
        raise ValueError("Candidate/scenario grid exceeds its explicit bounded budget")
    return planning, scope, count * len(scenarios)


def _patch(planning, change):
    _required(change, ("name", "path", "value", "rationale"), "sensitivity item")
    if set(change) != {"name", "path", "value", "rationale"}:
        raise ValueError("Sensitivity items apply exactly one numeric path/value patch")
    _text(change["name"], "sensitivity.name")
    _text(change["rationale"], "sensitivity.rationale")
    parts = _text(change["path"], "sensitivity.path").split(".")
    valid = (len(parts) == 2 and parts[0] == "physics") or (
        len(parts) == 3 and parts[0] == "tyres" and parts[-1] in {"base_time", "degradation"}
    )
    if not valid:
        raise ValueError("Sensitivity path must select one physics or tyre numeric parameter")
    result = deepcopy(planning)
    node = result
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            raise ValueError("Sensitivity path does not exist")
        node = node[part]
    if parts[-1] not in node:
        raise ValueError("Sensitivity parameter does not exist")
    old = node[parts[-1]]
    finite_number(old, "sensitivity original value")
    finite_number(change["value"], "sensitivity value")
    node[parts[-1]] = change["value"]
    if parts[0] == "physics":
        Physics(**result["physics"])
    else:
        ExplicitTyrePace(**result["tyres"][parts[1]])
    return result, old


def _leaves(value, prefix=""):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from _leaves(child, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from _leaves(child, f"{prefix}.{index}")
    else:
        yield prefix, value


def _overrides(frozen, assumptions, planning):
    state, originals = frozen["state"], {}
    originals["state.season"] = state["session"]["year"]
    originals["state.completed_laps"] = {
        car["id"]: car.get("completed_laps") for car in state["cars"]
    }
    originals["state.track_status"] = state.get("track_status")
    originals["state.weather"] = state.get("surface_condition")
    observation = state.get("weather_observation", {}).get("value")
    originals["state.track_temp"] = observation.get("track_temperature") if observation else None
    by_id = {car["id"]: car for car in state["cars"]}
    renamed = {"tyre_age": "estimated_completed_tyre_age", "driver": "id"}
    for index, car in enumerate(planning["state"]["cars"]):
        original = by_id[car["driver"]]
        for key in car:
            originals[f"state.cars.{index}.{key}"] = original.get(renamed.get(key, key))
    result = []
    for path, assumed in _leaves(planning):
        if path.startswith("state.cars."):
            field = path.split(".")[3]
            group = (
                "inventory"
                if field in {"tyre_inventory", "used_compounds", "pit_stops"}
                else ("pace_and_physics" if field == "base_lap_time" else "state_alignment")
            )
        elif path.startswith("state."):
            group = (
                "conditions"
                if path.split(".")[1] in {"weather", "track_status", "track_temp"}
                else "state_alignment"
            )
        else:
            group = {
                "physics": "pace_and_physics",
                "tyres": "tyres",
                "opponents": "opponents",
                "scenarios": "scenarios",
                "rules": "rules",
            }.get(path.split(".")[0], "state_alignment")
        section = path.split(".")[0]
        model_default = (
            section in {"physics", "rules"}
            and len(path.split(".")) > 1
            and path.split(".")[1] not in assumptions["planning"][section]
        ) or (path == "risk_top_k" and path not in assumptions["planning"])
        explanation = assumptions["field_assumptions"][group]
        entry = {
            "path": path,
            "original": deepcopy(originals.get(path)),
            "assumed_value": deepcopy(assumed),
            "assumption_group": group,
            "origin": "model_default" if model_default else "user_supplied_assumption",
            "source": f"planner {section} default" if model_default else explanation["source"],
            "rationale": explanation["rationale"],
            "original_status": "recorded_in_frozen_input"
            if path in originals
            else "not_recorded_in_frozen_input",
        }
        if path.startswith("state.cars."):
            entry["driver"] = planning["state"]["cars"][int(path.split(".")[2])]["driver"]
        result.append(entry)
    return result


def _candidate(row, planning, stay_out):
    """Add simulated trace proxies and matched-scenario teammate differences."""
    result = deepcopy(row)
    ego = planning["ego"]
    team = next(c["team"] for c in planning["state"]["cars"] if c["driver"] == ego)
    mates = [
        c["driver"] for c in planning["state"]["cars"] if c["team"] == team and c["driver"] != ego
    ]
    references = {o["scenario"]: o for o in stay_out["outcomes"]} if stay_out else {}
    details = []
    for outcome in row["outcomes"]:
        first = next((t for t in outcome["trace"] if ego in t["pit_actions"]), None)
        proxy = None
        if first:
            order = first["order"]
            index = order.index(ego)
            ahead = order[index - 1] if index else None
            behind = order[index + 1] if index + 1 < len(order) else None
            gaps = first["gaps_seconds"]
            proxy = {
                "kind": "simulated_first_post_stop_lap_proxy_not_exact_pit_exit",
                "lap": first["lap"],
                "position": index + 1,
                "ahead": ahead,
                "behind": behind,
                "gap_to_ahead_seconds": gaps[ego] - gaps[ahead] if ahead else None,
                "gap_from_behind_seconds": gaps[behind] - gaps[ego] if behind else None,
                "traffic_adjustment_seconds": first["traffic_adjustment_seconds"][ego],
                "pit_queue_wait_seconds": first["pit_queue_wait_seconds"].get(ego, 0),
            }
        ref = references.get(outcome["scenario"])
        costs = {}
        for mate in mates:
            costs[mate] = (
                None
                if ref is None
                else {
                    "elapsed_delta_vs_same_scenario_stay_out_seconds": (
                        outcome["driver_elapsed_seconds"][mate]
                        - ref["driver_elapsed_seconds"][mate]
                    ),
                    "position_delta_vs_same_scenario_stay_out": (
                        outcome["finish_order"].index(mate) - ref["finish_order"].index(mate)
                    ),
                    "simulated_queue_wait_seconds": sum(
                        t["pit_queue_wait_seconds"].get(mate, 0) for t in outcome["trace"]
                    ),
                }
            )
        details.append(
            {
                "scenario": outcome["scenario"],
                "first_post_stop_lap_proxy": proxy,
                "simulated_teammate_costs": costs,
            }
        )
    result["simulation_details"] = details
    result["interpretation"] = "Hypothetical model prediction; no factual strategy-gain score"
    result["position_semantics"] = "simulated_horizon_end_position_not_actual_finish"
    result["horizon_end_lap"] = planning["state"]["total_laps"]
    return result


def propose_exploration(frozen, assumptions):
    """Propose up to three feasible hypothetical plans plus an independent stay-out.

    Inputs are never mutated. All base/variant planning inputs and hashes are
    prepared before the first rollout. The caller must supply every modeled car
    and acknowledge the same-lap abstraction, projected gaps and unknown boundary.
    The result contains no archive-derived outcome or causal performance score.
    """
    planning, scope, cost = _validate(frozen, assumptions)
    changes = assumptions["sensitivity"]
    if not isinstance(changes, list) or len(changes) > MAX_SENSITIVITIES:
        raise ValueError("Provide at most five single-parameter sensitivity changes")
    budget = assumptions["max_total_rollouts"]
    positive_int(budget, "max_total_rollouts")
    if budget > MAX_TOTAL_ROLLOUTS or cost * (1 + len(changes)) > budget:
        raise ValueError("Base plus all sensitivities exceed the cumulative rollout budget")
    if len({c["name"] for c in changes}) != len(changes) or any(
        c["name"] == "baseline" for c in changes
    ):
        raise ValueError("Sensitivity names must be unique and not baseline")
    variants = [("baseline", planning, None, None)]
    for change in changes:
        variant, old = _patch(planning, change)
        variants.append((change["name"], variant, change, old))
    context = {
        key: deepcopy(assumptions[key])
        for key in ("acknowledgement", "action_boundary", "field_assumptions", "inventory_policy")
    }
    context["model_scope"] = scope
    preference = assumptions.get("selection_preference", {"mode": "mean_position"})
    context["selection_preference"] = preference
    engine_hashes = _engine_manifest()
    freezes = []
    for name, resolved, _, _ in variants:
        envelope = {
            "decision_sha256": frozen["decision_sha256"],
            "planning": resolved,
            "assumption_context": context,
            "engine_source_sha256": engine_hashes,
        }
        freezes.append({"name": name, "sha256": digest(envelope), "resolved_input": envelope})
    # No planner invocation, archive or outcome access occurs before this point.
    reports = [plan_from_document(deepcopy(v[1])) for v in variants]
    if preference["mode"] == "conservative":
        for candidate_report in reports:
            candidate_report["ranking"].sort(
                key=lambda row: (
                    row["worst_finish_position"],
                    row["weighted_share_outside_top_k"],
                    row["expected_finish_position"],
                    len(row["stops"]),
                    row["label"],
                )
            )
    report = reports[0]
    ranking = report["ranking"]
    stay = next((r for r in ranking if not r["stops"]), None)
    rejected_stay = next(
        (r for r in report["rejected_candidates"] if r["label"] == "stay-out"), None
    )
    winner = ranking[0]["label"] if ranking else None
    sensitivities = []
    labels = {winner} if winner else set()
    winner_positions = [ranking[0]["expected_finish_position"]] if ranking else []
    for index, (name, variant, change, old) in enumerate(variants[1:], 1):
        rows = reports[index]["ranking"]
        selected = rows[0] if rows else None
        label = selected["label"] if selected else None
        if label:
            labels.add(label)
            winner_positions.append(selected["expected_finish_position"])
        base_plan = next((r for r in rows if r["label"] == winner), None)
        sensitivities.append(
            {
                "name": name,
                "path": change["path"],
                "original_value": old,
                "assumed_value": change["value"],
                "rationale": change["rationale"],
                "resolved_input_sha256": freezes[index]["sha256"],
                "winner": label,
                "winner_changed": label != winner,
                "winner_expected_position": selected["expected_finish_position"]
                if selected
                else None,
                "baseline_plan_rank_in_variant": next(
                    (i + 1 for i, r in enumerate(rows) if r["label"] == winner), None
                ),
                "baseline_plan_expected_position": base_plan["expected_finish_position"]
                if base_plan
                else None,
                "status": reports[index]["status"],
            }
        )
    order = report["initial_order"]
    ego_index = order.index(planning["ego"])
    gaps = report["initial_gaps_seconds"]
    ego_gap = gaps[planning["ego"]]
    ahead = order[ego_index - 1] if ego_index else None
    behind = order[ego_index + 1] if ego_index + 1 < len(order) else None
    return {
        "schema_version": 1,
        "kind": "explicit_assumption_strategy_exploration",
        "status": report["status"],
        "cutoff": frozen["cutoff"],
        "claim": (
            "Exploratory simulation under user assumptions; no causal or factual strategy gain"
        ),
        "decision_sha256": frozen["decision_sha256"],
        "assumptions_sha256": digest(assumptions),
        "assumption_time_semantics": "hindsight_user_declared; historical availability unknown",
        "engine_source_sha256": engine_hashes,
        "model_horizon": {
            "after_lap": planning["state"]["completed_laps"],
            "through_lap": planning["state"]["total_laps"],
            "modeled_laps": planning["state"]["total_laps"] - planning["state"]["completed_laps"],
        },
        "position_semantics": (
            "All finish_position fields inherited from the engine mean MODEL HORIZON-END rank; "
            "a short horizon is not the actual race finish"
        ),
        "action_boundary": deepcopy(assumptions["action_boundary"]),
        "model_scope": scope,
        "inventory_policy": deepcopy(assumptions["inventory_policy"]),
        "inventory_feasibility": "configured finite spare stocks only"
        if (assumptions["inventory_policy"]["kind"] == "finite")
        else "UNKNOWN STOCK; UNLIMITED MODEL IS NOT INVENTORY FEASIBILITY",
        "field_overrides": _overrides(frozen, assumptions, planning),
        "top3": [_candidate(row, planning, stay) for row in ranking[:3]],
        "stay_out": {
            "status": "feasible" if stay else "infeasible",
            "candidate": _candidate(stay, planning, stay) if stay else None,
            "rejection": deepcopy(rejected_stay),
        },
        "selection_preference": {
            **preference,
            "target_top_k": planning["risk_top_k"],
            "ordering": "worst rank, weighted share missing target, mean rank, fewer stops"
            if preference["mode"] == "conservative"
            else "mean rank, worst rank, fewer stops",
            "weight_notice": "Subjective scenario shares, not calibrated failure probabilities",
        },
        "modeled_participants": deepcopy(planning["state"]["cars"]),
        "opponent_policies": deepcopy(planning["opponents"]),
        "covered_scenarios": deepcopy(planning["scenarios"]),
        "modeled_conditions": {
            key: planning["state"][key] for key in ("track_status", "weather", "track_temp")
        },
        "initial_threats": {
            "kind": "user_assumed_initial_gaps",
            "ahead": ahead,
            "behind": behind,
            "gap_to_ahead_seconds": ego_gap - gaps[ahead] if ahead else None,
            "gap_from_behind_seconds": gaps[behind] - ego_gap if behind else None,
        },
        "sensitivity": {
            "baseline_winner": winner,
            "cases": sensitivities,
            "winner_labels": sorted(labels),
            "winning_position_range": [min(winner_positions), max(winner_positions)]
            if winner_positions
            else None,
            "notice": (
                "Finite declared perturbations only; no reversal does not establish robustness"
            ),
        },
        "input_freezes": freezes,
        "budget": {
            "limit": budget,
            "preflight_rollout_upper_bound": cost * len(variants),
            "rollouts_executed": sum(r["search"]["rollouts_executed"] for r in reports),
            "searches": len(reports),
        },
        "search": {k: v for k, v in report["search"].items() if k != "elapsed_seconds"},
        "rejected_candidates": deepcopy(report["rejected_candidates"]),
        "limitations": [
            scope["rank_semantics"],
            "Engine finish_position fields denote modeled horizon-end rank, not actual race finish",
            "Same-lap abstraction and assumed gap projection; not measured synchronous field state",
            "Action boundary and exact pit-entry/exit UTC remain unverified "
            "even when a UTC is assumed",
            "Vehicle pace, tyre curves, future opponent actions and scenarios are user assumptions",
            "Scenario weights are not calibrated probabilities; no actual future is injected",
            "First post-stop lap traffic is a simulated proxy, not an exact pit-exit forecast",
            "Teammate deltas compare matched scenarios to feasible stay-out; "
            "missing reference gives null",
            "Rule subset and optional stocks are configured assumptions, not full FIA compliance",
            "Limited sensitivities do not validate model accuracy or causal strategy benefit",
        ],
    }


def _select(document, cutoff):
    records = document if isinstance(document, list) else [document]
    if not records or len(records) > 100 or any(not isinstance(r, dict) for r in records):
        raise ValueError("Decision file must contain one record or a bounded list of records")
    if cutoff is None:
        if len(records) != 1:
            raise ValueError("--cutoff is required to select from a decision batch")
        return records[0]
    requested = _utc(cutoff, "selected cutoff")
    matches = [r for r in records if _utc(r["cutoff"], "record.cutoff") == requested]
    if len(matches) != 1:
        raise ValueError("--cutoff must select exactly one frozen decision")
    return matches[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-file", type=Path, required=True)
    parser.add_argument("--cutoff", help="Explicit UTC selection when the decision file is a batch")
    parser.add_argument("--assumptions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.expanduser()
        if output.exists():
            raise ValueError("Output directory already exists; choose a new directory")
        raw_decision = args.decision_file.read_bytes()
        raw_assumptions = args.assumptions.read_bytes()
        if max(len(raw_decision), len(raw_assumptions)) > 20_000_000:
            raise ValueError("Input file exceeds the 20 MB budget")
        frozen = _select(json.loads(raw_decision), args.cutoff)
        assumptions = json.loads(raw_assumptions)
        report = propose_exploration(frozen, assumptions)
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "exploration.json", report)
        write_json(output / "resolved-inputs.json", report["input_freezes"])
        lines = [
            "# Explicit-assumption strategy exploration",
            "",
            report["claim"],
            "",
            report["model_scope"]["rank_semantics"],
            "",
            report["inventory_feasibility"],
            "",
            report["position_semantics"],
            "",
            "Historical availability and action-effective UTC are unverified.",
            "",
            "| Candidate | Model horizon-end mean rank | Worst horizon-end rank |",
            "|---|---:|---:|",
        ]
        lines.extend(
            f"| {r['label']} | {r['expected_finish_position']} | {r['worst_finish_position']} |"
            for r in report["top3"]
        )
        lines += [
            "",
            f"Stay-out baseline: {report['stay_out']['status']}",
            "",
            "All field overrides, frozen inputs, matched-scenario teammate costs, simulated "
            "traffic proxies and bounded sensitivities are in exploration.json.",
            "",
            *report["limitations"],
            "",
        ]
        (output / "exploration.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"Exploratory {report['status']}: {output.resolve()}")
        return 0 if report["top3"] else 2
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
