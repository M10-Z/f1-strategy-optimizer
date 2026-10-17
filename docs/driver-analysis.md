# Track / team / driver analysis

[中文说明](driver-analysis.zh-CN.md)

This independent entry point adds driver analysis without changing the main CLI.
It uses the same data adapter, grouped tyre model and DP solver.
Installed distributions also provide the equivalent `f1-driver-analysis` command.
Use `--offline` to read existing FastF1 caches without data requests, or use the bilingual
terminal wizard (`f1-menu`) to choose the data mode and fill in parameters interactively.

## Quick start

```sh
python -m pip install -e ".[data]"
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC
```

Only track, team and driver are required for **historical review**. If no year is
given, the last three calendar years are searched newest first for a matching race
scheduled at least six hours ago. Actual timing data must still load successfully.
The resolved year, event, driver and team are printed and saved.

Track accepts an exact calendar event name, location or country, ignoring case and
punctuation. Ambiguous names fail. Driver accepts full name, abbreviation or car number.
Team must match the session entry list; transfers and mismatched seasons are not guessed.
Use English names supplied by FastF1. Chinese aliases and a graphical selector are not
implemented.

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver "Charles Leclerc" --year 2025 --history-years 3 --output-dir output/leclerc-bahrain-2025
```

Default fitting uses only the selected driver **at the selected team**. Each compound
needs six cleaned laps and sufficient within-stint age variation; this is a numerical
screening threshold, not a confidence guarantee. At least two dry compounds must fit.
If samples are insufficient, expand history or explicitly permit fallback:

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC --year 2025 --fallback team
```

`--fallback team` tries same-team data for missing compounds. `--fallback field` then
permits the entire field. Sources report actual drivers, teams, years and sample counts.
No hidden fallback occurs by default.

## Prediction mode

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC --year 2025 --mode predict --laps 57
```

Prediction never loads target-race results or trains on target-year race laps. It
verifies membership using the target event's completed FP1 entry list and requires an
explicit planned race distance. Before FP1 data exists it fails instead of guessing.
`--history-years 3` includes the target year, so prediction uses up to two earlier races.
A historical forecast run today is a structural time split, not proof that every source
revision was available at the original prediction timestamp.

## Output and limits

Each run creates a unique directory under `output/`, unless `--output-dir` is given.
Nonempty destinations are rejected. Outputs are UTF-8:

- `driver-analysis.md`: identity, strategy, data sources and limitations.
- `driver-analysis.json`: full parameters, source tiers, skipped years and actual stints.
- `analysis-laps.csv`: cleaned historical selection pool. Source records identify the
  subset actually fitted; SHA-256 is recorded in JSON.
- `driver-model.png`: raw fitted shape and the curve actually used by the optimizer.
- `driver-strategies.png`: starting-tyre, pit-loss, temperature, degradation-prior and
  known reduced-pit-loss scenario comparisons. These are separate assumptions, not
  predicted probabilities of future safety-car events.

When earlier seasons provide enough samples, review also trains a separate model on
strictly earlier years and reports the target driver's held-out MAE/RMSE per compound.
This is lap-time validation, not evidence that a counterfactual strategy would win.
Insufficient history is explicitly reported instead of substituting training scores.

Historical distance defaults to the maximum recorded race lap, which may differ from
planned distance after a shortened race. Pit loss is a **24-second configurable prior**,
not an automatic event-specific measurement; use `--pit-loss` to override. Temperature
is the model's 35 C reference, not a measured forecast.

Actual stints come from uncleaned laps. DNF/lapped cars, gaps, used starting tyres,
unsupported compounds or invalid constraints prevent an unqualified model comparison.
Where scored, every stint transition is priced as a stop; red-flag changes may violate
that assumption. The gap is hypothetical model time, not a proven real-world saving.

The optimizer assumes unlimited new dry tyres and simplified dry constraints. It does
not implement complete FIA rules, traffic, overtaking, live race control or uncertain
weather. Historical review includes the target race and is not a pre-race prediction.

## Tests

```sh
python -m pytest tests/test_driver_analysis.py
```

Tests cover identity, transfers, ambiguity, explicit fallback, DNF, UTF-8 output,
latest-year selection and exclusion of target-race data in prediction mode.

Repository guides and terminal interaction are bilingual. Low-level CLI help, engine logs
and technical fields in generated reports currently remain primarily in English.
