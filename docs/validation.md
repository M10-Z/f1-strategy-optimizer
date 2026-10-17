# Release-candidate validation — 2026-10-17

[中文说明](validation.zh-CN.md)

## Reproducible checks

```sh
python -m pytest -q -W error::FutureWarning
python -m ruff check .
python -m ruff format --check src tests main.py _compat.py data_engine.py degradation_model.py dp_solver.py environment.py
python -m build
```

The initial source snapshot recorded **95 passing tests** on Python 3.13, with lint and
formatting checks passing.
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

## Cloud iteration — holdout artifact integrity

On 2026-10-17, the Linux/Python 3.12.14 environment reproduced the 95-test baseline.
Four new CLI regressions failed before the fix: default/explicit holdout exports differed
from the validation model, a sparse test-only compound aborted the run, and perturbing
held-out/future times changed the exported model.

After the fix, **103 tests pass** with `-W error::FutureWarning`; Ruff lint, formatting and
`git diff --check` pass. The eight added cases also cover mixed/zero evaluation coverage,
future-year exclusion, normalized CSV/source hashes and invalid splits leaving no outputs.
Existing demo coverage verifies that exploration still fits all input years.

Both sdist and wheel build successfully. The installed wheel was imported from a temporary
directory outside the source checkout under isolated Python (`-I`), using the environment's
installed scientific dependencies. It passed a synthetic demo with comparison/holdout, a
2024 CSV backtest with 2025 excluded, and a sparse unseen-compound backtest. The latter
correctly reports 0/1 evaluated laps instead of an error metric. Local generated artifacts
are under `output/iteration-holdout-integrity/` and are not committed.

There are 18 pre-existing NumPy/pandas timedelta deprecation warnings (also present in the
baseline); no FutureWarning failures. This iteration did not run hosted CI, other Python/OS
combinations, or download/validate real races. These results establish software behavior
with synthetic fixtures, not real-world predictive accuracy.

## Position-planning iteration — 2026-10-17

The next iteration changes the product objective to finish position against responsive,
heterogeneous opponents. Before that change, seven additional data/baseline cases brought
the suite to 110 tests; four deleted-lap/message regressions failed before their fixes.
The multi-car module adds 20 cases, bringing the local Linux/Python 3.12.14 suite to
**130 passing tests** with `-W error::FutureWarning`. Ruff lint/format and diff checks pass.
There are 31 instances of the existing timedelta deprecation warning family after adding
more fixtures; no warning is used as evidence of race-model accuracy.

The competition checks include independently summed lap/pit costs, tyre reset, blocked versus
permitted overtakes, SC/VSC passing restrictions and pit-driven order changes, bounded SC
gap closure, distinct fixed/undercut/overcut timing, delayed weather observation, current-status
pit pricing, known-history replanning, rejected future information, weighted position risk,
rank-first selection despite a faster time-only alternative, the existing fitted-model
interface, and CLI provenance/overwrite protection. A fixed-versus-reactive ablation confirms
that opponent responses change finishing positions and recommendations.

The installed `f1-race-plan` entry point passes the four-car example. sdist/wheel build and a
source-external installed-wheel smoke check pass, using isolated Python with the environment's
scientific dependencies. The example covers 13 candidates and four declared hypothetical
stress scenarios; generated artifacts are in `output/position-plan-iteration/` (untracked).
The [competition guide](competition.md) records measured synthetic outputs and limitations.

Real timing downloads were denied by the proxy; there are **no real finishing-position,
lap-error or strategy-benefit results**. See the [access attempt](real-validation-2026-10-17.md).
No physical parameter or event probability was calibrated. Hosted CI and other platforms
have not been run in this environment.

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
