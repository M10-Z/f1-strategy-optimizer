# Reserved 2024 whole-event holdout validation

The defaults **are the prefix-median and persistence baselines themselves**, not learned models with an established advantage. The original results below remain unchanged. [Subsequent British diagnostics](value-review.zh-CN.md) are post-observation development analysis.

The three reserved races were evaluated with the previously fixed prefix-median lap and persistence gap defaults. Each race contributes 20 registered drivers at all 23 scheduled-start offsets (+600 through +7200 seconds, step 300). No driver, cutoff, event or method was reselected from the errors.

**Execution qualification:** two transparent adapter corrections were necessary. Monaco and Italy had already been scored before both corrections. The British country-alias correction was committed before British outcome requests; an optional missing pit-audit duration was corrected after raw acquisition but before British prediction errors were computed. The original and identity-only rejection runs remain intact. This is not an unmodified strict three-event blind execution.

## Fixed-default results

| Event | Drivers | Lap scored/all | Median lap MAE (s) | Gap scored/all | Persistence MAE (s) |
|---|---:|---:|---:|---:|---:|
| Monaco Grand Prix | 20 | 213/460 | 1.037347 | 190/460 | 1.433716 |
| British Grand Prix | 20 | 276/460 | 5.074451 | 218/460 | 2.043459 |
| Italian Grand Prix | 20 | 259/460 | 1.790237 | 213/460 | 2.392629 |

Equal-event lap MAE: **2.634012 s**, coverage **748/1380 (54.20%)**. Equal-event gap-report MAE: **1.956601 s**, coverage **621/1380 (45.00%)**. Each race has equal metric weight; the 1380 correlated driver/cutoff slots are not 1380 independent tests.

The frozen linear comparators have equal-event MAE 2.570596 s for laps and 1.560394 s for gaps. The default lap MAE (2.634012 s) is higher than linear (2.570596 s) and last eligible completed lap (2.165170 s); default gap MAE (1.956601 s) is higher than linear (1.560394 s). Lower MAE is better. All comparators use the same scored targets; defaults remain unchanged.

Final local preparation/freezing/evaluation took 11.080 seconds. All 69 decision packets were durably written before any evaluation in the final batch. Their SHA-256 is `562508a0ddd4c203ada1a6a65ad752ca1b4291ac186e1299a8f06fcc93f1949d`. Both inner and outer decision partitions are `holdout`; forecasts are unchanged from the original kernel.

## Freeze and technical exception ledger

The original strict run scored 2/3 events; the identity-only corrected run also scored 2/3. Their complete-three-event MAEs remain null. Only the final technical-correction run scores all 3/3; the earlier partial means are never relabelled as three-event results.

- Candidate model commit: `d466efa50375a28d05795d46740c89e6dcf80e8a`.
- Pre-acquisition source/policy/sampling/scoring freeze: `8d7926c32d1ffe31a7e9d1a15c48a2baba7eb7e7`; 16 source/test hashes and the original reservation hash are bound.
- Metadata-only British alias correction: `358345f1eea44700b7728fb93fdb2523fe356576`. Cached OpenF1 session 9558 / meeting 1240 gives `country_name=United Kingdom`, scheduled `2024-07-07T14:00:00Z`; the original adapter expected `Great Britain`. This was an adapter rejection, not service unavailability. The event/circuit/start/offsets did not change.
- Optional-audit correction: `32c8938a03b6a4d8afdca84bd566f8d81db8678f`. The hash-bound Jolpica Tsunoda lap 27, stop 1 record has raw `duration=""`; the raw string remains intact and normalized `duration_seconds=null`. All page/hash/identity/key checks still run. No target, row or driver is removed. Pit-audit rows never enter the observation model.
- Original run: `output/whole-race-holdout/original`; identity-only run: `output/whole-race-holdout/corrected`; final run: `output/whole-race-holdout/final`.
- Exact Monaco/Italian decision packets, predictions, scores, summaries and source manifests are identical to the original run. Version selection was fixed by the technical correction, never by performance.

## Source coverage and integrity

| Event | Accepted OpenF1 laps | Null durations | Accepted stints | Interval updates | Position updates | Quarantined rows |
|---|---:|---:|---:|---:|---:|---:|
| Monaco Grand Prix | 1237 | 20 | 39 | 23976 | 127 | 4 |
| British Grand Prix | 961 | 2 | 64 | 22499 | 252 | 2 |
| Italian Grand Prix | 1009 | 1 | 50 | 20444 | 482 | 0 |

Saved 66 ordinary GET receipts, all HTTP/CONNECT `200 200`, with 11,557,408 raw response bytes. Every body matches its saved SHA-256 and byte count. No retries, alternate hosts, credentials or network requests after the optional-audit correction were used.

- Source identity uses historical same-race `Results.number` plus normalized name tokens, never current `permanentNumber`. Final position/status/time fields are excluded from driver features.
- Jolpica timings/pits are separate audit streams. Reported first-lap/source duration disagreements are retained; timings are never blended into OpenF1 features.
- Monaco quarantines four stints with invalid/unknown `lap_start`; Britain quarantines one lap with unknown `date_start` and one invalid stint start. No replacement timestamp, stint, gap or duration is fabricated.
- Raw directories: `/workspace/real-data/holdout-2024-{metadata,monaco,british,italian}`. Each response retains `.body`, `.headers` and `.meta.json`. The report JSON includes receipts and source manifests.

## Exclusions at the fixed denominator

### Monaco Grand Prix

- Lap: `{"insufficient_prefix_laps": 236, "target_already_started": 11}`
- Gap: `{"insufficient_or_stale_numeric_interval_prefix": 262, "stale_interval_outcome": 7, "invalid_or_null_interval_outcome": 1}`

### British Grand Prix

- Lap: `{"insufficient_prefix_laps": 23, "target_already_started": 12, "target_duration_unknown": 1, "target_missing_no_retirement_inference": 148}`
- Gap: `{"insufficient_or_stale_numeric_interval_prefix": 228, "invalid_or_null_interval_outcome": 3, "stale_interval_outcome": 11}`

### Italian Grand Prix

- Lap: `{"target_already_started": 8, "target_missing_no_retirement_inference": 193}`
- Gap: `{"stale_interval_outcome": 5, "insufficient_or_stale_numeric_interval_prefix": 238, "invalid_or_null_interval_outcome": 4}`

## Interpretation and remaining gaps

This evaluates unconditional full-lap and fresh asynchronous interval-report forecasts. It does not establish synchronized physical gaps, verified historical publication times, calibrated probabilities, action-effective pit timing, inventory/rule feasibility or causal strategy gains. Strategy scores remain **0**, with metrics **null**. Rain/control/pit outcomes are not retrospectively removed from forecast-error samples. Only three whole events are reserved; repeated driver/cutoff targets are correlated. Further model tuning would require a newly reserved whole-event test set.

## Local evidence and reproduction

- [Model/policy/source freeze](../examples/holdout-evaluation-freeze.json)
- [British metadata identity erratum](../examples/holdout-identity-erratum.json)
- [Nullable optional pit-audit erratum](../examples/holdout-audit-erratum.json)
- [Durable report, counts, SHA-256 and HTTP receipts](holdout-validation.json)
- [Full local final report](../output/whole-race-holdout/final/evaluation.json)
- [All 69 frozen decisions](../output/whole-race-holdout/final/decisions.json)

Preserve the two earlier run directories and the exact cached raw/metadata files; their hashes are part of the correction ledger. Use a new output directory for a local recomputation. This command performs no network acquisition.

```sh
python -m f1_strategy_optimizer.holdout_audit_erratum \
  --data-root /workspace/real-data \
  --output-dir output/whole-race-holdout/reproduction-new-directory \
  --manifest examples/holdout-audit-erratum.json \
  --audit-commit 32c8938a03b6a4d8afdca84bd566f8d81db8678f
```

Targeted validation at the respective freezes, all completed before British first error scoring: 16 adapter/protocol synthetic tests, 7 metadata-only alias tests, 6 optional-audit tests; Ruff passed. Integration regression is owned by the parent workflow.
