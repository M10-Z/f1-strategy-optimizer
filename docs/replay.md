# Timestamped next-lap replay

[中文](replay.zh-CN.md) · [Cache/CSV handoff](real-data-import.md)

`f1-replay` imports a normalized cache export containing frozen decision packets and separate
later observations. It checks the existing model against the immediately following lap. It does
not claim race-long strategy validation, probability calibration or causal counterfactual gains.
The first supported scope is individual-driver snapshot planning and a complete same-lap field.

```sh
python -m f1_strategy_optimizer.replay --input examples/replay-synthetic.json \
  --output-dir output/replay-demo
# After installation: f1-replay --input /path/to/trusted-export.json --output-dir output/replay-real
```

The bundled two-case fixture is **entirely synthetic**, with manually constructed later results.
Its nominal development/holdout dates test splitting logic; no real model was trained on them.

## Export contract (schema 1)

Use the example as the exact JSON shape. Do not rename synthetic data as observed.

| Object | Required evidence |
|---|---|
| `provenance` | `kind` synthetic/observed, source, URI, acquired_at, processing description |
| `splits` | Timezone-aware training_end_at strictly before holdout_start_at |
| Each case | Unique case_id, development/holdout partition, decision, independent outcome |
| `decision` | at, observed_at, available_at, assumptions_available_at; explicit field_complete; driver_completed_laps; model_kind; model_data_end_at; planning |
| `decision.planning` | Existing race-planner input, with named season/event, observed conditions, full car gaps/tyres/ages/team, explicit pace/model assumptions and predeclared candidate/scenario grids |
| `outcome` | observed_at, available_at, next completed_laps, full-field cars with driver/lap/position/gap/compound/age, track_status/weather, known pit_actions and their boundary |

All timestamps require an offset or Z. Decision observations must be observed and available by
the decision clock. The entire snapshot must be a coherent common decision boundary: do not
combine each driver's independently completed lap into a supposedly simultaneous observation.
The exporter must establish alignment and availability from the source; declarations are checked
for consistency but cannot independently prove provenance. `acquired_at` is download time, not
the time information was available to a historical decision.

Every initial driver must have the same completed lap, and the next outcome must contain exactly
those drivers at the immediately following lap. Missing drivers, retirements, lapped cars, unknown
pit actions or unsupported conditions are unscored with explicit reasons. No interpolation or
default weather fills missing observations. Unknown tyre inventory remains explicitly unlimited
in the model, not a resource-feasibility claim. Active stop/compound-history rules require known
prior counts/used compounds. Initial pace estimates remain assumptions, not identified vehicle
performance. Outcomes retain actual tyres/ages and must agree with recorded compound changes.

`model_kind=assumed` requires a null training cutoff. `model_kind=fitted` requires a cutoff no
later than the decision and, for holdout cases, no later than the declared training end. Holdout
decisions must occur after holdout start. Fitted model source and cleaning details belong in the
provenance; exporting coefficients does not make them independently verified.

## Information boundary and comparison

The adapter validates and copies only `decision.planning`, completes the planner call, and hashes
that decision input **before reading outcome**. No future result fills missing state, sets scenario
weights, chooses opponents or selects a plan. Scenarios retain the existing hypothetical-only
contract and must have been available at the decision. The source exporter must not backdate a
known future SC/weather path as a hypothesis. Changing or removing outcomes cannot change plans.

Using the same feasible candidate grid, state, opponents and scenarios, select:

1. The existing position-ranked recommendation.
2. Minimum expected simulated elapsed time, using the already computed candidate metric.
3. Stay out, if feasible.

The elapsed-time baseline is a common-grid comparison using existing model outputs; it is **not**
the separate single-car DP's exact optimum, and no fresh-tyre reset is introduced for that baseline.
Finish-rank/time figures in this comparison remain simulated. Only the first trace step is compared
with the independent next-lap observation; later recommended stops are not evaluated as outcomes.

For each method, all drivers' predicted current pit actions must match the recorded boundary
actions in every supplied scenario. Otherwise mark `action_mismatch`, with null error metrics.
No scenario is discarded or reweighted to manufacture agreement. Conditional on action agreement,
compare weighted predicted next-lap positions and gaps with observed positions/gaps; weather/SC
surprises remain forecast errors, never injected into planning retrospectively. This conditional
sample can be selective and is not an off-policy estimate of a strategy's race benefit.

Aggregate per-driver absolute errors separately for development/holdout; report case counts,
driver-observation counts, action mismatches and other status counts. Only the intersection of
action-matched cases contributes to the paired position-vs-time error difference. Different method
coverage must not be compared as if the samples matched. Empty coverage produces null, not zero.
Observations from one race are correlated; these summaries supply no confidence intervals.

## Bounds and outputs

At most 100 cases per batch, with existing per-case search caps and `max_total_rollouts` (default
10000). Input order determines which cases run when the batch budget is tight. Cases exceeding
the remaining conservative candidate × scenario budget are explicitly unscored. There is no
automatic retry, future-data substitution or relaxation of rules.

Output: `replay.json`, readable `replay.md`, and `manifest.json` containing the exact input,
SHA-256 and package versions. Existing output is not overwritten. CLI exit 2 still writes partial
evidence for rejected/budget-exhausted/no-feasible cases, or if no position case can be scored.
For clean input, baseline action mismatches are reported coverage limitations, not parser failures.

## What is still needed

This is a normalized export adapter, **not an automatic raw FastF1 cache decoder/alignment tool**.
Trusted exports can be evaluated directly. If only a raw cache is supplied, first inspect its
actual timing/messages and implement a narrow source-specific exporter with auditable common-clock
alignment; do not guess position, gap, pit boundaries or missing availability times. Cleaned lap
CSV alone omits the pit/non-green context needed here.

No trusted race export has been supplied. On 2026-10-17, one normal request to each previously
configured source again failed at proxy HTTPS CONNECT with 403; no origin HTTP response was
received. See the [run record](replay-validation-2026-10-17.md). The next step is one trusted
complete same-lap segment plus its later observation, followed by held-out-race coverage and
failure analysis. Do not add further race mechanisms before testing the existing ones on evidence.
