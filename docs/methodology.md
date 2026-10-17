# Methodology and limitations

[中文说明](methodology.zh-CN.md)

## State and terminal semantics

At the START of lap L, a state is `(compound, age, used_mask, capped_stint_count)`.
Age is the age used to price the lap about to be driven. The first lap has age 1.
Costs are cumulative costs before L. After charging that lap:

1. If L is the final lap, test minimum compound/stint requirements and settle the race.
2. Otherwise continue on age + 1 if allowed, or pay the loss at the END of L and switch
   to age 1 for L + 1. The replacement may have the same compound.

A replacement compound enters the mask only on a transition that necessarily leads to a
driven lap. There is no pit transition at the finish and no zero-length stint.
Maximum age limits the age actually driven, not the fictitious age after finishing.
The stint-count state saturates at the required minimum, since larger counts do not affect
future feasibility. Inventory constraints would require additional state and are not implemented.

The solver caches model costs for each compound and reachable age, validates that they are
positive and finite, and returns a fully reconstructed schedule. A separate evaluator validates
and sums the schedule. Tests compare optima against an independent partition/product oracle.
Ties are deterministic by model compound order and state insertion order, not a secondary
objective such as fewest stops.

## Complexity

Let N = laps, C = compounds, A = maximum tyre age, K = minimum stint count.
The state upper bound per lap is S = C A 2^C K. Each state has at most C + 1 transitions.
Time is O(N S (C + 1)), excluding model prediction. The rolling cost tables use O(S), but
parent pointers use O(N S), so total memory is O(N S). With fixed C = 3, constants may be
suppressed, but storing all parents does not remove the factor N from total memory.

## Estimating degradation

The fitting target is observed lap time + fuel_gain_per_lap * (LapNumber - 1).
For each compound, center the features (age - 1, age² - 1) and target within each
Year/Driver/Stint group. Least squares estimates shared within-group slopes. The baseline
is the median of group median residual baselines. Rank-deficient fits fail explicitly.
This reduces group intercept confounding but cannot establish causal degradation: tyre
selection, traffic, track evolution, fuel assumptions and driver behaviour remain limitations.

The effective delta is the discrete running maximum of the fitted delta, zero, and a
configured linear degradation floor. It is nondecreasing, including outside the observed
age range. The optional temperature factor multiplies the degradation delta only, not the
whole baseline lap time. Its factor is bounded to [0.5, 2.0]. Both bounds and coefficients
are modelling choices, not a validated physical law. Compound gap = 0 disables forced
ordering; a positive gap explicitly enables that scenario prior.

Model plots display raw and effective curves separately and shade observed training ages.
The raw curve uses the reported model baseline; with an ordering prior enabled its baseline
may also be shifted. Training R² and MAE are descriptive, not held-out performance.

## Validation and comparison

Backtesting holds out one year and uses only earlier seasons. Later years are ignored.
It evaluates reference-temperature predictions against fuel-adjusted held-out observations,
reporting MAE, RMSE, signed bias and out-of-range ages. Missing training compounds are
reported, not silently fitted using test data. Standalone `backtest` uses this same prior-year
training model for its manifest, plot and extrapolation flags; it never fits held-out or future
laps. The manifest labels this model `holdout_training`. `demo`/`optimize` retain an
`exploratory_all_input` model for strategy exploration, even with `--holdout-year`;
their `backtest.json.model` is the separate training-only validation model.

The report's `data_split` records training/holdout sample counts and ignored future sample
counts/years. `coverage` records evaluated and unmodeled held-out laps. Per-compound errors
apply only to evaluated samples; absent training compounds do not contribute zero errors.
A report with zero evaluated samples is a coverage result, not measured prediction accuracy.
For each evaluated compound, a constant baseline uses the median fuel-adjusted lap time of
that compound in the training years only. It has no tyre-age response and is scored on the
same held-out samples with the same fuel prior. Baseline MAE/RMSE/bias and
`mae_difference_vs_baseline_seconds` are reported; a negative difference favors the fitted
model. This baseline comparison does not calibrate the fuel prior or establish causal effects.
The exported `laps.csv` retains all normalized input rows, while the source-file hash remains
separate from the normalized-data hash. It is not a training-only dataset.

Scenario comparisons price the original schedule AND reoptimized schedule in each same
scenario. Totals across different environments alone are not strategy improvements.
Forced-start scenarios impose an extra restriction, so they can cost more than an unrestricted
baseline. Known future reduced pit losses are perfect-information scenarios; they cannot be
interpreted as an online or stochastic policy. No confidence interval or calibrated probability
is claimed. Real strategy effectiveness needs additional race simulation and external validation.
