# Evidence-first frontend

The browser frontend is served by the existing local Python workbench. There is no Node package installation, asset build, CDN, account or live timing feed.

```sh
python -m pip install -e .
python -m f1_strategy_optimizer.workbench
```

Open `http://127.0.0.1:8765`. Stop the process with Ctrl+C. A fresh server starts with the bundled Bahrain historical archive, not current race data.

## What the dashboard shows

- An always-visible historical-replay label, catalog counts and failed model-acceptance warning.
- A full-field table from `GET /api/forecast?case=...`: fixed target lap, conditional lap-duration candidate, evidence age and abstention reason. Missing predictions remain “弃权”, never zero. Counts describe output coverage, not accuracy.
- Select a driver in the table to inspect their existing frozen facts, horizon gate and editable scenario assumptions.
- Candidate cards show declared pit stops and per-scenario model finish positions. These positions apply only to the selected modeled field; weights are not calibrated probabilities.
- Existing explicit reveal, cancellation, frozen export and stale-result invalidation are retained. Forecast requests do not fetch outcomes. Source failure clears the forecast table instead of retaining stale rows.

The immediate post-pit target remains independently gated. The field table does not bypass that gate. Observed sample ranges are not confidence intervals, and generating a number does not establish live readiness or validated strategy value.

## Verification

```sh
node --check src/f1_strategy_optimizer/workbench_static/app.js
node scripts/test_workbench_frontend.mjs
```

The dependency-free DOM contract test covers IDs, null forecasts, driver changes, error/loading clearing, scenario-rank and pit-stop rendering, stale-result invalidation absence of automatic startup reveal, deferred snapshot/driver interleaving, out-of-order snapshot responses, stale reveal responses and failed-load lockout. It is not a browser layout test.

For real Chromium acceptance use `scripts/verify_workbench_browser.py` with its normal and short-timeout server URLs. The 2026-11-04 cloud execution attempt could not launch Chromium because the container denied its singleton `socket()` operation, including the elevated execution attempt. No desktop/mobile visual pass is claimed for this change.

## Visual refresh

The interface now uses a restrained light palette, generous spacing, a compact project header, rounded monochrome actions and a sticky section navigator. This is an independent F1 research interface, not an OpenAI product; it uses no OpenAI name or logo in the UI. It requires no remote fonts or image assets.

Readiness warnings remain visible above the main workflow. Forecast tables are height-bounded with sticky column headers and keyboard-focusable scrolling regions. On narrow screens status cards stack, controls remain touch-sized and the section navigator scrolls horizontally. Reduced-motion preferences are respected. Existing field values, validation claims, model logic and reveal gating are unchanged by this visual refresh.

The visual refresh was subsequently checked in the connected browser at a desktop width of 1165 px and a narrow window with `innerWidth=500` (485 px content area). Both had no page-wide horizontal overflow; wide tables scrolled inside their own regions. CTA navigation, driver-table selection, acknowledgment gating and a three-candidate simulation with a stay-out baseline worked. The simulation completed in 0.32 seconds with 56 rollouts. Exact 390 px viewport emulation was not tested because browser DevTools was prohibited by organization policy. These browser checks cover the listed flows, not the entire earlier Playwright acceptance suite.

## Optional OpenF1 historical browser

A separate historical-observation panel is available through `history.js`. Opening the workbench does not call OpenF1. Click the historical panel's load button once, then selecting a year refreshes race options, selecting a race loads its drivers, and selecting a driver loads laps and stints. Only the local server's `/api/openf1/*` routes are called by the browser.

The panel never mutates the existing frozen research selection or calls prediction, reveal or simulation endpoints. Source download/receipt times describe a post-event retrieval, not availability during the race. Missing laps/times remain missing. Its JSON export contains the selected historical response, not a scored prediction artifact.

Selection changes immediately remove previous results. Delayed responses are discarded, cancellation clears the pending display, and errors require an explicit retry. Sealed sessions are disabled and the server remains authoritative about access. Identity and post-event source labels are checked before rendering a history response.

Run the isolated frontend tests with `node scripts/test_openf1_frontend.mjs`; these exercise contract fixtures without network requests. They do not establish successful retrieval from the real public API.

Stale-cache fallback is visibly labeled in the status, cache badge and warning area, including the original retrieval time and `source.warnings`. The same warning handling applies to race and driver lists; warnings clear when a later response no longer carries them. This is covered by fixture tests. A captured real OpenF1 response for Bahrain session 7953 / driver 16 also passed rendering-contract checks (40 laps, 3 stints) without an additional external request:

```sh
node scripts/test_openf1_frontend.mjs output/openf1-history-check-20261104/history.json
```

Connected-browser verification on 2026-11-04 confirmed offline initial state, race-list failure feedback, hidden old results, disabled export, unchanged frozen research selection, and no page-wide overflow at a 500 px window. The browser host's actual server-to-OpenF1 path failed with `URLError` caused by `ConnectionRefusedError` (errno 111). No network settings or browser-policy restrictions were changed. The successful 40-lap/3-stint browser path therefore remains unverified in that host, despite a successful backend fetch in the separate execution environment and the captured-response DOM checks above.
