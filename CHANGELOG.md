# Changelog

[中文说明](CHANGELOG.zh-CN.md)

## 0.1.0 — unreleased

- Load race control messages in both FastF1 adapters and reject unknown deleted-lap flags.
  Report overlapping metadata exclusions and subsequent numeric exclusions. Backtests now
  compare against a training-only per-compound median baseline on the same held-out laps.
- Record the bounded Bahrain real-validation attempt and network denial; real accuracy and
  parameter calibration remain unmeasured.
- Fixed standalone backtests failing on sparse compounds seen only in the held-out year.
  Their manifest/plot now use the prior-year validation model; exploration commands retain
  the all-input model, with explicit model roles. Added split/coverage reporting and ensured
  exported lap CSVs contain the normalized observations used by the model.
- Compact one-question terminal screens, on-demand `?` help and result pauses.
- Bilingual documentation and privacy-reviewed source-only distribution.

- Added a Chinese/English terminal wizard with startup language selection, result browsing,
  input validation, timestamped output directories and a Windows launcher.
- Added explicit offline-cache mode to the driver analysis entry point.
- Replaced ambiguous history-window input with concrete year-range choices; added bilingual
  examples, specific input errors and previous-step navigation that retains earlier answers.

- Converted the course prototype into an installable, offline-first research package.
- Fixed terminal-pit compound accounting, zero-length stints and finish-at-age-limit handling.
- Added explicit model/config interfaces, strict input validation and configurable rules.
- Removed import-time cache initialization and plotting/global model side effects.
- Added metadata-driven lap cleaning and explicit missing-season reporting.
- Added grouped regression, chronological holdout validation and recorded modelling priors.
- Added scenario comparison, model/strategy plots, provenance manifests and CSV/JSON exports.
- Added regression/oracle tests, Windows/Linux CI and contributor documentation.
