# Event-time archive replay and factual forecast benchmark

[中文](event-replay.zh-CN.md) · [Measured development results](event-replay-validation-2026-10-17.md)

`f1-event-replay` reconstructs a common UTC information cutoff from verified historical
responses, freezes every forecast, and evaluates separate outcomes. Bahrain 2023 is a
development race. This is a non-interventional observation benchmark, not a strategy benefit
estimate. The existing `f1-replay` retains its stricter action-matched strategy contract.

```sh
python -m f1_strategy_optimizer.event_replay \
  --openf1-dir /workspace/real-data/openf1-2023-bahrain \
  --jolpica-dir /workspace/real-data/jolpica-2023-bahrain \
  --cutoffs examples/bahrain-event-cutoffs.json \
  --output-dir output/bahrain-event-development
```

Use a new output directory. No network calls occur during replay. The adapter is deliberately
restricted to session 7953 / meeting 1141 and Jolpica 2023 round 1. It checks raw response
SHA-256, byte counts, successful request receipts, endpoint filters, event identity, pagination
offsets/totals and unique keys. Raw archives and generated outputs stay outside Git.
Expected files are OpenF1 `sessions/drivers/laps/stints/weather/race_control/position/intervals.body`,
same-event `jolpica-results.body`, and their `.meta.json` receipts; Jolpica uses
`raw/laps-NNNN.json`, `raw/pitstops-NNNN.json` and matching receipts. Minute samples never
stand in for full-session responses. Identity uses race-result number plus separate given/family
names when available, not current permanent numbers. Only identity/team fields leave that join.

All cars share a UTC cutoff, not a completed-lap number. Each state field carries observed,
inferred or unknown status, event time, assumed availability, freshness and source. Default
publication delay is two seconds plus a one-second timing margin, configurable with `--policy`.
These are archival research assumptions, not verified historical online availability.
Positions and gaps remain asynchronous last-known observations; no gap sorting fabricates a
synchronized order. Unknown activity, track/surface state and tyre stock stay unknown.

A completed lap enters the prefix only after its consecutive next start is visible and
`max(start + duration, next_start) + delay + margin <= cutoff`. Terminal laps without next-start
corroboration lose training coverage. Current unfinished durations never enter the prefix.
Stint state attaches only to a visible start event; `lap_end` and future compounds are excluded.
Tyre age is explicitly inferred. Race-control messages are retained rather than misreading
pit-exit green lights as whole-track GREEN. Rainfall zero does not prove a dry surface.

The fixed target lap is the latest visible started lap plus one. A revealed target already
started at cutoff, missing, or without a positive duration is excluded without retargeting.
The prefix model uses up to eight eligible completed laps, excluding first laps and known
outlaps, with at least three samples and bounded linear slope. It is compared with the same
prefix's median and last eligible completed lap. Future pit, SC/VSC and weather effects remain
forecast errors, not retrospective exclusion filters. Each driver uses its own history; this
does not identify independent car performance or tyre degradation.

The gap target is the last newly available numeric interval report at a fixed 90-second
horizon. Input/outcome freshness is limited to 12 seconds. Null, negative and lap-string gaps
are rejected; numeric zero is valid. A 60-second prefix trend is compared with persistence.
This measures report-value error, not simultaneous physical gap accuracy. All methods share
the same scored set; reports include denominators, exclusions, MAE and paired MAE differences.
Zero coverage produces null metrics.

All cases are durably written to `decisions.json` before outcome evaluation. Frozen records
contain code hashes, configuration, seed, visible-prefix hash, fitting cutoff, coefficients,
targets, forecasts, blocked candidates and missing-field reasons. Algorithms are deterministic.
Full-archive hashes live in `evaluation.json`, outside decision features. Future changes to a
valid archive cannot change the visible-prefix decision; corrupt/missing required archive
fields fail source integrity checks before prediction. Edited frozen records fail hash checks.

Stay-out and SOFT/MEDIUM/HARD pit candidates record requested time but remain blocked, with
null effective time, prediction and recommendation. This race lacks verified pit-action
boundaries and complete causal strategy state. Unconditional observation scores cannot satisfy
the action-matching gate. Strategy metrics remain null; unexecuted candidate benefits would be
model counterfactuals, not observed benefits.

Next, build an operational historical replay interface around this kernel: driver/UTC selection,
top three feasible options including stay-out, nearby-car threats, pit-exit traffic, teammate
cost, assumption sensitivity, explicit outcome reveal and decision export. Show refusal reasons
when options cannot be supported. Before expanding strategy mechanisms, audit an event-time
slice and action timing, compare delay assumptions, and fix an entire unseen race and scoring
rules before tuning. Never randomly split adjacent laps. Commercial source rights require a
separate assessment.

## Conservative defaults and assumption explorer

The default forecast now selects prefix median and gap persistence using prior Bahrain development evidence. Context median is an experimental comparator. Factual strategy scoring stays blocked, while an independent explicit-assumption explorer can produce simulated options. See the [UI/API contract](exploration-ui-contract.md) and [whole-race reservation](../examples/whole-race-holdout-lock.json).
