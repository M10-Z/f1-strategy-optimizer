# Two-car joint planning and validation handoff

[中文](joint-planning.zh-CN.md) · [Resources](resources-and-replanning.md)

`plan_joint_positions` selects a plan for **both** named teammates. Each can make zero, one or
two future stops. Both schedules execute in the same existing simulator: separate tyre stock,
shared team pit box, simultaneous decisions and responsive uncontrolled opponents. This is
a finite snapshot search; single-ego rolling planning remains available separately. Joint
rolling is explicitly rejected by the CLI rather than silently controlling only one car.

## Objective and tradeoffs

The default remains `driver_position`, ordered by ego's weighted mean rank, worst rank, total
stops and label. It never substitutes team rank sum for the target driver's objective. To allow
a cooperative tradeoff, explicitly set `objective: {"mode": "team_rank_sum", "team": "T"}`.
This orders by team rank sum, worst sum, ego mean rank, total stops and label. Neither objective
is a championship-points model or a guarantee about an unsearched plan.

Schema 3 records both plans, per-driver mean/worst ranks, rank distributions, time and pit-box
waiting. Rank delta compares with the first declared pair, if feasible (negative is improvement).
Rank cost compares with that driver's own best feasible evaluated pair (positive is sacrifice).
Those individual best pairs can conflict with one another; they are not a jointly achievable
promise. The Markdown recommendation exposes the same costs. Original schema 1/2 calls remain
unchanged, with an additional all-driver elapsed-time field in scenario outcomes.

## Budget and search scope

Each driver supplies at most 500 unique plans. The pair budget is the minimum of Cartesian
grid size, `max_joint_candidates` (default 500), and `max_rollouts // scenario_count` (default
2000 rollouts). Selection is an **input-order, ego-major prefix**, not a quality heuristic.
Each pair is evaluated across every supplied scenario; first constraint failure rejects the
whole pair. Saved rollouts do not expand the selected prefix, so the searched set is predictable.

Reports include full/evaluated/omitted pair counts, every candidate label, exact omitted
half-open teammate-index ranges for each ego index, attempted rollouts and runtime. For example,
6 × 6 plans with two scenarios and budget 8 evaluate `(0,0)..(0,3)` only; 32 pairs are unsearched.
Reordering input plans can affect a truncated result. Empty feasible results do not establish
that the full grid is infeasible, and searched winners are never called global optima.

## Run the synthetic conflict example

```sh
f1-race-plan --scenario examples/competition-joint.json --output-dir output/joint-demo
```

The `joint` object names the teammate, its independent candidate grid and pair cap. Remove
that teammate from `opponents`; only uncontrolled cars belong there. Existing `candidates`
configure the ego and shared rollout cap. The example intentionally opts into team scoring.
Removing `objective` selects individual scoring without changing physics or candidates.

| Objective | Ego E | Teammate M | Rank sum | Ego cost vs its best evaluated pair |
|---|---:|---:|---:|---:|
| Default individual | 2 | 4 | 6 | 0 |
| Explicit cooperation | 3 | 1 | 4 | 1 |

This four-car, five-lap example evaluates all 36 pairs under one declared dry case. It is a
synthetic regression, not evidence that sacrificing a real driver improves a real team's result.
Separate regressions demonstrate avoiding a 2.8-second double-stack wait, covering an already
observed rival stop with one car while extending the other, independent stock, both cars making
two stops, future-information rejection, and exact budget omissions.

## Current capability boundary and next gate

Implemented: single-car tyre fitting/DP and chronological backtests; strict cleaned-lap imports;
multi-car pace/traffic/limited passing; reactive opponents; hypothetical SC/VSC/wet effects;
optional fresh-stock/rule subsets; bounded two-stop plans; single-ego rolling replanning; shared
team queues; now two-car joint snapshot planning with explicit individual/cooperative scoring.

The [normalized snapshot replay adapter](replay.md) now checks next-lap outcomes separately.
Still absent: calibrated real position accuracy, automatic raw-cache alignment, used-set reuse,
complete event regulations, sub-lap/pit-lane dynamics, lapped traffic, penalties/retirements/red
flags and joint adaptive control. Scenario weights are user assumptions. No new mechanism is
needed before the next evidence gate: obtain trusted data, then validate the existing model.

The [cache/CSV handoff](real-data-import.md) specifies the minimum inputs. A cleaned lap CSV can
validate tyre pace only; position validation additionally needs timestamped field gaps/order,
pits, tyre state, visible conditions and decision-time provenance, with held-out outcomes kept
separate. The real-data access denial remains recorded in [the attempt log](real-validation-2026-10-17.md).
