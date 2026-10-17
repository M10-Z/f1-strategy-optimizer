"""Optional real-browser acceptance; requires Playwright and Chromium locally."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8765")
parser.add_argument("--timeout-url", default="http://127.0.0.1:8766")
parser.add_argument("--output-dir", type=Path, default=Path("output/workbench-acceptance"))
args = parser.parse_args()
out = args.output_dir
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    started = time.monotonic()
    page.goto(args.url)
    page.wait_for_selector("#assumed-cars input")
    ready_seconds = time.monotonic() - started
    assert page.locator("#driver").input_value() == "leclerc"
    assert not any("/api/reveal" in url for url in requests)
    expect(page.locator("#reveal-result")).to_have_text("结果仍未揭晓。")
    page.screenshot(path=str(out / "desktop-start.png"), full_page=True)
    page.locator("#pit-loss").fill("18")
    page.locator("#pit-loss").dispatch_event("change")
    page.locator("#ack").check()
    started = time.monotonic()
    page.locator("#compare").click()
    page.wait_for_selector("#comparison-content:not(.hidden)", timeout=20_000)
    comparison_seconds = time.monotonic() - started
    assert page.locator(".candidate").count() == 3
    assert not any("/api/reveal" in url for url in requests)
    page.locator(".candidate").nth(1).locator("summary").click()
    page.locator("#comparison").screenshot(path=str(out / "desktop-comparison.png"))
    job_status = page.locator("#job-status").inner_text()
    page.locator("#reveal").click()
    page.wait_for_selector("#reveal-result strong")
    assert "99.073 s" in page.locator("#reveal-result").inner_text()
    with page.expect_download() as downloaded:
        page.locator("#export").click()
    downloaded.value.save_as(str(out / "decision-export.json"))
    record = json.loads((out / "decision-export.json").read_text())
    assert record["selection"]["driver"] == "leclerc"
    assert record["reveal"]["evaluation"]["lap"]["actual"] == 99.073
    assert record["assumptions"]["planning"]["physics"]["pit_loss"] == 18
    assert record["exploration"]["model_scope"]["modeled_driver_count"] == 5
    assert record["frontend_source_sha256"] and record["dataset_file_sha256"]
    replay = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "f1_strategy_optimizer.workbench_replay",
            str(out / "decision-export.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(replay.stdout)["status"] == "exact_match"
    page.locator("#outcomes").screenshot(path=str(out / "desktop-revealed.png"))
    page.locator("#pit-loss").fill("20")
    page.locator("#pit-loss").dispatch_event("change")
    expect(page.locator("#export")).to_be_disabled()
    # A different frozen UTC must also clear the revealed observation.
    page.locator("#cutoff").select_option(index=1)
    expect(page.locator("#snapshot-note")).to_contain_text("15:38:00")
    expect(page.locator("#reveal-result")).to_have_text("结果仍未揭晓。")
    page.locator("#driver").select_option("hamilton")
    expect(page.locator("#assumption-json")).to_have_value(re.compile('"ego": "hamilton"'))
    expect(page.locator("#ack")).not_to_be_checked()
    page.locator("#ack").check()
    page.locator("#compare").click()
    page.wait_for_selector("#comparison-content:not(.hidden)", timeout=20_000)
    expect(page.locator("#global-error")).not_to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#comparison").screenshot(path=str(out / "mobile-comparison.png"))
    page.screenshot(path=str(out / "mobile-full.png"), full_page=True)
    widths = page.evaluate("() => ({scroll:document.documentElement.scrollWidth,view:innerWidth})")
    assert widths["scroll"] <= widths["view"], widths
    # Corrupt JSON yields a readable error and cannot reuse the old export.
    page.locator("#advanced").evaluate("el => el.open = true")
    page.locator("#assumption-json").fill("{")
    page.locator("#apply-json").click()
    expect(page.locator("#global-error")).to_contain_text("JSON 无法应用")
    expect(page.locator("#export")).to_be_disabled()
    # Use a separate intentionally tiny-limit server to check a real killed process.
    page.goto(args.timeout_url)
    page.wait_for_selector("#assumed-cars input")
    page.locator("#ack").check()
    page.locator("#compare").click()
    expect(page.locator("#global-error")).to_contain_text("已停止", timeout=10_000)
    expect(page.locator("#export")).to_be_disabled()
    page.screenshot(path=str(out / "timeout-feedback.png"), full_page=True)
    assert errors == [], errors
    metrics = {
        "browser": "headless system Chromium via Playwright",
        "desktop": {"width": 1440, "height": 1000},
        "mobile": {"width": 390, "height": 844},
        "page_ready_seconds": ready_seconds,
        "comparison_wall_seconds": comparison_seconds,
        "backend_status": job_status,
        "mobile_widths": widths,
        "browser_errors": errors,
        "reveal_requested_only_after_comparison": True,
        "driver_and_cutoff_switch_passed": True,
        "stale_export_disabled": True,
        "invalid_json_feedback_passed": True,
        "real_timeout_feedback_passed": True,
        "export_bytes": (out / "decision-export.json").stat().st_size,
    }
    (out / "browser-acceptance.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))
    browser.close()
