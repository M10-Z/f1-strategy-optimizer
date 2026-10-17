"""Real browser choices, synthetic delayed revisions, and downloaded offline replay."""

import argparse
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8780")
    parser.add_argument("--output", type=Path, default=Path("output/horizon-browser"))
    parser.add_argument("--replay-python", default=".venv/bin/python")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
        errors, requests = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(args.url)
        expect(page.locator("#export-horizon")).to_be_enabled()
        expect(page.locator("#horizon-choice")).to_have_value("immediate_post_pit")
        options = page.locator("#cutoff option").evaluate_all("xs=>xs.map(x=>x.value)")
        page.locator("#cutoff").select_option(options[-1])
        expect(page.locator("#snapshot-note")).to_contain_text("16:13:00")
        expect(page.locator("#horizon-status")).to_contain_text("原即时目标不可用")

        def export(name, button="export-horizon"):
            with page.expect_download() as download:
                page.locator("#" + button).click()
            path = args.output / (name + ".json")
            download.value.save_as(str(path))
            replay = subprocess.run(
                [args.replay_python, "-m", "f1_strategy_optimizer.workbench_replay", str(path)],
                check=True, text=True, capture_output=True)
            results[name] = json.loads(replay.stdout)
            assert results[name]["status"] == "exact_match"
            return json.loads(path.read_text())

        exact = export("cached-immediate")
        original = exact["horizon_report"]["selection"]["original_immediate_target_lap"]
        assert original is not None
        page.locator("#horizon-choice").select_option("first_unstarted_after_confirmation")
        expect(page.locator("#horizon-status")).to_contain_text("尚未开始边界")
        later = export("cached-later")
        assert later["horizon_report"]["selection"]["original_immediate_target_lap"] == original
        assert later["horizon_report"]["selection"]["selected_target_lap"] is None
        assert later["horizon_report"]["selection"]["availability_label"] == (
            "retrospective assumed availability")
        page.locator("#availability-mode").select_option("recorded_receipts")
        expect(page.locator("#horizon-status")).to_contain_text("没有可见圈状态")
        missing = export("cached-receipts-missing")
        assert missing["horizon_report"]["availability"]["snapshot"] == {}

        frozen = later["frozen_decision"]
        cutoff = datetime.fromisoformat(frozen["cutoff"])
        car = next(c for c in frozen["state"]["cars"] if c["id"] == "leclerc")
        stream = "driver:leclerc:lap_state"
        row = {"event_id": "synthetic-lap-state", "stream": stream, "kind": "lap_state",
               "source": "synthetic-receipt-fixture", "session_id": "7953",
               "event_time": (cutoff - timedelta(seconds=1)).isoformat(),
               "received_at": cutoff.isoformat(), "sequence": 1, "revision": 0,
               "payload": {"current_lap": car["last_started_lap"]["value"]}}
        envelope = {
            "schema_version": 1, "session_id": "7953", "driver_id": "leclerc",
            "decision_sha256": frozen["decision_sha256"], "data_kind": "synthetic_fixture",
            "original_immediate_target_lap": original, "required_streams": [stream],
            "records": [row, {**row, "revision": 1, "sequence": 2,
                              "received_at": (cutoff + timedelta(seconds=30)).isoformat(),
                              "payload": {"current_lap": 999}}],
        }
        fixture = args.output / "synthetic-delayed-revision-input.json"
        fixture.write_text(json.dumps(envelope, indent=2))
        page.locator("#horizon-file").set_input_files(str(fixture))
        expect(page.locator("#horizon-import-label")).to_contain_text("合成延迟/修订")
        delayed = export("synthetic-delayed-revision")
        snapshot = delayed["horizon_report"]["availability"]["snapshot"]
        assert snapshot[stream]["revision"] == 0
        assert snapshot[stream]["payload"]["current_lap"] != 999
        assert not delayed["horizon_report"]["prediction_enabled"]
        assert len(delayed["horizon_report"]["availability"]["records"]) == 2

        # Invalid import blocks export, then restoring the archive recovers it.
        bad = args.output / "wrong-binding-input.json"
        bad.write_text(json.dumps(envelope | {"driver_id": "hamilton"}))
        page.locator("#horizon-file").set_input_files(str(bad))
        expect(page.locator("#horizon-status")).to_contain_text("不匹配")
        expect(page.locator("#export-horizon")).to_be_disabled()
        page.locator("#clear-horizon-file").click()
        expect(page.locator("#horizon-import-label")).to_contain_text("当前冻结归档")
        expect(page.locator("#horizon-status")).to_contain_text("没有可见圈状态")
        page.locator("#availability-mode").select_option("historical_approximation")
        expect(page.locator("#horizon-clock")).to_contain_text("retrospective assumed availability")

        # Existing simulation stays independent, yet its export records this horizon.
        page.locator("#cutoff").select_option(options[0])
        expect(page.locator("#snapshot-note")).to_contain_text("15:18:00")
        expect(page.locator("#ack")).to_be_enabled()
        page.locator("#ack").check()
        page.locator("#compare").click()
        expect(page.locator("#export")).to_be_enabled(timeout=20000)
        simulation = export("simulation-with-selected-horizon", "export")
        assert simulation["horizon_report"]["selection"]["requested_horizon"] == (
            "first_unstarted_after_confirmation")
        assert simulation["reveal"] is None
        assert not any("/api/reveal" in r for r in requests)
        page.set_viewport_size({"width": 390, "height": 844})
        widths = page.evaluate(
            "()=>({scroll:document.documentElement.scrollWidth,view:innerWidth})")
        assert widths["scroll"] == widths["view"] == 390
        assert not errors, errors
        results.update(browser_errors=errors, mobile_widths=widths,
                       independent_horizons=True, missing_boundary_blocks=True,
                       late_revision_leaks=0, imported_identity_mismatch_blocked=True,
                       reveal_requests=0, precision_experiments=0)
        (args.output / "acceptance.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
