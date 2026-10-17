"""Two-car finite plan search using the existing simultaneous race simulator."""

from dataclasses import asdict
from time import perf_counter

from .competition import FixedPolicy, PlanningObjective, _stops, plan_positions
from .config import positive_int


def plan_joint_positions(
    model,
    initial,
    physics,
    ego,
    teammate,
    opponents,
    actions_by_driver,
    scenarios,
    risk_top_k=3,
    observed_pits=(),
    rules=None,
    objective=None,
    max_joint_candidates=500,
    max_rollouts=2000,
):
    """Choose both schedules; default scoring protects ego's mean/worst position.

    Input order determines a documented ego-major prefix when the joint budget is
    smaller than the Cartesian grid. No quality bound is claimed for omitted pairs.
    All evaluated pairs share scenarios, physics, finite resources and opponent APIs.
    """
    started = perf_counter()
    positive_int(max_joint_candidates, "max_joint_candidates")
    positive_int(max_rollouts, "max_rollouts")
    drivers = (ego, teammate)
    team = initial.car(ego).team
    if ego == teammate or not team or initial.car(teammate).team != team:
        raise ValueError("Joint planning requires two distinct cars on the same named team")
    if set(actions_by_driver) != set(drivers):
        raise ValueError("Supply candidate plans for exactly the two controlled drivers")
    if set(opponents) != set(initial.order) - set(drivers):
        raise ValueError("Supply opponent policies only for uncontrolled drivers")
    objective = objective or PlanningObjective()
    if objective.mode == "team_rank_sum" and objective.team != team:
        raise ValueError("Cooperative objective must name the controlled cars' team")
    for driver in drivers:
        actions = actions_by_driver[driver]
        if not actions or len(actions) > 500 or len({a.label for a in actions}) != len(actions):
            raise ValueError("Each driver needs 1..500 unique candidate plans")
        for action in actions:
            stops = _stops(action)
            if len(stops) > 2 or any(
                not initial.completed_laps <= s.after_lap < initial.total_laps
                or s.compound not in model.compounds
                for s in stops
            ):
                raise ValueError("Each candidate needs at most two valid future stops")
    if not scenarios or max_rollouts < len(scenarios):
        raise ValueError("Budget must cover at least one pair across all supplied scenarios")
    left, right = (actions_by_driver[d] for d in drivers)
    total = len(left) * len(right)
    cap = min(total, max_joint_candidates, max_rollouts // len(scenarios))
    ranking, rejected, attempted = [], [], 0
    template = None
    for index in range(cap):
        i, j = divmod(index, len(right))
        pair = {ego: left[i], teammate: right[j]}
        # Both schedules are installed before simulate collects simultaneous decisions.
        report = plan_positions(
            model,
            initial,
            physics,
            ego,
            {**opponents, teammate: FixedPolicy(_stops(right[j]))},
            (left[i],),
            scenarios,
            risk_top_k,
            observed_pits,
            rules,
            objective,
            max_rollouts=len(scenarios),
        )
        template = report
        attempted += report["search"]["rollouts_executed"]
        label = " | ".join(f"{d}={pair[d].label}" for d in drivers)
        stops = {d: [asdict(s) for s in _stops(pair[d])] for d in drivers}
        if not report["ranking"]:
            rejected.append(
                {
                    "label": label,
                    "pair_indices": [i, j],
                    "joint_stops": stops,
                    "first_failure": report["rejected_candidates"][0]["first_failure"],
                }
            )
            continue
        row = report["ranking"][0]
        row.update(label=label, pair_indices=[i, j], joint_stops=stops, action=stops)
        row["per_driver"] = {}
        for driver in drivers:
            distribution = {}
            for outcome in row["outcomes"]:
                rank = outcome["finish_order"].index(driver) + 1
                distribution[rank] = distribution.get(rank, 0) + outcome["weight"]
            row["per_driver"][driver] = {
                "expected_finish_position": sum(p * w for p, w in distribution.items()),
                "worst_finish_position": max(distribution),
                "position_distribution": {str(p): w for p, w in sorted(distribution.items())},
                "expected_elapsed_seconds": sum(
                    o["weight"] * o["driver_elapsed_seconds"][driver] for o in row["outcomes"]
                ),
                "expected_queue_seconds": sum(
                    o["weight"]
                    * sum(t["pit_queue_wait_seconds"].get(driver, 0) for t in o["trace"])
                    for o in row["outcomes"]
                ),
            }
        ranking.append(row)
    ranking.sort(
        key=lambda r: (
            r["expected_objective"],
            r["worst_objective"],
            r["expected_finish_position"],
            sum(len(stops) for stops in r["joint_stops"].values()),
            r["label"],
        )
    )
    reference = next((r for r in ranking if r["pair_indices"] == [0, 0]), None)
    best_by_driver = (
        {
            d: min(
                ranking,
                key=lambda r: (
                    r["per_driver"][d]["expected_finish_position"],
                    r["per_driver"][d]["worst_finish_position"],
                    r["label"],
                ),
            )
            for d in drivers
        }
        if ranking
        else {}
    )
    for row in ranking:
        for driver, metrics in row["per_driver"].items():
            metrics["rank_cost_vs_individual_best_evaluated"] = (
                metrics["expected_finish_position"]
                - best_by_driver[driver]["per_driver"][driver]["expected_finish_position"]
            )
            metrics["rank_delta_vs_reference"] = (
                metrics["expected_finish_position"]
                - reference["per_driver"][driver]["expected_finish_position"]
                if reference
                else None
            )
    # Prefix cuts are precisely represented as half-open teammate index ranges.
    omitted = [
        {"ego_index": i, "teammate_index_range": [max(0, cap - i * len(right)), len(right)]}
        for i in range(len(left))
        if max(0, cap - i * len(right)) < len(right)
    ]
    template.update(
        schema_version=3,
        status="feasible" if ranking else "no_feasible_candidate",
        controlled_drivers=list(drivers),
        ranking=ranking,
        rejected_candidates=rejected,
        recommended_action=ranking[0]["joint_stops"] if ranking else None,
        recommended_stops=ranking[0]["stops"] if ranking else None,
        recommended_joint_stops=ranking[0]["joint_stops"] if ranking else None,
        recommended_per_driver=ranking[0]["per_driver"] if ranking else None,
        individual_best_evaluated={d: r["label"] for d, r in best_by_driver.items()},
        comparison_reference={
            "pair_indices": [0, 0],
            "feasible": reference is not None,
            "meaning": "First declared plan for each driver; negative rank delta is improvement",
        },
        search={
            "candidate_count": cap,
            "scenario_count": len(scenarios),
            "full_pair_count": total,
            "omitted_pair_count": total - cap,
            "max_joint_candidates": max_joint_candidates,
            "rollout_budget": max_rollouts,
            "rollouts_executed": attempted,
            "feasible_candidates": len(ranking),
            "elapsed_seconds": perf_counter() - started,
            "selection": "Input-order ego-major prefix; no quality bound for omitted pairs",
            "candidate_labels": {d: [a.label for a in actions_by_driver[d]] for d in drivers},
            "omitted_half_open_ranges": omitted,
            "scope": "Only supplied compound/lap grids with at most two future stops per car",
        },
    )
    template["limits"][-1] = (
        "Two-car fixed-plan search, not an optimal adaptive policy; no team orders or penalties"
    )
    return template
