# Real-data validation attempt — 2026-10-17

[中文](real-validation-2026-10-17.zh-CN.md)

Status: **blocked before any real lap evaluation**. No real MAE, baseline improvement,
finishing-position accuracy or calibrated event probabilities have been measured.

The bounded request was Bahrain race sessions for 2022–2024, with 2022–2023 training
and 2024 held out. There was no existing session cache. FastF1 3.8.3 stopped at 2022
with `DataNotLoadedError`; 2023–2024 sessions were not subsequently downloaded.
Direct small endpoint probes returned `ProxyError: Tunnel connection failed: 403 Forbidden`
for `livetiming.formula1.com`, the built-in `livetiming-mirror.fastf1.dev`, and FastF1's
Jolpica results source `api.jolpi.ca`. The GitHub-hosted FastF1 calendar returned HTTP 200,
but it contains no race lap observations. An additional public
[FastF1-derived dataset](https://data.mendeley.com/datasets/djr8rnjtjp/1) had readable web
metadata, but its download API was also denied by the environment proxy. No data from it
were obtained or treated as validated. Local machine-readable evidence is in
`output/real-validation-discovery/attempt.json` (not committed).

Source inspection found a separate correctness defect: both adapters disabled race control
messages although FastF1 uses them to populate deleted-lap flags. See
[FastF1 3.8.3 source](https://github.com/theOehrly/Fast-F1/blob/v3.8.3/fastf1/core.py).
The adapters now load messages and reject missing/unknown flags, with regression tests.
Cleaning records overlapping metadata exclusions separately from numeric exclusions.
The lap backtest also compares against a training-only compound-median baseline on exactly
the same held-out samples. These software checks use synthetic fixtures, not real outcomes.

The product goal subsequently changed to position-oriented multi-car planning. Lap-time
validation remains a component check, not the final objective. Once data access is restored,
freeze information available at each decision boundary, estimate pace only from earlier
observations (with traffic/fuel confounding disclosed), and replay held-out race segments.
Evaluate position-distribution calibration, realized rank/regret against declared opponent
policies, pit-response behavior and traffic errors. A historical finish cannot establish the
causal benefit of an unobserved alternative strategy. Future weather, SC/VSC and opponent
actions must not be supplied as known inputs to a historical decision.

To resume the bounded component check with a fresh output path:

```sh
python -m f1_strategy_optimizer backtest --track Bahrain --start 2022 --end 2024 \
  --holdout-year 2024 --cache-dir cache --output-dir output/bahrain-2024-real
```

Network access to an approved timing source, or a trusted local cache/normalized CSV with
provenance, is required. No permissions were changed and no prior was calibrated.
