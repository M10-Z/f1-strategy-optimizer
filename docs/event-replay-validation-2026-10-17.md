# Bahrain event-time development validation — 2026-10-17

[中文](event-replay-validation-2026-10-17.zh-CN.md) · [Run contract](event-replay.md)

The new instance successfully acquired this historical race. The earlier proxy-denial reports
remain historical evidence. No restricted timing host was retried during this implementation.
Raw archives remain local; this report records aggregate results and reproducibility receipts.

Inputs: 1055 Jolpica completed lap records, 50 pit records; OpenF1 1058 lap-start records,
70 stints, 20 drivers, 75 race-control messages, 161 weather observations, 666 position updates
and 27797 interval reports. Twenty historical identities match by race number plus names.
OpenF1 has three additional null-duration records; all 20 first laps differ between sources
by 0.266–0.407 seconds. Forecasts use OpenF1 only and exclude first laps from training.

Ten UTC cutoffs were fixed in `examples/bahrain-event-cutoffs.json` before scoring. Delay=2s,
timing margin=1s, gap horizon=90s. All 20 roster members remain in every denominator, regardless
of subsequent retirement or missing observations. This is development, not independent holdout.

| Target / model | Scored / attempted | MAE (seconds) |
|---|---:|---:|
| Full next target lap / prefix linear | 126 / 200 | 2.964945 |
| Same lap / prefix median | 126 / 200 | 1.741583 |
| Same lap / last eligible completed | 126 / 200 | 3.073246 |
| Future interval report / prefix linear | 124 / 200 | 5.024089 |
| Same report / persistence | 124 / 200 | 3.596758 |
| Action-matched strategy predictions | 0 | null |

Linear minus median lap MAE: +1.223362s; linear minus last eligible lap: -0.108301s.
Gap trend minus persistence: +1.427331s. These are paired comparisons on identical coverage.
The more elaborate extrapolation does not improve on the strongest simple baseline. No model
selection was made from these outcomes, and no causal strategy gain was measured.

Lap exclusions: 40 insufficient prefixes, 31 missing target laps, 3 targets already started.
Gap exclusions: 74 insufficient/stale numeric prefixes, 2 invalid/null target reports.
All blocked strategy candidates retain unknown action timing and null predictions.

| UTC cutoff | Lap scored | Gap scored |
|---|---:|---:|
| 14:59 | 0 | 0 |
| 15:10 | 0 | 19 |
| 15:18 | 20 | 19 |
| 15:30 | 19 | 16 |
| 15:45 | 19 | 17 |
| 16:05 | 18 | 16 |
| 16:12 | 18 | 13 |
| 16:18 | 16 | 13 |
| 16:35 | 16 | 11 |
| 16:43 | 0 | 0 |

Measured freeze/evaluation/export runtime was 1.819s (excluding archive loading and download).
Source manifest SHA-256:
`3e1187bf69bfacf7d53a5b7d792eb528bbe2fae568e4015a27612a9fe6cf88c6`.
At 15:18 UTC, changing/removing future lap values, stints, weather, race control, positions,
intervals, pit records and archive audit metadata left the entire frozen record identical:
`2199ddfe088d7afba0b7e9b08fd3c4baeb87e45b7a8c0f398fb3303b8d958283`.
This compares valid archive projections, not bypasses of source-integrity checks.

One full regression run passed 215 tests. Real import then caught Chinese display-name ordering;
the adapter now uses separate given/family names. A focused rerun passed 32 source/replay tests,
including the new regression. Ruff passed; sdist/wheel build passed after installing missing
local build dependencies. Existing NumPy timedelta deprecation warnings remain.

Artifacts are `output/bahrain-event-development/{decisions.json,evaluation.json,evaluation.md,
real-prefix-invariance.json}`. Publication delay is assumed, interval values are asynchronous,
retirement activity is unknown, and exact pit boundaries are unavailable. The next acceptance
gate is audited shared-cutoff/action evidence and a predeclared whole-race holdout, not UI claims
of race-ready strategy performance.
