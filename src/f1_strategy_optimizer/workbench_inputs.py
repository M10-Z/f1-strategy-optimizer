"""Visible-prefix initialization of explicitly hypothetical multi-car inputs.

Only the frozen record is accepted; no archive, evaluation or future pit actions.
Unknown inputs remain null. Normalizing report gaps is an acknowledged asynchronous
projection; prefix pace is backed out using the user-assumed tyre curve, not a
causally identified vehicle model.
"""

from copy import deepcopy

from .event_replay import verify_frozen


def prefix_assumptions(frozen, template, ego, field="nearby", drivers=None, quality=None):
    verify_frozen(frozen)
    from .prefix_quality import assess_prefix

    quality = quality or assess_prefix(frozen)
    cars = {c["id"]: c for c in frozen["state"]["cars"]}
    if ego not in cars or field not in {"nearby", "all", "custom"}:
        raise ValueError("选择有效车手及 nearby / all / custom 车阵")
    if field == "custom":
        ids = list(dict.fromkeys(drivers or []))
        if ego not in ids or set(ids) - set(cars):
            raise ValueError("自选车阵须包含当前车手，且全部来自冻结记录")
    elif field == "all":
        ids = list(cars)
    else:
        gap = cars[ego]["gap_seconds"]["value"]
        nearby = (
            sorted(
                (c for c in cars.values() if c["gap_seconds"]["value"] is not None),
                key=lambda c: (abs(c["gap_seconds"]["value"] - gap), c["id"]),
            )
            if gap is not None
            else []
        )
        ids = list(
            dict.fromkeys(
                [ego]
                + [c["id"] for c in nearby[:5]]
                + [c["id"] for c in cars.values() if c["team"] == cars[ego]["team"]]
            )
        )
    result = deepcopy(template)
    planning = result["planning"]
    boundary = cars[ego]["completed_laps"]["value"]
    # Null boundary is intentionally not converted to a plausible race lap.
    planning["state"].update(
        season=frozen["state"]["session"]["year"],
        event=f"session-{frozen['state']['session']['session_key']}-prefix-research",
        completed_laps=boundary,
        total_laps=boundary + 6 if boundary is not None else None,
    )
    planning["ego"] = ego
    gaps = [cars[d]["gap_seconds"]["value"] for d in ids]
    offset = min(gaps) if gaps and all(g is not None for g in gaps) else 0
    modeled = []
    for driver in ids:
        c = cars[driver]
        compound = c["compound"]["value"]
        age = c["estimated_completed_tyre_age"]["value"]
        pace = quality["drivers"][driver]["candidate"]["value_seconds"]
        curve = planning["tyres"].get(compound)
        # The engine adds the next-lap tyre contribution. Subtract it here to
        # avoid counting observed tyre degradation twice when seeding base pace.
        base = (
            pace
            - curve["base_time"]
            - curve["degradation"] * age
            + planning["physics"]["reference_lap_time"]
            if pace is not None and curve is not None and age is not None
            else None
        )
        gap = c["gap_seconds"]["value"]
        modeled.append(
            dict(
                driver=driver,
                team=c["team"],
                base_lap_time=base,
                gap_seconds=gap - offset if gap is not None else None,
                compound=compound,
                tyre_age=age,
                tyre_inventory=None,
                used_compounds=[compound] if compound else [],
                pit_stops=0,
            )
        )
    planning["state"]["cars"] = modeled
    planning["opponents"] = {d: {"kind": "fixed", "stops": []} for d in ids if d != ego}
    planning["risk_top_k"] = min(3, len(ids))
    planning["candidates"]["pit_laps"] = (
        [boundary, boundary + 2, boundary + 4] if boundary is not None else []
    )
    for scenario in planning["scenarios"]:
        old = scenario["available_at_lap"]
        scenario["available_at_lap"] = boundary
        for event in scenario["events"]:
            event["lap"] = boundary + event["lap"] - old if boundary is not None else None
    explanation = (
        f"Visible-prefix initialization at {frozen['cutoff']}; {field} selection. "
        f"Report gaps subtract {offset} s and are projected to the ego's completed-lap "
        "boundary, not synchronized measurements. Tyre age/compound retain prefix values. "
        "Base pace = fresh visible-segment median minus assumed next-lap tyre contribution; "
        "not identified vehicle pace. Stale/transition/unstable evidence yields null pace. "
        "Missing values remain null. All selected cars are "
        "ASSUMED ACTIVE; activity is unknown. Historical pit count=0 and used_compounds="
        "current compound are explicit counter assumptions, not observed history. "
        "Conditions, curves, physics, future opponent stay-out and scenarios remain "
        "manual hypotheses. Inventory stays unknown/unlimited; no stock feasibility claim."
    )
    planning["source"] = explanation
    result["action_boundary"].update(after_lap=boundary, effective_at=None, rationale=explanation)
    result["model_subset"] = dict(drivers=ids, acknowledged=True, rationale=explanation)
    for group in ("state_alignment", "pace_and_physics", "inventory", "opponents"):
        result["field_assumptions"][group] = dict(
            source="Frozen prefix + explicit model assumptions", rationale=explanation
        )
    result["selection_preference"] = {"mode": "conservative"}
    return result
