"""Focused value review: actual prefix, missing full field, manual full field and rejection."""

import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

out = Path("output/value-review/extended-browser")
out.mkdir(parents=True, exist_ok=True)
results = {}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    errors, requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: requests.append(r.url))
    page.goto("http://127.0.0.1:8768")
    page.wait_for_selector("#assumed-cars input")

    def apply(a):
        page.locator("#advanced").evaluate("e=>e.open=true")
        page.locator("#assumption-json").fill(json.dumps(a, indent=2))
        page.locator("#apply-json").click()
        expect(page.locator("#global-error")).not_to_be_visible()

    def run():
        page.locator("#ack").check()
        started = time.monotonic()
        page.locator("#compare").click()
        page.wait_for_selector("#comparison-content:not(.hidden)", timeout=20000)
        return time.monotonic() - started

    def export(name):
        with page.expect_download() as download:
            page.locator("#export").click()
        path = out / (name + ".json")
        download.value.save_as(str(path))
        # Real downloaded JSON, separate Python process and no network.
        replay = subprocess.run(
            [".venv/bin/python", "-m", "f1_strategy_optimizer.workbench_replay", str(path)],
            check=True,
            text=True,
            capture_output=True,
        )
        results[name + "_offline_replay"] = json.loads(replay.stdout)["status"]
        return json.loads(path.read_text())

    # Reactive opposition actually pits inside the engine; editing pace recalculates.
    page.get_by_label("sainz response", exact=True).select_option("cover_undercut")
    page.get_by_label("sainz base_lap_time", exact=True).fill("103")
    page.get_by_label("sainz base_lap_time", exact=True).dispatch_event("change")
    results["nearby_reactive_seconds"] = run()
    first = export("reactive-prefix")
    assert any(
        "sainz" in t["pit_actions"]
        for t in first["exploration"]["stay_out"]["candidate"]["outcomes"][0]["trace"]
    )
    page.get_by_label("sainz base_lap_time", exact=True).fill("110")
    page.get_by_label("sainz base_lap_time", exact=True).dispatch_event("change")
    expect(page.locator("#export")).to_be_disabled()
    run()
    second = export("recomputed-prefix")
    assert first["assumptions_sha256"] != second["assumptions_sha256"]
    assert (
        first["exploration"]["stay_out"]["candidate"]["outcomes"][0]["driver_elapsed_seconds"][
            "sainz"
        ]
        != second["exploration"]["stay_out"]["candidate"]["outcomes"][0]["driver_elapsed_seconds"][
            "sainz"
        ]
    )
    assert not any("/api/reveal" in r for r in requests)

    # Full registered field is selectable, but unknown gaps cannot be auto-filled.
    page.locator("#field-mode").select_option("all")
    expect(page.locator("#assumed-cars tr")).to_have_count(20)
    page.locator("#ack").check()
    page.locator("#compare").click()
    expect(page.locator("#global-error")).to_contain_text("缺少", timeout=10000)
    expect(page.locator("#export")).to_be_disabled()
    page.locator("#assumptions").screenshot(path=str(out / "missing-full-field.png"))
    a = json.loads(page.locator("#assumption-json").input_value())
    missing = []
    for car in a["planning"]["state"]["cars"]:
        for key, value in list(car.items()):
            if value is None and key in {"gap_seconds", "base_lap_time", "compound", "tyre_age"}:
                missing.append(
                    {
                        "driver": car["driver"],
                        "field": key,
                        "manual_value": 0
                        if key in {"gap_seconds", "tyre_age"}
                        else "MEDIUM"
                        if key == "compound"
                        else 100,
                    }
                )
                car[key] = missing[-1]["manual_value"]
    a["planning"]["source"] += (
        " Browser acceptance ONLY: manually fill missing fields as "
        + json.dumps(missing)
        + ". These are test hypotheses, not measured full-field inputs."
    )
    a["field_assumptions"]["state_alignment"]["rationale"] = a["planning"]["source"]
    apply(a)
    results["full_20_manual_seconds"] = run()
    full = export("manual-20-car")
    assert full["exploration"]["model_scope"]["modeled_driver_count"] == 20
    assert full["exploration"]["model_scope"]["excluded_drivers"] == []
    assert all(
        c["tyre_inventory"] is None for c in full["assumptions"]["planning"]["state"]["cars"]
    )
    results["manual_missing_inputs"] = missing
    page.locator("#comparison").screenshot(path=str(out / "manual-20-car.png"))

    # A declared model scenario with an actual sensitivity reversal (not calibration).
    a = json.loads(Path("examples/workbench-reversal-stress.json").read_text())
    apply(a)
    run()
    flip = export("sensitivity-reversal")
    assert any(c["winner_changed"] for c in flip["exploration"]["sensitivity"]["cases"])
    expect(page.locator("#sensitivity")).to_contain_text("方案翻转")
    page.locator("#comparison").screenshot(path=str(out / "sensitivity-reversal.png"))

    # All candidates, including stay-out, violate the declared rule subset.
    p = a["planning"]
    p["rules"] = {"season": p["state"]["season"], "event": p["state"]["event"], "min_stops": 2}
    apply(a)
    run()
    rejected = export("no-feasible-plan")
    assert rejected["exploration"]["top3"] == []
    expect(page.locator("#candidates")).to_contain_text("本次不提供策略建议")
    expect(page.locator("#stay-out")).to_contain_text("不可行")
    page.locator("#comparison").screenshot(path=str(out / "no-feasible-plan.png"))

    # Post-observation British data with current-cutoff projection, still unrevealed.
    page.locator("#field-mode").select_option("nearby")
    expect(page.locator("#ack")).to_be_enabled()
    page.locator("#race").select_option("british-2024")
    expect(page.locator("#snapshot-note")).to_contain_text("14:10:00")
    expect(page.locator("#assumed-cars tr")).to_have_count(5)
    a = json.loads(page.locator("#assumption-json").input_value())
    assert a["planning"]["state"]["completed_laps"] == 4
    results["british_seconds"] = run()
    british = export("british-prefix")
    assert british["exploration"]["model_horizon"]["through_lap"] == 10
    page.locator("#reveal").click()
    page.wait_for_selector("#reveal-result strong")
    expect(page.locator("#reveal-result")).to_contain_text("92.758")
    page.locator("#comparison").screenshot(path=str(out / "british-prefix.png"))
    results["no_future_requests_before_explicit_reveal"] = (
        sum("/api/reveal" in r for r in requests) == 1
    )
    assert results["no_future_requests_before_explicit_reveal"]
    assert not errors, errors
    results.update(
        browser_errors=errors,
        manual_edit_changed_simulation=True,
        missing_inputs_blocked=True,
        no_feasible_stay_out_visible=True,
    )
    (out / "acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    browser.close()
