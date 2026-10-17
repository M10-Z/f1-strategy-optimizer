# Roadmap

[中文说明](roadmap.zh-CN.md)

## Product objective

Plan for finishing position against opponents with heterogeneous car performance and visible
responses. Single-car minimum time is a component baseline, not the final product objective.
No implementation can claim to include every race factor or guarantee the best real result.

## Implemented research foundations

- Explicit tyre/config APIs, corrected deterministic DP and independent exhaustive oracle.
- Grouped fits, chronological holdout with training-only baseline/coverage, JSON/CSV provenance.
- Bilingual terminal research wizard, synthetic demo, scenarios, packaging and offline tests.
- FastF1 message loading and known deleted-lap flags; explicit cleaning exclusion reasons.
- Multi-car visible snapshots, one-stop candidate planning and weighted finish-position risk.
- Heterogeneous base pace, tyre aging, lap-resolution traffic/limited passing, fixed plans,
  responsive undercut/overcut policies, hypothetical SC/VSC and wet-penalty events.
- Information boundaries: simultaneous actions hidden, future events simulator-only,
  past-stop timestamps and scenario availability checked; no historical replay adapter yet.

## Next steps and evidence gates

1. **Real-data access and validation.** Timing endpoints currently return proxy 403. Use trusted
   cached/normalized data or approved access; build decision snapshots from prior observations.
   Validate gap/position transitions, overtakes, pit losses and opponent response windows on
   held-out races. Report model coverage, position calibration, downside and failure cases;
   historical replay is not causal proof of hypothetical strategy gains.
2. **Feasible adaptive planning.** Add tyre inventory, used-set ages, legal compound constraints,
   multiple stops and replanning with persistent observable history. Compare policies under
   pace/opponent uncertainty declared before the held-out decision. Keep exact single-car
   optimality claims separate from finite multi-car candidate search.
3. **Better traffic and race environment.** Calibrate passing/DRS, lapped traffic, fuel and pace
   evolution, SC deployment/restarts, wet/intermediate pace and weather response from evidence.
   Current heuristic parameters and example weights must not be promoted to fitted probabilities.
4. **Team operations and disruptions.** Add team identifiers, shared pit-box queues/double
   stacking, teammate objectives and explicit cooperation constraints. Add penalties, failures,
   retirements and red-flag restarts as observable event/state transitions. Estimate hazards and
   distributions only when suitable historical exposure/labels exist; otherwise use declared
   stress scenarios and show sensitivity rather than invented likelihoods.
5. **Decision workflow.** Extend the terminal/UI with inspectable snapshots, assumption editing,
   response traces and risk preferences after core validation. Live advice/deployment is not
   part of the current scope.

The [competition guide](competition.md) states current approximations. The
[real-validation attempt](real-validation-2026-10-17.md) records the unresolved access blocker.
