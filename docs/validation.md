# Release-candidate validation — 2026-10-17

[中文说明](validation.zh-CN.md)

## Reproducible checks

```sh
python -m pytest -q -W error::FutureWarning
python -m ruff check .
python -m ruff format --check src tests main.py _compat.py data_engine.py degradation_model.py dp_solver.py environment.py
python -m build
```

The final local suite passes **95 tests** on Python 3.13. Lint and formatting checks pass.
Tests cover the independent small-race exhaustive oracle, final-lap compound accounting,
tyre-age limits, grouped fitting, chronological holdout, data validation, driver identity,
explicit fallback, exclusion of target-race data, offline demo exports and both terminal languages.
Terminal tests include previous-step edits, input errors, on-demand help, result pauses,
Chinese character width and real-process startup.

Source and wheel distributions are checked separately from the development checkout.
The wheel smoke test uses isolated Python outside the source tree, runs a synthetic demo
with scenario comparison and held-out validation, and checks both menu languages.

CI is configured for Windows/Linux and Python 3.10/3.13. Hosted results are recorded in
the repository Actions tab; a local pass is not a claim that every hosted job has passed.

## Distribution boundary

The first publication uses a reviewed source snapshot, without prior development Git
history. Files are selected explicitly; environment folders, caches, downloaded race data,
local reports, presentation materials, credentials and personal paths are excluded.
Commit metadata uses a GitHub no-reply address. The example image contains only synthetic data.

## Interpretation

These checks verify software behaviour, not real-world prediction accuracy or complete
sporting-regulation compliance. Model assumptions, extrapolation, uncalibrated priors and
unsupported race effects remain documented in the methodology. Version 0.1.0 is a research
candidate, not a validated real-time race decision system.
