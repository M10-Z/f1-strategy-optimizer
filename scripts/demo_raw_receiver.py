"""Local, deterministic clock scenarios. Never opens a network connection."""

import argparse
import json
from pathlib import Path

from f1_strategy_optimizer.observation_import import inspect_import
from f1_strategy_optimizer.raw_receiver import RawReceiver, digest, replay_log, to_envelope, utc

BASE = 1792281600 * 10**9
EVIDENCE = {"source": "synthetic-controlled-clock", "max_error_seconds": 0.25,
            "evidence_ref": "demo-only-not-external-clock-verification"}


class SyntheticClock:
    def __init__(self, rollback=False):
        self.index = 0
        self.rollback = rollback

    def __call__(self):
        n = self.index
        self.index += 1
        offset = -10 * 10**9 if self.rollback and n >= 3 else 0
        return BASE + n * 10**9 + offset, n * 10**9


def payload(event="state", revision=0, event_seconds=1, lap=4):
    return json.dumps({"event_id": event, "revision": revision, "_id": 100 + revision,
                       "_key": event, "event_time": utc(BASE + int(event_seconds * 10**9)),
                       "kind": "lap_state", "payload": {"current_lap": lap}}).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/raw-receiver-demo-20261018"))
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    summary = {}
    for scenario in ("out_of_order_delayed_revision", "disconnect_reconnect",
                     "system_clock_rollback", "unknown_clock"):
        path = out / (scenario + ".jsonl")
        with RawReceiver(path, source="synthetic-local-source", session_id="synthetic-session",
                         collector_id="offline-demo", input_kind="synthetic_demo",
                         clock=SyntheticClock(rollback=scenario == "system_clock_rollback"),
                         clock_evidence=None if scenario == "unknown_clock" else EVIDENCE) as log:
            log.connection("connected", reason="synthetic callback only")
            log.receive(payload(), stream="laps")
            if scenario == "out_of_order_delayed_revision":
                log.receive(payload(event="older-event", event_seconds=0.5), stream="laps")
                log.receive(payload(revision=1, lap=5), stream="laps")
            else:
                log.connection("disconnected", reason="synthetic gap; no transport was opened")
                log.connection("connected", reason="synthetic reconnect")
                log.receive(payload(event="after-gap", event_seconds=4, lap=5), stream="laps")
        rows = replay_log(path)
        assert digest(rows) == digest(replay_log(path))
        envelope = to_envelope(path, required_streams=["laps"])
        (out / (scenario + "-envelope.json")).write_text(json.dumps(envelope, indent=2) + "\n")
        gates = {}
        for second in (2.1, 2.5, 4.5, 8):
            report = inspect_import(envelope, utc(BASE + int(second * 10**9)))
            gates[str(second)] = {
                "snapshot_checks_passed": report["snapshot_checks_passed"],
                "missing_streams": report["missing_streams"],
                "null_payload_streams": report["null_payload_streams"],
                "revision": report["snapshot"].get("laps", {}).get("revision"),
                "model_eligible": report["model_eligible"],
            }
            assert not report["model_eligible"] and not report["immediate_post_pit_target_enabled"]
        if scenario == "out_of_order_delayed_revision":
            assert gates["2.1"]["revision"] is None
            assert gates["2.5"]["revision"] == 0 and gates["4.5"]["revision"] == 1
        if scenario in {"unknown_clock", "system_clock_rollback"}:
            assert all(r["received_at"] is None for r in envelope["records"])
        gaps = [r["closed_gap"] for r in rows if r.get("closed_gap")]
        if gaps:
            assert gaps[0]["monotonic_duration_ns"] == 10**9
            assert gaps[0]["lost_message_count"] is None
        summary[scenario] = {
            "records": len(rows), "raw_replay_exact_match": True,
            "terminal_sha256": rows[-1]["record_sha256"], "gates": gates,
            "utc_tainted": envelope["utc_tainted_run"], "gaps": gaps,
        }
    result = {"label": "SYNTHETIC_LOCAL_DEMO_NOT_A_LIVE_FEED_TEST", "scenarios": summary,
              "network_connections": 0, "historical_receipts_reconstructed": False,
              "models_or_holdouts_run": False}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(out), "scenarios": list(summary),
                      "all_raw_replays_exact": True, "network_connections": 0}, indent=2))


if __name__ == "__main__":
    main()
