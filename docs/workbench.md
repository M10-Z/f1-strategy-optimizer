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

The default assumption model contains four of twenty cars over laps 9–14. Ranks are within
that subset at the model horizon, not full-race final classification. Scenario weights and
future actions are hypothetical. Unknown stock uses an acknowledged unlimited model. The
short manually supplied example is not calibrated to real future outcomes. Selecting another
driver maps identity/team labels only, not calibrated numerical parameters.

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
`--data-dir output/workbench-all-events`; add `--port 8767` if desired. Numeric exploration
assumptions remain unchanged illustrative values, not a fit to holdout results. Rebuild the
catalog offline using `scripts/build_workbench_catalog.py` with the final report and decisions.
The [holdout report](holdout-validation.md) records both transparent British adapter errata.
