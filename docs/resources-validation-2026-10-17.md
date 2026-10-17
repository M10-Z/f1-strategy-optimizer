# Resource-aware planning validation — 2026-10-17

Scope: implementation checks with original synthetic fixtures. No observed lap data, fitted
event likelihoods, real finishing-position accuracy or measured strategy gains were produced.

## Changes verified

- Optional immutable fresh-set inventory and persistent used compounds/stop counts.
- Explicit season/event/version/source rule subset, all-car feasibility, no silent relaxation
  or removal of an infeasible scenario from weighted evaluation.
- Bounded zero/one/two-stop search and rolling one-boundary actions, with observable history
  and simulator-owned realizations. Counters and partial statuses expose exhausted budgets.
- Same-team pit-box waiting and ego-plan optimization for a team rank-sum objective.
- Legacy one-stop API and original synthetic example retained.

## Executed checks

Environment: Linux, Python 3.12.14, existing development virtual environment.

| Check | Result |
|---|---|
| Targeted competition/resource tests | 41 passed |
| `python -m pytest -q -W error::FutureWarning` | 151 passed in 5.80 s; 31 non-FutureWarning warnings |
| `python -m ruff check .` | Passed |
| README's Ruff format check across package, tests and compatibility scripts | 29 files formatted |
| `git diff --check` | Passed |
| `python -m build` | sdist and wheel built successfully |
| Local wheel installed with `--no-deps --no-index` in a temporary target | Passed outside checkout under isolated Python import |

The warnings concern existing NumPy timedelta deprecations in data fixtures/driver analysis;
they do not constitute calibrated model evidence. No network is required by the tests.
An optional no-isolation rebuild failed because this virtual environment lacks setuptools;
the supported isolated build supplies that backend. The final isolated rebuild includes this
record in the source archive.

The installed-wheel smoke asserts the module loads from the temporary installed target,
67 candidates, two-stop candidates present and 8 rolling decisions ending at the finish.
Generated build/report artifacts remain ignored; no external deployment or push occurred.

## Measured synthetic outputs

Command: `python -m f1_strategy_optimizer.race_planner --scenario
examples/competition-resources.json --output-dir output/resources-iteration` (one command).
The directory contains exact input/hash/version manifest, ranked JSON and Markdown.

- Initial grid: 67 candidates × 4 user-weighted cases; 211 attempted rollouts after early
  infeasibility exits; 48 feasible, 19 rejected. Time: 0.069997 s.
- Initial recommendation: after lap 47, HARD. Weighted ego rank: 2.5; team rank sum: 6.5.
- Rolling realization: 8 decisions, candidate grids 37/37/37/37/16/16/4/4, 572 attempted
  rollouts; finished lap 53. Time: 0.145875 s. These timings are one run, not guarantees.
- Two-stop necessity fixture: both available spare sets are consumed and two stops selected
  under an explicit synthetic minimum-stop/age constraint.
- Opponent-counter fixture: immediate HARD stop takes 409.9 s but finishes P2; waiting one
  boundary takes 412.45 s and finishes P1. The position objective selects the latter.
- Cooperation fixture: optimizing ego alone produces E/R/M; optimizing Team T's rank sum
  avoids the double stack and produces E/M/R under the supplied policies.
- Paired-realization regression: hidden SC changes do not change actions until observed.

## Remaining limits and handoff

Fresh sets only; no used-set reuse. Rule checking is a declared subset, not full FIA compliance.
Queues approximate same-boundary arrivals; no cross-lap box occupancy. Team scoring chooses
ego actions, not a joint teammate strategy. Rolling search is bounded and may miss plans outside
its grid. Scenario weights remain assumptions, with no empirical calibration.

The [resource guide](resources-and-replanning.md) records the checked FIA source and unsupported
exceptions. The [real-data record](real-validation-2026-10-17.md) lists exact blocked timing
hosts and the trusted local-data alternative. No denied timing source was retried this iteration.
Next priorities are permitted data access and observation-only replay, identified used sets,
source-checked event rules and joint teammate planning.
