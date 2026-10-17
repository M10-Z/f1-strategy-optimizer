# Position-oriented multi-car planning

[中文](competition.zh-CN.md)

The goal is to choose strategies for better finishing positions against cars with different
pace and opponents that react. The implementation ranks a finite candidate set under explicit
hypotheses; it is not a game-theoretic optimum, calibrated forecast or race-ready controller.

## Architecture and reuse

| Layer | Implementation | Responsibility |
|---|---|---|
| Existing tyre interface | `solver.LapTimeModel` | Compound/age/temperature pace; existing fitted `TyreModel` can be passed directly |
| Visible snapshot | `competition.RaceState`, `CarState`, `Observation` | Completed/total laps, field order/gaps, vehicle base pace, compound/age, visible conditions and past pits |
| Opponent decision | `OpponentPolicy.choose(observation, driver)` | Fixed schedules or observed-undercut/overcut responses; no future scenario object |
| Event assumptions | `Scenario`, `RaceEvent` | Explicit weighted hypothetical SC/VSC/weather/temperature paths |
| Competition physics | `Physics`, `simulate` | Simultaneous pit decisions, paid time losses, tyre aging, constrained passing and neutralization |
| Position objective | `candidate_actions`, `candidate_plans`, `plan_positions` | Legacy one-stop API plus bounded two-stop plans; position or team rank-sum objective |
| Resources and control | `CompetitionRules`, `rolling_plan` | Explicit stock/rule feasibility, same-team queues, one observed lap at a time |
| Offline entry point | `race_planner`, `f1-race-plan` | JSON input, recorded assumptions/hash/versions, ranked JSON and readable Markdown |

The deterministic solver remains a baseline for isolated model-relative time optimization.
It does not solve an interactive multi-car race. Its `LapTimeModel` interface and existing
fitting/validation/data provenance are reused rather than replacing their semantics.
The CLI's generic linear tyre curves can name intermediates/wets but are supplied scenario
assumptions; there is no fitted wet-tyre model. Vehicle base time replaces the tyre model's
reference baseline: `base_lap_time + tyre_prediction - reference_lap_time`.
The CLI linear model ignores temperature; the Python model interface can respond to it.

## Timing and information boundary

At a boundary after lap L:

1. Every driver sees the same immutable snapshot and pit records strictly before L.
2. All pit choices are collected before any is exposed to another driver.
3. Pit losses use the **currently visible** track status. Pitted tyres reset to age zero.
4. A hypothetical event for lap L+1 is revealed, then lap L+1 is driven at age + 1.
5. Cars are classified, gaps updated, and the completed pits become visible at the next boundary.

`cover_undercut` can bring a planned stop forward after observing a rival's stop within the
response gap/window; `overcut` can extend the planned stop. Both reconsider visible gaps.
They cannot react simultaneously to an unobserved action. `observed_pits` allows replanning
from known prior stops; records at/after the decision boundary are rejected.

An event is a full-lap approximation, not a sub-lap deployment. The simulator owns the future
event list; policies receive no forecast/event list. Scenarios must be declared `hypothetical`
with `available_at_lap <= decision_lap`. Historical-future scenario types are rejected.
These checks enforce API information boundaries, not the truth of user-supplied provenance.
A real replay adapter must derive beliefs only from earlier information; relabeling known
future events as hypotheses would still be hindsight leakage. That adapter is not implemented.

## Traffic, events and uncertainty

- Vehicles are all active and on the same race lap. Initial positions derive from gaps; ties
  preserve input order. Cars can change position through paid pit losses before driving.
- On-track passing requires enough modeled pace advantage and space after the passing cost.
  Each car may pass at most one car per lap. Otherwise it is held behind the preceding car.
  This is an explicit heuristic, not a DRS/aerodynamics or continuous-distance simulation.
- SC/VSC prohibit on-track passing. SC closes gaps by a bounded amount per lap, never beyond
  green-equivalent travel; VSC has no deliberate bunching. Slower pace and reduced net pit
  losses are independently supplied factors. Same-boundary team pit-box queues use arrival gaps;
  actual pit-lane geometry is absent.
- Rain changes explicit per-compound penalties, allowing tyre-choice tradeoffs. Every modeled
  compound needs a declared wet penalty in a wet scenario; unknown wet response is not guessed.
- Weights are normalized user assumptions, not measured frequencies. Outputs include weighted
  mean finish position, full rank distribution, worst position, standard deviation and weighted
  share outside the configured top k. Ranking uses mean rank, then worst rank; exact ties prefer
  staying out, then the stable action label. It does not minimize total elapsed time.
- Each search compares zero/one/two-stop plans. The rolling controller executes only the
  current action, advances one observed lap and rebuilds the remaining plan with persistent
  stock/history. This is bounded receding-horizon search, not an optimal adaptive policy tree.
- Optional team rank-sum scoring changes the ego's plan while teammate policies remain fixed
  or reactive. [Resource and rule semantics](resources-and-replanning.md) describe feasibility,
  candidate budgets, queues and the distinction between checked subsets and full regulations.

## Reproducible synthetic example

```sh
python -m f1_strategy_optimizer.race_planner \
  --scenario examples/competition.json --output-dir output/position-plan
```

The example uses four synthetic cars, 8 remaining laps, 13 candidates and four equally weighted
stress scenarios (green/dry, SC, VSC, rain). It produces `race-plan.json`, `race-plan.md` and
`manifest.json` with the exact input and SHA-256. Existing output directories are not overwritten.
No network, real-data download or random event probabilities are involved.

Observed software behavior for this example, **not real race performance**:

| Opponent assumption | Best ranked action | Weighted finish position |
|---|---|---:|
| Reactive LEADER/FAST plus fixed TRAFFIC | Stay out | 2.25 |
| All opponents fixed at their original planned stops | Pit after 45, HARD | 1.00 |

For the same `pit-after-45-MEDIUM` action, fixed opponents yield P1 in every stress case;
responsive opponents yield P2 with weight 0.25 and P3 with weight 0.75. In the dry case,
LEADER responds after lap 46 rather than waiting until 49. This ablation demonstrates that
assuming opponents never respond can materially change simulated recommendations. It does
not establish which opponent model is realistic, nor justify the arbitrary example weights.

## Real feasibility and remaining evidence

No real finishing-position accuracy or strategy advantage has been validated. Timing sources
were denied by the environment proxy; see the [attempt record](real-validation-2026-10-17.md).
Public lap pace mixes vehicle performance, traffic, fuel, tyres, track evolution and driver
behavior. It must not be presented as an identified causal vehicle-performance parameter.

Immediate next work is trusted data access plus snapshot/replay validation and physical checks
on observed gaps, passes, pit losses and opponent responses. Fresh-set inventory, explicit
rule subsets, rolling two-stop planning and simple team queues are now implemented; used-set
reuse, joint teammate planning, failures, penalties, lapped traffic and red flags remain open.
Event distributions require evidence before calibration. No module claims to enumerate every
factor that can affect a race. The [roadmap](roadmap.md) records these priorities.
