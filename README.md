# F1 Strategy Optimizer

[Focused value/quality review · 实际价值复核](docs/value-review.zh-CN.md): prefix-based participant selection, conservative target ranking, verified offline exports; historical research only.

[Local browser workbench](docs/workbench.md)：`python -m f1_strategy_optimizer.workbench` → http://127.0.0.1:8765

[中文说明](README.zh-CN.md) · [Methodology](docs/methodology.md) · [Contributing](CONTRIBUTING.md)

An offline-first Python research toolkit moving toward **position-oriented strategy planning
against opponents with different vehicle performance**. The first multi-car planner compares
finish-position distributions under explicit hypothetical scenarios and responsive opponents.
The existing deterministic single-car optimizer remains a model-relative baseline and tyre-model
research tool. This is an independent project, not an official FIA, Formula 1 or Pirelli tool.

## Multi-car position planning

After installation, run the original synthetic four-car example:

```sh
f1-race-plan --scenario examples/competition.json --output-dir output/position-plan
# From a source checkout: python -m f1_strategy_optimizer.race_planner --scenario ... --output-dir ...
```

The input snapshot contains gaps, vehicle pace, tyres/ages, remaining distance and visible
track/weather conditions. Candidates include staying out and changing tyres at different
pit boundaries. Opponents follow fixed plans or react to observed undercuts/overcuts.
Traffic, restricted passing, SC/VSC and weather changes affect the simulated outcome.
JSON and Markdown outputs rank candidates by scenario-weighted finish position, then worst
position, and expose the position distribution, downside share and every opponent response.

**Scenario weights and physics are assumptions, not calibrated probabilities or guaranteed
optimal race advice.** The planner handles same-lap cars, optional finite fresh tyre stock,
explicit race-specific rule subsets, up to two future stops per search, rolling replanning,
same-team pit-box waits and an optional team rank-sum objective. It is not a full sporting
compliance checker. Try `examples/competition-resources.json` with the same command and a new
output directory; see [resources and replanning](docs/resources-and-replanning.md).
Two teammates can now be planned jointly with `examples/competition-joint.json`; individual
ego rank remains the default objective, and explicit cooperation reports each driver's cost.
See [joint planning](docs/joint-planning.md) and [trusted cache/CSV imports](docs/real-data-import.md).
A timestamped normalized-export evaluator is available as `f1-replay`; it compares frozen
decisions with separate next-lap outcomes and reports action-matched coverage. See the
[replay contract and synthetic example](docs/replay.md). Action-matched real strategy accuracy
remains unmeasured. `f1-event-replay` now imports verified Bahrain 2023 archives, reconstructs
common UTC prefixes and evaluates frozen, unconditional lap-time/interval-report forecasts.
See the [event-time contract](docs/event-replay.md) and [real development benchmark](docs/event-replay-validation-2026-10-17.md).
Missing intervention timing keeps strategy candidates blocked; observation errors are not strategy gains.
The current terminal menu remains
the single-car research interface. See [architecture, timing semantics and limits](docs/competition.md)
and the [blocked real-data attempt](docs/real-validation-2026-10-17.md).

## Interactive terminal menu

Run `f1-menu` or `f1-strategy menu` after installation. From the source checkout,
use `python main.py menu`; Windows users can also double-click `start.cmd`.
Choose **中文 / English** at startup; switch language from the main menu at any time.
The wizard covers demo, historical race/driver analysis, held-out validation, recent results,
and output/cache settings. Enter accepts defaults, `b` edits the previous step while retaining
earlier answers, `q` cancels the form and returns to the menu, `0` exits,
and Ctrl+C cancels the current operation. Every run gets a new timestamped directory.
Real-data workflows default to existing-cache-only mode, with an explicit online option.
Track/team/driver inputs still use FastF1 names; engine diagnostics may remain in English.
Directory settings last for the current session; browsing shows the 20 newest runs.
Interactive terminals show one question per screen. Enter `?` for formats, ranges and examples;
normal prompts show only the question, choices and default. Driver history selection shows actual
year ranges or lets you enter a custom starting year; prediction excludes the target year.

## Quick start

Python 3.10–3.13 is the intended supported range; CI tests 3.10 and 3.13 on Windows/Linux.
From a clone of this repository:

```sh
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install .
f1-strategy demo --compare --holdout-year 2025 --output-dir output/demo
```

The demo generates original synthetic laps with a fixed seed. **No network access or
FastF1 installation is needed after package installation.** Choose a fresh output directory
for every run; existing outputs are never silently overwritten.

Outputs: `strategy.json`, `strategy.csv`, `laps.csv`, `manifest.json`, `model.png`,
`scenarios.json`, `strategies.png`, and (when requested) `backtest.json`.
The manifest records source provenance, normalized-data SHA-256, package versions, rules,
parameters, fit diagnostics and extrapolation flags.

Standalone `backtest` exports the prior-year training model in both `manifest.json` and
`model.png`, matching `backtest.json.model`. The manifest's `model_role` is
`holdout_training`. For `demo`/`optimize`, including runs with `--holdout-year`, it is
`exploratory_all_input`: strategy and plot use all input years, with validation kept separate.
`backtest.json` records split sizes, ignored future years and evaluated/unmodeled lap counts;
zero evaluated laps means no prediction errors could be measured. `laps.csv` retains all
normalized input rows for reproducibility, including held-out and ignored future rows.

![Synthetic-data scenario comparison](docs/assets/synthetic-strategies.png)

The image above is generated by the quick-start command, seed 42. It shows model-relative
synthetic scenarios, not observed race results.

## Real race data

```sh
python -m pip install ".[data]"
f1-strategy optimize --track Bahrain --start 2022 --end 2025 --laps 57 --cache-dir cache --output-dir output/bahrain
f1-strategy backtest --track Bahrain --start 2022 --end 2025 --holdout-year 2025 --cache-dir cache --output-dir output/validation
```

This path downloads data via FastF1 and creates the chosen cache directory. Failed years
stop the run by default. `--allow-partial` explicitly permits incomplete coverage and records
every failed season. A successful fetch is not evidence that a model is accurate.
No live data downloads run in CI.
Use `--offline` to require existing FastF1 cache entries without sending data requests.

For a specific driver/team, the separate entry point shares the validated solver and models:

```sh
f1-driver-analysis --track Bahrain --team Ferrari --driver LEC --year 2025 --output-dir output/leclerc-2025
```

See [driver analysis](docs/driver-analysis.md) for identity checks, explicit fallback,
historical-review versus prediction modes, and data requirements.

Use your own normalized CSV without network access:

```sh
f1-strategy optimize --csv output/demo/laps.csv --laps 57 --output-dir output/from-csv
f1-strategy backtest --csv output/demo/laps.csv --holdout-year 2025 --output-dir output/from-csv-validation
```

Required columns: `Year, Driver, Stint, LapNumber, TyreLife, Compound, LapTimeSeconds`.
Optional columns: `Event, TrackTemp`. Use one track/event per dataset. Compound labels must
be `SOFT`, `MEDIUM`, `HARD`; physical C-number nominations are not mapped globally.
Times are seconds, temperature is degrees Celsius, and laps/stints are positive integers.
Duplicate driver/year/lap keys and nonfinite observations are rejected.

## API

```python
from f1_strategy_optimizer import RaceConfig, fit_model, solve
from f1_strategy_optimizer.models import synthetic_laps

model = fit_model(synthetic_laps(seed=42))
config = RaceConfig(total_laps=57, pit_loss=24.0)
strategy = solve(model, config)
print(strategy)
```

`solve` accepts any model exposing `compounds` and `predict(compound, age, track_temp)`.
Models are explicit objects; independent fits never overwrite a global model. Importing
the package or fitting a model does not create caches, plots or output directories.
Plotting is available separately in `f1_strategy_optimizer.plotting`.

## Single-car rules and sensitivity

```sh
f1-strategy demo --rules examples/rules/simplified-dry.json --scenario examples/scenarios/reduced-pit-loss.json --model-parameters examples/model-parameters.json --compare --output-dir output/scenario
```

Rules carry a season, event, version and source description. Implemented constraints are
minimum distinct compounds, minimum stints, maximum tyre age (including per-compound
limits), and optional starting compound. They are **not complete sporting regulations**.
Do not infer a wet-tyre exemption from rain alone. No automatic event-specific regulation
selection is performed.

Known pit-loss overrides are hypothetical, deterministic scenarios. They do not simulate
safety-car bunching, slower laps, pit queues or uncertain future events. `--compare`
reoptimizes starting compounds, pit losses, temperatures, degradation floors and a known
reduced-loss lap. It prices the baseline schedule in each same scenario for comparison.
For a forced starting compound, a positive difference is a constraint cost, not a bug.

## Single-car research scope

- Fits within year/driver/stint groups to reduce intercept confounding; uses a median group
  baseline. Fuel correction is applied to both slopes and baselines.
- Reports raw and effective training errors; held-out validation trains **only on prior years**.
- Fuel gain, temperature response and degradation floors are explicit uncalibrated priors.
  Forced compound ordering is disabled by default. Low fit quality is not “fixed” by priors.
- Optimal means optimal in the supplied model. It is not a prediction of real race results.
- No traffic, overtaking, fuel trajectory during optimization, tyre inventory, used starting
  tyres, wet tyres, red flags or stochastic safety-car policy is modelled.
- Curves outside observed ages are extrapolations. Constant relative pace and unlimited
  replacement tyre sets are simplifying assumptions. Held-out lap errors do not measure
  the causal benefit of a different strategy.

See [methodology](docs/methodology.md), [data provenance](docs/data-and-rules.md),
[migration notes](docs/migration.md), [validation record](docs/validation.md) and [roadmap](docs/roadmap.md).

Forecast defaults, explicit-assumption strategy exploration and the next local UI contract: [guide](docs/exploration-ui-contract.md). Whole-race holdouts are [reserved before tuning](examples/whole-race-holdout-lock.json); Bahrain remains development data.

## Development

```sh
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check src tests main.py _compat.py data_engine.py degradation_model.py dp_solver.py environment.py
python -m ruff format --check src tests main.py _compat.py data_engine.py degradation_model.py dp_solver.py environment.py
python -m build
```

Tests include an independent exhaustive oracle for small races, terminal-pit and tyre-age
regressions, held-out leakage checks, cache initialization, Unicode paths and offline CLI exports.
Build artifacts contain the installable package, not local caches, presentations or PDFs.

## License

Original source code and generated synthetic example data are under [MIT](LICENSE).
Third-party race data, documents and marks retain their respective ownership and terms;
the project does not relicense them. Prefer source links and local caches to redistributing
raw third-party material. See [data and rules](docs/data-and-rules.md).

All guides have Chinese editions: [documentation index](docs/README.md).
See the [changelog](CHANGELOG.md) and [Chinese license reference](LICENSE.zh-CN.md).
