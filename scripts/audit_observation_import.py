"""Bounded gating checks on four saved development prefixes, without scoring."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from f1_strategy_optimizer.event_replay import dt, iso, verify_frozen
from f1_strategy_optimizer.observation_import import inspect_import, select_horizon

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("bahrain", "monaco", "british", "italian")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/observation-contract")
    out = parser.parse_args().output
    out.mkdir(exist_ok=False)
    totals, rows, hashes = {}, [], {}
    for event in EVENTS:
        name = "decisions.json.gz" if event == "bahrain" else f"{event}-decisions.json.gz"
        path = ROOT / "output/freshness-development" / name
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        frozen = json.loads(gzip.decompress(path.read_bytes()))
        counts = Counter()
        for decision in frozen:
            verify_frozen(decision)
            cutoff = decision["cutoff"]
            records, streams = [], []
            for car in decision["state"]["cars"]:
                stream = f"development-prefix/lap-state/{car['id']}"
                streams.append(stream)
                start = car["last_started_lap"]
                records.append({
                    "event_id": stream, "stream": stream, "kind": "lap_state",
                    "source": "development-prefix-export-not-live", "session_id": event,
                    "event_time": start.get("event_at"), "received_at": None,
                    "sequence": None, "revision": 0,
                    "payload": {"current_lap": start.get("value")},
                })
            doc = {"schema_version": 1, "session_id": event,
                   "required_streams": streams, "records": records}
            variants = [("missing_receipts", doc, "recorded_receipts", None),
                        ("assumed_3s", doc, "historical_approximation", 3)]
            delayed = json.loads(json.dumps(doc))
            for record in delayed["records"]:
                if record["event_time"]:
                    record["received_at"] = iso(dt(record["event_time"]) + timedelta(seconds=30))
            variants.append(("synthetic_30s_receipts", delayed, "recorded_receipts", None))
            revised = json.loads(json.dumps(delayed))
            for record in list(revised["records"]):
                revised["records"].append({
                    **record, "revision": 1,
                    "received_at": iso(dt(cutoff) + timedelta(seconds=30)),
                    "payload": {"current_lap": 999, "synthetic_late_revision": True},
                })
            variants.append(("synthetic_late_revision", revised, "recorded_receipts", None))
            for label, document, mode, delay in variants:
                report = inspect_import(document, cutoff, mode=mode, assumed_delay_seconds=delay)
                counts[f"{label}:snapshots"] += 1
                counts[f"{label}:visible_streams"] += len(report["snapshot"])
                counts[f"{label}:missing_streams"] += len(report["missing_streams"])
                counts[f"{label}:structural_snapshot_pass"] += report["snapshot_checks_passed"]
                assert all(r["revision"] == 0 for r in report["snapshot"].values())
                assert not report["model_eligible"]
                for stream in streams:
                    # Gate only: original target is a declared synthetic request,
                    # no targets/outcomes/errors from final evaluation are opened.
                    horizon = select_horizon(
                        report, horizon="first_unstarted_after_confirmation",
                        driver_stream=stream, original_target_lap=1)
                    counts[f"{label}:horizon:{horizon['reason']}"] += 1
                    assert horizon["selected_target_lap"] is None
                rows.append({"event": event, "cutoff": cutoff, "scenario": label,
                             "visible": len(report["snapshot"]),
                             "missing": len(report["missing_streams"]),
                             "skew_seconds": report["snapshot_skew_seconds"],
                             "snapshot_checks_passed": report["snapshot_checks_passed"],
                             "diagnostics": report["diagnostics"]})
        totals[event] = dict(counts)
    result = {
        "purpose": "Offline import gating, not forecast accuracy or another model comparison",
        "development_events": list(EVENTS), "input_sha256": hashes,
        "scenarios": "missing receipts; assumed 3s; synthetic 30s receipts; revision after cutoff",
        "synthetic_timing_notice": "Injected receipt times are simulations, never captured live",
        "late_revision_leaks": 0, "immediate_post_pit_unlocks": 0,
        "unproved_horizon_selections": 0,
        "sealed_events_read": [], "network_requests": 0, "totals": totals, "rows": rows,
    }
    (out / "development-gates.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"saved": str(out), "totals": totals}, indent=2))


if __name__ == "__main__":
    main()
