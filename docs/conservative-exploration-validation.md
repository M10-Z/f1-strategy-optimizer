# Conservative forecast and exploration development record

Date: 2026-10-17. [中文](conservative-exploration-validation.zh-CN.md) ·
[Machine-readable scores and artifact hashes](conservative-exploration-validation.json)

The prior linear forecasts did not beat the simple baselines. This iteration selects prefix
median for laps and persistence for interval reports using the already-observed Bahrain
results. It does not claim a newly learned model beats those baselines. Context median is an
experimental comparison; the expanded results were not used to switch the chosen defaults.

Before this iteration, commit `719cdc89c7ba17e31501673bd8761069353e1a96` reserved entire
2024 Monaco, British and Italian races by circuit characteristics. Their results were not
acquired or evaluated. This is a reservation, not completed independent validation; the
current source adapter is still Bahrain-specific. Freeze a broader adapter/model/policy and
scoring manifest before opening those outcomes.

| Development set | Lap coverage | Linear MAE | Default median MAE | Context median MAE | Gap coverage | Gap linear MAE | Default persistence MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original 10 UTC cutoffs | 126/200 | 2.964945 | 1.741583 | 1.693448 | 124/200 | 5.024089 | 3.596758 |
| Fixed 18 cutoffs, 15:13–16:38 every 5 min | 309/360 | 3.477003 | 2.468472 | 2.411241 | 251/360 | 3.276854 | 3.262195 |

Errors are seconds. Both panels are Bahrain development; some UTCs overlap. Cutoffs were
written before running this iteration's expanded evaluation, but that does not make an
already-examined race unseen. All methods use paired targets. The expanded gap difference
is only 0.014658 seconds, so the strong original advantage does not establish a general win.
No confidence intervals or multi-race generalization claims are made.

Outcome-only diagnostics retain difficult targets. Original pit-related targets: 11, median
MAE 10.718091 versus 0.882961 for 115 targets not identified as pit-related. Expanded:
33 pit-related targets have median MAE 15.086121; the remaining 276 have 0.959841. Eleven
expanded targets overlap the identified control window, median MAE 12.444318. Pit and control
groups can overlap. These are descriptions, not causal attribution or a filtering rule.
Control ENDING is not clearance; explicit TRACK CLEAR closes the identified window. Linear
extrapolation can also carry a slowdown from a preceding VSC into a later target. Missing
activity, unknown terminal durations and asynchronous gaps remain explicit limitations.

The exploration example consumes the real frozen 15:18 record plus illustrative manual
assumptions. It models only four cars from laps 8 to 14. Its top three are stay-out,
pit-after-12-HARD and pit-after-12-MEDIUM; each has mean/worst horizon-end rank 2 within the
four-car model. This tie and the short horizon do not identify the actual best race strategy.
Stay-out is feasible under the supplied finite stock/rule assumptions. Four searches (base
plus three sensitivities), 56 rollouts, stayed within the declared 200 budget. Pit-loss changes
22→16/28 seconds and HARD degradation 0.06→0.12 did not change the winner; this is not a
robustness proof. Reports include every override, source-code/input hashes, nearby assumed
threats, first-post-stop-lap traffic proxies and same-scenario teammate costs.

Strict action-matched strategy scores remain **0**, metrics **null**. Exploratory plans now
provide useful options under explicit assumptions without presenting them as factual causal
benefit. Exact pit-action boundaries, calibrated scenario probabilities and real stock remain
outside verified source coverage. Historical availability of user assumptions is unknown.

Verification: 245 tests passed in one complete regression (31 existing NumPy/pandas deprecation
warnings); Ruff lint and format checks passed; sdist/wheel built successfully. Tests exercise
future-data invariance, same-target default scoring, context fallback, posthoc isolation,
control-ending semantics, hash tampering, missing assumptions, subset acknowledgement, finite
stock, cumulative budgets before planner calls, sensitivity and CLI exports. Independent
read-only review found no blocking exploration-contract issues. No public deployment, push or
holdout download occurred.

Local outputs: `output/bahrain-conservative-original`, `output/bahrain-conservative-expanded`,
`output/bahrain-assumption-exploration`. Earlier raw archives, output and recovery packs remain
intact. UI entry points and labels are specified in [the interface contract](exploration-ui-contract.md).
