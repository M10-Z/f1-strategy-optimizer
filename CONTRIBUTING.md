# Contributing

[中文说明](CONTRIBUTING.zh-CN.md)

Start with a reproducible issue including Python/package versions, command, rules and model
parameters. Use synthetic data or a minimal permitted fixture; do not attach entire race
caches, copyrighted PDFs, private paths or access credentials.

Install with `python -m pip install -e ".[data,dev]"`. Run `python -m pytest -q`, Ruff checks
and formatting (commands in README), then `python -m build`. Tests must be offline and
deterministic. A bug fix should include a regression that fails before the fix. Changes to
DP state/transitions must pass the independent exhaustive oracle, not just snapshots.

Keep APIs, examples, CLI help and methodology aligned. Distinguish synthetic results,
historical observations, model-relative counterfactuals and future work. Report held-out
metrics separately from training fit. Explain sources and uncertainty for physical constants.

Submit a focused pull request describing the problem, change and actual validation. Do not
commit local environments, downloaded datasets, generated reports or secrets. Contributions
to original project code are made under the repository's MIT license.
