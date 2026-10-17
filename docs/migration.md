# Migrating the course prototype

[中文说明](migration.zh-CN.md)

The installable package is `f1_strategy_optimizer` under `src/`. A virtual environment directory is not the source package.

```python
from data_engine import fetch_cycle_data
from degradation_model import fit_tyre_degradation
from dp_solver import solve

df = fetch_cycle_data(cache_dir="cache")
model = fit_tyre_degradation(df)
strategy = solve(total_laps=57, model=model)
```

Changes from the prototype:

- `fit_tyre_degradation` returns a `TyreModel`, does not write a plot, and does not publish
  globals. `get_expected_lap_time(..., model=model)` requires an explicit model.
- `dp_solver.solve` retains historical argument names, with required `model=` injection.
  The new package API is `solve(model, RaceConfig(...))`.
- Input fitting data now requires `Year`, `Driver`, `Stint`, and `LapNumber`. Re-fetch old
  exports that omitted stint metadata; do not invent historical group identifiers.
- `python main.py` defaults to an offline demo. Explicit legacy `--track/--start/--end`
  arguments select the historical-data path. New commands are demo/optimize/backtest.
- No blanket warning suppression, import-time cache creation, guessed C-number mapping,
  implicit weather exemption, or automatic overwrite of output artifacts remains.
- Historical course report totals are not current regression targets. Fixes and changes in
  modelling assumptions can legitimately change the recommended strategy.

Before migration, keep a backup of old reports and source outside the repository.
Personal presentation materials are not part of the distribution.
