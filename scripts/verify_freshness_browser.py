"""Real cached stable, transition and stale cases; download/replay boundary."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8771")
parser.add_argument("--output", type=Path, default=Path("output/freshness-acceptance"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
    errors = []
    requests = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: requests.append(r.url))
    started = time.monotonic()
    page.goto(args.url)
    page.wait_for_selector("#quality-table tr")
    expect(page.locator("#ack")).to_be_enabled()
    ready = time.monotonic() - started
    assert page.locator("#quality-table tr").count() == 5
    expect(page.locator("#segment-forecast")).not_to_have_text("暂不预测")
    expect(page.locator("#quality-table")).to_contain_text("过期：降级为未知")
    page.locator("#observed").screenshot(path=str(args.output / "stable-prefix.png"))
    page.locator("#ack").check()
    page.locator("#compare").click()
    page.wait_for_selector("#comparison-content:not(.hidden)", timeout=20000)
    assert not any("/api/reveal" in r for r in requests)
    with page.expect_download() as download:
        page.locator("#export").click()
    file = args.output / "freshness-decision.json"
    download.value.save_as(str(file))
    replay = subprocess.run(
        [".venv/bin/python", "-m", "f1_strategy_optimizer.workbench_replay", str(file)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(replay.stdout)["status"] == "exact_match"
    page.locator("#race").select_option("british-2024")
    expect(page.locator("#ack")).to_be_enabled()
    options = page.locator("#cutoff option").evaluate_all(
        "xs=>xs.map(x=>({value:x.value,text:x.textContent}))"
    )

    def select_time(time_text):
        value = next(o["value"] for o in options if time_text in o["text"])
        page.locator("#cutoff").select_option(value)
        expect(page.locator("#snapshot-note")).to_contain_text(time_text)
        expect(page.locator("#ack")).to_be_enabled()
        expect(page.locator("#driver")).to_have_value("leclerc")

    select_time("14:35:00")
    expect(page.locator("#segment-note")).to_contain_text("转换后不足三圈")
    expect(page.get_by_label("leclerc base_lap_time", exact=True)).to_have_value("")
    page.locator("#ack").check()
    page.locator("#compare").click()
    expect(page.locator("#global-error")).to_contain_text("缺少", timeout=10000)
    expect(page.locator("#export")).to_be_disabled()
    page.locator("#observed").screenshot(path=str(args.output / "rain-transition.png"))
    select_time("15:35:00")
    expect(page.locator("#segment-note")).to_contain_text("陈旧")
    expect(page.locator("#quality-table")).to_contain_text("过期：降级为未知")
    assert not any("/api/reveal" in r for r in requests)
    page.locator("#reveal").click()
    expect(page.locator("#reveal-result")).to_contain_text("赛后不适用")
    page.locator("#observed").screenshot(path=str(args.output / "stale-post-event.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#observed").screenshot(path=str(args.output / "mobile-quality.png"))
    widths = page.evaluate("()=>({scroll:document.documentElement.scrollWidth,view:innerWidth})")
    assert widths["scroll"] == widths["view"] == 390
    assert not errors, errors
    result = {
        "page_ready_seconds": ready,
        "browser_errors": errors,
        "quality_rows": 5,
        "transition_abstention_blocks_automatic_pace": True,
        "stale_evidence_abstains": True,
        "post_event_only_on_reveal": True,
        "actual_download_offline_replay": "exact_match",
        "mobile_widths": widths,
    }
    (args.output / "browser.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    browser.close()
