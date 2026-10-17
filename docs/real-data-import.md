# Importing trusted race caches or cleaned CSVs

[中文](real-data-import.zh-CN.md)

No new network access is needed for these paths. Data origin and lawful availability must be
known; a CSV filename alone is not provenance. Preserve source URL/provider, event/session,
collection date, source/library versions, cleaning steps and original file hashes alongside
the data. The program hashes imported CSV bytes and normalized output but does not independently
verify that a user CSV is real or automatically ingest a provenance sidecar.

## Existing FastF1 cache

Copy the **complete cache directory** from a trusted source into a writable local directory,
preserving its layout. Do not copy only a session pickle and assume schedule/weather/messages
are included. Current adapters use FastF1 3.8.x-compatible race sessions and load lap timing,
weather and race-control messages; unknown deleted-lap flags cause a failure. Existing caches
may need additional source data before they are usable. Do not automatically refill online.

For a cache containing Bahrain 2022–2024:

```sh
f1-strategy backtest --track Bahrain --start 2022 --end 2024 --holdout-year 2024 \
  --offline --cache-dir /path/to/trusted-cache --output-dir output/trusted-bahrain-validation
```

This fits on earlier years only. Missing cache content fails explicitly. A partial run is not
equivalent to the requested coverage; inspect loaded/failed years and evaluation coverage.
Keep downloaded cache data and generated reports outside Git.

## Normalized cleaned lap CSV

Minimum required columns for the existing `validate_laps` API:

| Field | Validation |
|---|---|
| `Year`, `LapNumber`, `TyreLife`, `Stint` | Positive finite integers |
| `LapTimeSeconds` | Positive finite seconds, not a time-formatted string |
| `Driver` | Nonempty identifier; surrounding whitespace is normalized |
| `Compound` | SOFT/MEDIUM/HARD; surrounding whitespace/case normalized |
| `Event` (recommended) | One nonempty event/track per file; normalized if supplied |
| `TrackTemp` (optional) | Retained metadata; fitting/holdout currently use reference temperature |

Duplicate year/event/driver/lap keys and empty datasets are rejected. This iteration closes a
whitespace-duplicate driver loophole and rejects blank event names. A minimal shape check, with
no fit or download:

```python
import pandas as pd
from f1_strategy_optimizer.models import validate_laps
laps = validate_laps(pd.read_csv("/path/to/cleaned-laps.csv"))
print(len(laps), sorted(laps.Year.unique()))
```

Raw FastF1 tables require `clean_session_laps` first: timing/compound/stint/driver metadata,
pit-in/out flags, accuracy, track status and known deleted flags. The cleaned CSV path trusts
the supplier's cleaning and cannot reconstruct excluded laps or independently verify those flags.
Document the exclusion process instead of inventing clean flags. Fit each event separately.

```sh
f1-strategy backtest --csv /path/to/cleaned-laps.csv --holdout-year 2024 \
  --output-dir output/trusted-csv-validation
```

At least one prior training year and a nonempty holdout year are required, with enough age
variation and samples to fit the reported compounds. Inspect coverage and training-only baseline
comparisons; a valid CSV schema does not guarantee a usable model.

## Minimum additional evidence for position validation

The cleaned CSV above intentionally removes pit/non-green laps; it cannot validate multi-car
strategy outcomes by itself. Supply at least one trusted race segment with timestamped driver
order/gaps on the same lap, compound/age, actual pit entry/exit or stop boundaries, team identity,
visible track/weather status and clearly separated later outcomes. Record season/event, total
distance, decision boundary, data source and when each observation became available. Finite
stock or rule claims additionally require inventory/usage and applicable event-rule evidence;
unknown stock stays explicitly unknown, never invented.

The existing JSON snapshot accepts these observed state fields plus **separately labeled
assumptions** for vehicle pace, tyre curves, pit loss and scenario weights. Public lap pace is
confounded by traffic/fuel/driver behavior. Automatic historical snapshot reconstruction and
position replay evaluation are not implemented. The first data-backed iteration should build
that narrow adapter and measure existing transition errors; do not feed known future SC/weather
or rival actions into a historical decision. One segment permits a smoke validation, not reliable
probability calibration; held-out races are needed for broader accuracy claims.

Access to timing hosts is still [blocked](real-validation-2026-10-17.md). These instructions do
not claim any real dataset was imported or evaluated in the synthetic development iterations.
