# Local strategy workbench

[中文 / detailed guide](workbench.zh-CN.md)

Run the existing Python engine through a local standard-library HTTP server and a framework-free
browser UI. It binds only to 127.0.0.1. No account, CDN, public deployment or runtime network is needed.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m f1_strategy_optimizer.workbench
```

Open **http://127.0.0.1:8765**. Windows uses `.venv\Scripts\python.exe`; the installed command
is `f1-workbench`. `--port` changes the local port; `--timeout` sets the per-process simulation
limit (45 seconds by default). Ctrl+C stops the server.

The bundled real Bahrain archive example offers 15:18, 15:38 and 16:13 UTC frozen decisions and
all 20 drivers. Start with Leclerc at 15:18, inspect fact/inference/unknown status, change the
explicit manual assumptions, acknowledge the modeled scope, then compare. Three feasible plans
and stay-out are shown with assumed nearby threats, first-post-stop-lap traffic proxies,
matched-scenario teammate costs and sensitivity. Click reveal to request actual observation
outcomes; no outcome request happens before that action. Export saves matching frozen facts,
assumptions, simulation, optional revealed observations, versions, hashes and source evidence.

The default uses nearby cars and teammates from the selected frozen prefix (five cars for
Bahrain 15:18 Leclerc); custom or all registered cars can be selected. It starts from the
ego's completed-lap boundary with a six-lap default horizon. Unknown fields remain null and
block simulation until explicitly supplied. Pace is initialized from the median baseline
minus the assumed next-lap tyre contribution; this is not identified vehicle performance.
All selected cars are assumed active; inventory stays unknown/unlimited. Ranks are only
within the selected modeled field. Choose a target top-k and mean-rank or worst-rank-first
conservative ordering. Opponent policies, scenario weights and physical parameters remain
explicit hypotheses, not calibrated probabilities or causal strategy evidence.

Changed assumptions invalidate prior simulations and export. Changed selection also clears
revealed outcomes. Jobs run in separate cancellable processes, show elapsed time and fail with
readable errors or a real timeout. At most two concurrent jobs and 100 stored jobs are allowed.
Restarting the server clears in-memory runs; downloads remain on disk.

Bundled derivatives come from `output/bahrain-conservative-expanded` indices 1, 5 and 12;
original frozen hashes remain unchanged. OpenF1 session 7953 and Jolpica 2023 round 1 source
receipts are recorded separately. Each bundled file has a catalog SHA256. The outcome file is
opened only on explicit reveal, and the full source audit only on export. Export includes
posthoc evidence and is no longer a blinded model input. `--data-dir` accepts another catalog
with the same structure for additional races, but does not download data or build new cutoffs.

The optional Playwright/Chromium browser acceptance script is
`scripts/verify_workbench_browser.py`; see the Chinese guide for two-server commands. It checks
real data, editing, reveal gating, exports, driver/cutoff switches, malformed JSON, killed-process
timeout feedback and desktop/mobile layout. Runtime frontend assets and the real sample are
included in both wheel and sdist. See [the API contract](exploration-ui-contract.md).

[Measured browser acceptance](workbench-acceptance.md).

This workspace also contains `output/workbench-all-events`: four races and 72 frozen snapshots
(the three Bahrain examples plus 23 fixed UTCs for each reserved 2024 race). Start it with
`--data-dir output/workbench-all-events`; add `--port 8767` if desired. These races have now been observed: further work is development analysis. Prefix initialization
uses no outcomes; future actions, physics and scenarios remain uncalibrated assumptions. Rebuild the
catalog offline using `scripts/build_workbench_catalog.py` with the final report and decisions.
The [holdout report](holdout-validation.md) records both transparent British adapter errata.

Replay an actual downloaded file offline with
`python -m f1_strategy_optimizer.workbench_replay path/to/download.json`. This verifies all
hashes and engine source identity, then compares the complete deterministic simulation.
Exports now preserve server JSON bytes: the prior browser parse/stringify step corrupted
Python numeric hashes. Old artifacts are preserved. See the [focused review](value-review.zh-CN.md)
for British error diagnosis, limitations and end-to-end evidence.
