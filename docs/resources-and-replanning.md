# Resources, rules and rolling planning

[中文](resources-and-replanning.zh-CN.md) · [Competition model](competition.md)

This extension retains `PitAction`, `candidate_actions` and the original CLI input. New
optional fields enable finite resources and bounded multi-stop planning; old snapshots
explicitly report `unspecified_unlimited` inventory. No empirical probabilities are fitted.

## Snapshot and rule semantics

- `CarState.tyre_inventory` counts **fresh spare sets**, excluding the mounted set. A supplied
  empty inventory or missing compound means zero. Each stop consumes one set, including a
  same-compound stop. Removed used sets are not returned; used-set identity/reuse is not modeled.
- `used_compounds` records known race history; the mounted compound is added after a driven
  lap (or immediately when its supplied age is positive). `pit_stops` is the total already
  completed in this race. Supply these separately from `observed_pits`; no count is inferred
  from a possibly incomplete history. Rolling state preserves all three.
- `CompetitionRules` carries season, event, version, source and source status. Active rules
  require a season/event matching the snapshot. Configurable constraints cover minimum distinct
  dry compounds, at least one named mandatory dry compound, allowed compounds, minimum stops
  and maximum driven tyre age. A configured wet-use exemption affects dry requirements only;
  rain alone does not trigger it. Rules are checked for **all cars**, including opponents.
- If any supplied scenario violates inventory/rules, reject the whole candidate and record
  its first failure. Never drop that scenario and renormalize weights. An empty feasible set
  produces no recommendation. No rule is silently relaxed.

Official source checked on 2026-10-17: [FIA 2026 Sporting Regulations, Section B,
Issue 09, 2026-10-01](https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_b_sporting_-_iss_09_-_2026-10-01.pdf),
B6.3.6 (page 59). It links the dry-compound obligation and mandatory race specification to
actual intermediate/wet use. B6.3.2 defines use at pit/grid departure; our completed-lap
accounting is coarser. Suspension exceptions, B6.3.7 wet-start directives and event nominations
are not implemented. No automatic season/event profile is installed. The example's two-stop
minimum is a **synthetic assumption**, not a claim about a universal FIA requirement or Monaco.
`source_checked_subset` is provenance supplied by the caller, not certification.

## Bounded plans and rolling observations

`candidate_plans(..., max_stops=2, max_candidates=500)` returns `PitPlan` objects containing
zero, one or two ordered `PitAction`s. For L candidate boundaries and C compounds, the maximum
grid is `1 + L*C + L*(L-1)/2*C*C`. Oversize grids fail before enumeration. `plan_positions`
also caps candidate × scenario rollouts (default 2000); it reports actual attempted rollouts,
feasible candidates and wall time. Early constraint failures can reduce attempted rollouts.
Legacy `PitAction` input retains schema/action shape 1; `PitPlan` uses schema 2 and `stops`.

`rolling_plan` receives a belief callback with only current `Observation(state, pit_history)`.
At every boundary it rebuilds a bounded relative pit grid, ranks plans to race end, executes
only an immediate stop, advances one lap and discards future proposed stops. The realization
path belongs to the simulator. In the CLI, beliefs are the original declared scenarios with
past events removed; weights are not updated using the realization. A changed visible condition
can change the next plan, but unobserved future events cannot. Arbitrary Python callbacks still
need honest provenance; a closure must not secretly read historical future data.

Each decision logs assumptions, visible conditions/stock, selected stops, search counts and
timing. Per-search and total rollout caps plus a decision cap bound work. Budget exhaustion,
no feasible plan or a realized constraint failure returns the last verified state and a partial
status; it does not claim a finish. CLI status is 2 for infeasible/unfinished results, with
JSON/Markdown evidence still written. The search may miss feasible plans outside its grid;
it is not a globally optimal adaptive policy search.

## Shared pit boxes and cooperative objective

Cars with the same non-null `team` share one service resource at a decision boundary. Arrival
order/gaps approximate pit-box arrivals. Waiting is `max(0, previous_box_ready - arrival)`;
`pit_service_time` sets box occupancy and is **already included** in net `pit_loss`. Only waiting
is added, without SC/VSC discount. Default service time zero preserves previous behavior.
Different teams use independent boxes. There is no pit-lane geometry, cross-lap occupancy or
stochastic service model; long repairs/retirements need separate state transitions.

Default `driver_position` scores ego rank. `team_rank_sum` minimizes the declared team's sum
of finishing ranks (then worst score, ego mean rank, fewer stops and label). It optimizes
only the ego's schedule under supplied teammate policies; it is not joint control, team orders
or championship-point optimization. Opponent choices remain simultaneous and hidden.

## Reproduce and evidence

```sh
f1-race-plan --scenario examples/competition-resources.json --output-dir output/resources-demo
```

The fully synthetic example has four cars, 8 remaining laps, finite stock, explicit research
rules and four user-weighted cases. A local Python 3.12.14 run on 2026-10-17 measured:

| Search | Candidates / cases | Attempted rollouts | Result | Seconds |
|---|---|---:|---|---:|
| Initial plan | 67 / 4 | 211 | 48 feasible, 19 rejected | 0.0700 |
| Rolling realization | 8 decisions; 37 → 4 candidates each | 572 | Finished lap 53 | 0.1459 |

Times are one local observation, not performance guarantees; JSON records each run's timing.
The initial team objective selects pit after 47 on HARD (weighted ego rank 2.5, team rank sum
6.5). The rolling policy can revise that plan. These are software outputs, **not actual race
accuracy or measured strategic gains**. The tiny regression fixture also requires and selects
two stops; two-stop capability does not imply every example should choose two future stops.

Regression cases cover finite stock, dry/wet use, historical resources, scope mismatch,
two-stop necessity, same-team waits, cooperative ranking, slower-car defense and an opponent
counter that makes a shorter own elapsed time finish worse. A paired-realization test keeps
decisions identical until a hidden event becomes observed. CLI tests check finished and partial
reports. See the [iteration record](resources-validation-2026-10-17.md) for full checks.

Two-car joint snapshot planning is now available through the separate
[joint API](joint-planning.md). Next evidence: trusted timing access and observation-only replay;
used-set identity and official event profiles remain open. [Data access remains blocked](real-validation-2026-10-17.md).
