# Joint planning validation — 2026-10-17

This iteration implements actual two-car plan control while reusing existing race physics,
per-car tyre stock, shared team queues and observable opponent policies. Default ego scoring
and explicit cooperative scoring remain distinct. No real race data were received or evaluated.

## Executed software checks

Linux, Python 3.12.14, existing development environment:

- `python -m pytest -q tests/test_joint_planner.py tests/test_race_resources.py tests/test_competition.py`:
  54 passed, including 13 new tests/cases.
- `python -m pytest -q -W error::FutureWarning`: 164 passed in 5.70 seconds, 31 existing
  NumPy timedelta deprecation warnings. No new real-data evaluation is implied.
- `python -m ruff check .`, documented format check (31 files), `git diff --check`: passed.
- Isolated sdist/wheel build and installed-wheel smoke outside the checkout verify the joint
  CLI, both scheduled drivers and explicit individual/cooperative costs. Generated data and
  caches are excluded from the source archive.

The source scenario is `examples/competition-joint.json`; local output is
`output/joint-iteration/{race-plan.json,race-plan.md,manifest.json}` (ignored by Git).
The manifest preserves exact source input, hash and versions.

## Measured synthetic behavior

The example evaluated all 36 pairs × 1 declared dry case: 36 feasible, no omitted pairs,
36 attempted rollouts. The planner recorded 0.009059 seconds in this run, not a latency guarantee.

| Configuration | Ego E | Teammate M | Sum | Explicit ego rank cost |
|---|---:|---:|---:|---:|
| Default ego objective | 2 | 4 | 6 | 0 |
| Explicit team objective | 3 | 1 | 4 | 1 |

Other regression evidence:

- Joint schedules stagger stops to avoid 2.8 seconds of queue delay and change the synthetic
  team rank sum from 4 to 3. Both planned schedules execute in one simulator.
- Given an already observed rival stop, one car pits immediately while the other extends to
  a later candidate boundary. No future opponent action is exposed.
- Responsive opponent S reacts one boundary after observing E's stop, never simultaneously.
- Independent inventories cannot borrow a teammate's spare set. Both cars can execute two
  stops; impossible minimum-stop rules return no recommendation. Infeasible scenarios are not
  discarded to improve weighted results.
- With 6 × 6 plans, 2 scenarios and rollout budget 8, exactly four pairs are selected and all
  32 omitted pairs are accounted for by disjoint half-open index ranges. No quality bound or
  global optimality is claimed for this input-order prefix.
- Future assumptions/history, duplicate control of a teammate and unsupported joint rolling
  are rejected. Existing single-ego rolling and earlier APIs still pass their regressions.
- CSV validation now normalizes driver/event whitespace before duplicate detection and rejects
  blank events; the documented schema validator can run without fitting or downloading.

## Handoff and stopping point

The [complete capability/limit guide](joint-planning.md) and [cache/CSV import instructions](real-data-import.md)
define the next step. A trusted complete cache or cleaned lap dataset can unlock component
validation; position validation additionally needs observation-time field gaps/order, tyres,
pits and conditions plus separate later outcomes. A narrow replay adapter remains to be built
after obtaining those data. No timing host was retried and no permissions were changed.

All scenario weights remain assumptions. Stop adding mechanisms until trusted observations
allow validation of the implemented models. Used tyres, full regulations and joint adaptive
control remain limitations, not implicit promises of the current implementation.
