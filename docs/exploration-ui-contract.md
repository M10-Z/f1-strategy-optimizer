# Forecast and exploration interface v1

[中文](exploration-ui-contract.zh-CN.md)

This contract is for a later local UI. No web app, service, deployment or outcome download is
included. Three independent operations keep archived evidence, assumptions and revealed
outcomes visible to the user.

| Operation | Python API | JSON/output contract |
|---|---|---|
| Reconstruct and forecast | `event_replay.freeze_decision(archive, cutoff, policy=None)` | Frozen decision; `state.cars`, field provenance/freshness, `observation_forecasts[*].default_prediction`, `decision_sha256` |
| Explore assumptions | `strategy_exploration.propose_exploration(frozen, assumptions)` | Schema 1; top3, separate stay_out, field_overrides, model_scope, action_boundary, inventory_feasibility, initial_threats, sensitivity, input_freezes, budget, rejection reasons |
| Explicitly reveal | `event_replay.evaluate_frozen(frozen, archive)` | Per-driver observation errors/exclusions; strict strategy score remains unavailable |
| Batch evaluation/export | `event_replay.run_archive(archive, cutoffs, output_dir, policy=None)` | decisions.json is written before outcome scoring; evaluation.json/md contain outcomes and posthoc diagnostics |

`event_sources.load_archive(openf1_dir, jolpica_dir)` is an offline integrity-checked Bahrain
adapter. Broader event adapters are future work. `EventTimePolicy` is a dataclass; unknown
methods and invalid numeric settings raise `ValueError`. Defaults are `lap_method=prefix_median`
and `gap_method=persistence`, chosen from prior Bahrain development results. `context_median`
uses the current visible stint only if at least three eligible samples exist, otherwise the
prefix median; it remains an experimental comparator. Linear/last-lap comparators are retained.
All methods share targets and coverage. Neither median method estimates causal tyre effects.

## UI flow and labels

1. Select UTC and driver from `decisions.json`; display inferred/unknown/stale fields and source
   times without silently filling them. Do not load `evaluation.json` before explicit reveal.
2. Show default next-full-lap forecast and fixed-horizon interval-report forecast. A gap report
   is asynchronous, not a synchronized physical distance. Unavailable forecasts show the reason.
3. For strategy exploration, require an assumptions document shaped like
   [the example](../examples/exploration-assumptions.json). Display every `field_overrides` entry
   with original provenance and assumed value. The example models four of twenty drivers over
   laps 8–14 using illustrative hand-supplied physics; it is not calibrated to the actual future.
4. Show top3 and stay_out separately. Retain an infeasible stay-out with its rejection reason.
   `expected_finish_position` means **model horizon-end rank**, within `model_scope` only.
   Scenario-weighted shares are not calibrated probabilities. Unknown unlimited inventory
   cannot be labelled real stock feasibility. Initial threats use assumed gaps; traffic is a
   first-post-stop-lap proxy, not a precise pit-exit prediction.
5. Show same-scenario teammate deltas versus feasible stay-out; null means no valid baseline.
   Show sensitivity winner reversals and the baseline plan's position/rank in each variant.
   No reversals under the limited changes does not prove robustness.
6. Reveal observations only on a separate action. Do not label factual observation errors as
   strategy validation. Export the original frozen decision, assumptions, exploration report
   and resolved-inputs together; preserve their hashes and interpretation labels.

`propose_exploration` never accepts an archive or outcomes and does not mutate inputs. All
resolved base/variant inputs are hashed in memory before simulation. The CLI writes
`exploration.json`, `resolved-inputs.json` and `exploration.md` after simulation; this is not a
claim of durable pre-simulation storage. Historical availability of user assumptions is
unknown. The frozen cutoff is the hypothetical information boundary, not an assertion that
an assumption document was authored then. Exact real pit-action timing remains unverified.

The bounded interface allows 1–30 modeled laps, at most 30 cars, 8 scenarios, 500 candidates,
2 future stops and 5 one-parameter sensitivities. All variants count toward the total budget
(maximum 10,000 rollouts) before any simulation. Finite stock or explicitly acknowledged
unknown unlimited stock is required. Partial fields require an explicit subset acknowledgement.
For Python callers, validation failures raise `ValueError` (malformed nested types may also
raise `TypeError`/`KeyError`); the CLI prints an error and exits 2. A valid no-feasible-plan report
also exits 2 and retains its diagnostics. Existing output directories are never overwritten.

## Offline commands

```sh
python -m f1_strategy_optimizer.event_replay \
  --openf1-dir /workspace/real-data/openf1-2023-bahrain \
  --jolpica-dir /workspace/real-data/jolpica-2023-bahrain \
  --cutoffs examples/bahrain-expanded-development-cutoffs.json \
  --policy examples/event-policy-conservative.json \
  --output-dir output/my-development-run

python -m f1_strategy_optimizer.strategy_exploration \
  --decision-file output/my-development-run/decisions.json \
  --cutoff 2023-03-05T15:18:00Z \
  --assumptions examples/exploration-assumptions.json \
  --output-dir output/my-exploration
```

Installed entry point: `f1-strategy-explore`. The whole-race holdout reservation is
[locked separately](../examples/whole-race-holdout-lock.json). The expanded fixed five-minute
Bahrain cutoffs are development data, including overlaps with earlier development; they are
not independent test evidence. Posthoc pit/control error groups never enter model features
or change scoring denominators. No holdout outcomes have been acquired for this iteration.
