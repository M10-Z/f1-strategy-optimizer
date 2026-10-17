# Replay import and validation record — 2026-10-17

## Source access recheck

Following explicit authorization to check whether access changed, one normal `requests.get`
was made to each configured source at approximately **12:05:47 UTC**. No bypass, alternate
credentials or proxy changes were attempted.

| Target | Result | Origin HTTP response |
|---|---|---|
| `https://livetiming.formula1.com/static/2024/Index.json` | ProxyError; CONNECT tunnel rejected with 403 | None received |
| `https://livetiming-mirror.fastf1.dev/static/2024/Index.json` | ProxyError; CONNECT tunnel rejected with 403 | None received |
| `https://api.jolpi.ca/ergast/f1/2024/1/results.json` | ProxyError; CONNECT tunnel rejected with 403 | None received |

The failure is at the environment's proxy connection layer. It is not evidence that these
origins returned an application-level 403, that the requested resources do not exist, or that
the data providers changed their terms. No real lap observations were obtained. Local request
evidence is `output/replay-source-check/checks.json` (ignored by Git). Source errors were not
converted into synthetic observations or retried by another route.

## Delivered evaluation path

`f1-replay` / `python -m f1_strategy_optimizer.replay` accepts a normalized JSON export with
provenance, split boundaries, frozen decision packets and independent later outcomes. It
requires complete same-lap snapshots and known all-car current pit actions. Missing or unsupported
observations remain explicitly unscored. It is not an automatic raw FastF1 cache aligner.

The planner never receives the outcome object. Position, same-grid minimum simulated elapsed
time and stay-out choices use the same input. Full-race modeled results remain labeled simulated;
only the immediate next lap is evaluated against the later observation. Action disagreement
prevents scoring, with no scenario removal/reweighting. Paired error differences use only the
common scored subset. These are conditional observational prediction checks, not causal gains.

## Executed checks and synthetic evidence

Linux, Python 3.12.14:

- 20 replay tests passed, including future-result invariance, a guarded outcome read proving
  planning completes first, unavailable observations/assumptions, training-cutoff leakage,
  missing fields, lapped/incomplete fields, invalid outcomes, opponent action mismatch, budgets,
  unknown stock, timezone/provenance validation and CLI partial/no-overwrite outputs.
- Full suite: **184 passed in 5.97 seconds**, with 31 existing NumPy timedelta deprecation warnings
  and FutureWarning treated as errors.
- Ruff lint/format and diff whitespace checks pass. Isolated sdist/wheel build and outside-checkout
  installed-wheel replay smoke verify packaged imports, coverage and absence of fabricated metrics.

The hand-constructed `examples/replay-synthetic.json` supplies two cases and makes no empirical
claim. Its arbitrary development/holdout dates test software partitions, not real historical fits.

| Partition | Method | Scored cases / requested | Action mismatches | Rank MAE | Gap MAE (s) |
|---|---|---:|---:|---:|---:|
| Synthetic development | Position/time/stay-out (same action) | 1 / 1 each | 0 | 0 | 0.20 |
| Synthetic holdout | Position | 1 / 1 | 0 | 0 | 0.05 |
| Synthetic holdout | Elapsed time | 0 / 1 | 1 | Unmeasured | Unmeasured |
| Synthetic holdout | Stay out | 1 / 1 | 0 | 0 | 0.05 |

The holdout fixture selects pit after lap 5 for position versus after lap 4 for minimum simulated
time. The recorded current boundary has no pit. Hence the time method has **no eligible outcome**,
and there are zero paired holdout cases; no empirical superiority is inferred from the error table.
The two cases execute five candidate rollouts. Scenario weights and pace curves remain assumptions.

## Remaining evidence gate

Provide one trusted normalized export matching the [contract](replay.md), or a complete trusted
raw cache so source fields/timing can be inspected and aligned without guessing. Cleaned lap CSV
alone is insufficient for position replay. For broader claims, obtain held-out races, inspect
coverage/action-match selection bias and transition failures, and audit training/observation
availability. No mechanism expansion, paid resource, push, merge or deployment was performed.
