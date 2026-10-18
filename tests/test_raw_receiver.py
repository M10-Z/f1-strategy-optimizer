"""Synthetic receipt evidence, not a test of any live service."""

import base64
import json
import time

import pytest

from f1_strategy_optimizer import raw_receiver as receiver
from f1_strategy_optimizer.observation_import import inspect_import

BASE = 1792281600 * 10**9  # 2026-10-18 UTC, synthetic fixture epoch.
EVIDENCE = {
    "source": "synthetic-clock",
    "max_error_seconds": 0,
    "evidence_ref": "test-fixture-only-not-real-clock-validation",
}


class Clock:
    def __init__(self, offsets=None):
        self.count = 0
        self.offsets = offsets or {}

    def __call__(self):
        n = self.count
        self.count += 1
        return BASE + n * 10**9 + self.offsets.get(n, 0), n * 10**9


def logger(path, **kwargs):
    return receiver.RawReceiver(
        path,
        source="synthetic-source",
        session_id="demo",
        collector_id="test-collector",
        input_kind="synthetic_demo",
        clock=kwargs.pop("clock", Clock()),
        **kwargs,
    )


def message(event="state", revision=0, seconds=1, **extra):
    return json.dumps(
        {
            "event_id": event,
            "revision": revision,
            "kind": "lap_state",
            "event_time": receiver.utc(BASE + seconds * 10**9),
            "payload": {"current_lap": 4},
            "_id": 200 + revision,
            "_key": event,
            **extra,
        }
    ).encode()


def gate(path, seconds=20):
    envelope = receiver.to_envelope(path, required_streams=["laps"])
    return envelope, inspect_import(envelope, receiver.utc(BASE + seconds * 10**9))


def test_entry_stamp_precedes_decode_and_original_bytes_survive(tmp_path, monkeypatch):
    path = tmp_path / "raw.jsonl"
    clock = Clock()
    original = receiver.json.loads
    with logger(path, clock=clock) as log:

        def check_decode(value):
            assert clock.count == 2  # Header, then receive entry sampled BEFORE decode.
            return original(value)

        monkeypatch.setattr(receiver.json, "loads", check_decode)
        raw = message() + b"\n"
        row = log.receive(raw, stream="laps")
        assert row["utc_unix_ns"] == BASE + 10**9
        assert row["source_sequence"] == 200
        assert row["source_object_key"] == "state"
        assert row["source_revision_key"] == 0
        monkeypatch.setattr(receiver.json, "loads", original)
        opaque = log.receive(b"\xff\x00\n", stream="laps")
        assert base64.b64decode(opaque["raw_base64"]) == b"\xff\x00\n"
    rows = receiver.replay_log(path)
    assert base64.b64decode(rows[1]["raw_base64"]) == raw
    assert rows[0]["clock_evidence"]["status"] == "unknown"
    assert not rows[0]["publication_time_verified"]
    envelope, report = gate(path)
    assert envelope["rejected_payloads"][0]["index"] == 2
    assert not report["snapshot_checks_passed"]
    assert all(r["received_at"] is None for r in envelope["records"])


def test_real_system_clock_records_only_this_local_call_not_historical_receipt(tmp_path):
    path = tmp_path / "system.jsonl"
    with receiver.RawReceiver(
        path, source="local", session_id="s", collector_id="local-test"
    ) as log:
        before = time.time_ns()
        row = log.receive(b"old archive content", stream="raw")
        after = time.time_ns()
    assert before <= row["utc_unix_ns"] <= after
    assert row["monotonic_ns"] > 0
    assert receiver.replay_log(path)[0]["input_kind"] == "local_callback"


def test_older_out_of_order_revision_cannot_replace_newer_or_leak_before_receipt(tmp_path):
    path = tmp_path / "revisions.jsonl"
    with logger(path, clock_evidence=EVIDENCE) as log:
        log.connection("connected")
        log.receive(message(revision=1), stream="laps")  # received at second 2
        log.receive(message(revision=0, payload={"current_lap": 3}), stream="laps")
    envelope, before = gate(path, seconds=1)
    assert "laps" in before["missing_streams"]
    _, after = gate(path, seconds=3)
    assert after["snapshot"]["laps"]["revision"] == 1
    assert after["snapshot"]["laps"]["payload"]["current_lap"] == 4
    assert envelope["sequence_semantics"] == "unknown"  # _id is NOT assumed contiguous.
    assert not after["model_eligible"]


def test_disconnect_gap_uses_monotonic_duration_and_reconnect_does_not_restore_coverage(tmp_path):
    path = tmp_path / "gap.jsonl"
    with logger(path, clock_evidence=EVIDENCE) as log:
        log.connection("connected")
        log.receive(message(), stream="laps")
        log.connection("disconnected", reason="synthetic transport drop")
        log.receive(message(event="queued"), stream="laps")
        connected = log.connection("connected", reason="synthetic reconnect")
        log.receive(message(event="after-gap"), stream="laps")
    assert connected["closed_gap"]["monotonic_duration_ns"] == 2 * 10**9
    assert connected["closed_gap"]["lost_message_count"] is None
    _, before = gate(path, seconds=2)
    assert before["snapshot_checks_passed"]
    _, after = gate(path, seconds=6)
    assert not after["snapshot_checks_passed"]
    assert "synthetic-source:local_connection_coverage" in after["null_payload_streams"]


@pytest.mark.parametrize(
    "offset,warning",
    [(-10 * 10**9, "wall_clock_rollback"), (10 * 10**9, "wall_monotonic_divergence")],
)
def test_utc_clock_step_preserved_raw_and_entire_calendar_time_adapter_quarantined(
    tmp_path, offset, warning
):
    path = tmp_path / "clock.jsonl"
    with logger(path, clock=Clock({3: offset}), clock_evidence=EVIDENCE) as log:
        log.connection("connected")
        log.receive(message(), stream="laps")
        row = log.receive(message(event="step"), stream="laps")
    assert warning in row["clock_warnings"] and row["utc_tainted"]
    rows = receiver.replay_log(path)
    assert rows[-1]["utc_unix_ns"] == BASE + 3 * 10**9 + offset  # Never clamped/corrected.
    envelope, report = gate(path)
    assert envelope["utc_tainted_run"]
    assert report["snapshot"] == {}
    assert all(r["received_at"] is None for r in envelope["records"])


def test_monotonic_regression_is_flagged_and_replay_never_resamples(tmp_path, monkeypatch):
    path = tmp_path / "mono.jsonl"
    samples = iter([(BASE, 10), (BASE + 10**9, 9)])
    with logger(path, clock=lambda: next(samples)) as log:
        row = log.receive(b"x", stream="raw")
    assert "monotonic_regression" in row["clock_warnings"]
    monkeypatch.setattr(receiver, "system_clock", lambda: pytest.fail("Replay sampled clock"))
    assert receiver.replay_log(path)[-1]["monotonic_ns"] == 9


def test_limits_existing_logs_and_torn_or_truncated_evidence_fail_explicitly(tmp_path):
    path = tmp_path / "limit.jsonl"
    with logger(path, max_records=2) as log:
        log.receive(b"first", stream="raw")
        with pytest.raises(ValueError, match="limit reached"):
            log.receive(b"not stored", stream="raw")
    assert len(receiver.replay_log(path)) == 2
    with pytest.raises(FileExistsError):
        logger(path)
    data = path.read_bytes()
    path.write_bytes(data[:-1])  # Test-only external corruption, never writer behavior.
    with pytest.raises(ValueError, match="torn"):
        receiver.replay_log(path)
    path.write_bytes(data.splitlines(keepends=True)[0])
    with pytest.raises(ValueError, match="receipt mismatch"):
        receiver.replay_log(path)


def test_payload_size_failure_does_not_silently_claim_raw_was_saved(tmp_path):
    path = tmp_path / "payload.jsonl"
    with logger(path, max_payload=1) as log:
        with pytest.raises(ValueError, match="NOT saved"):
            log.receive(b"too large", stream="raw")
    assert len(receiver.replay_log(path)) == 1
    assert json.loads(path.with_name(path.name + ".receipt.json").read_text())["status"] == (
        "payload_limit_reached"
    )


def test_capture_clock_injection_cannot_masquerade_as_system_input(tmp_path):
    with pytest.raises(ValueError, match="synthetic_demo"):
        receiver.RawReceiver(
            tmp_path / "x", source="x", session_id="s", collector_id="c", clock=Clock()
        )


def test_declared_clock_error_delays_availability_without_rewriting_receipt(tmp_path):
    path = tmp_path / "uncertain.jsonl"
    with logger(path, clock_evidence=EVIDENCE | {"max_error_seconds": 2}) as log:
        log.connection("connected")
        row = log.receive(message(), stream="laps")
    envelope, early = gate(path, seconds=3)
    assert "laps" in early["missing_streams"]
    _, later = gate(path, seconds=4)
    record = later["snapshot"]["laps"]
    assert record["received_at"] == row["received_at"]
    assert record["available_at"] == receiver.utc(BASE + 4 * 10**9)
    assert "declared_clock_bound" in record["availability_basis"]
    assert envelope["clock_accuracy"]["status"] == "declared_not_verified"


def test_nan_payload_preserved_opaque_and_fsync_failure_cannot_be_replayed_as_success(
    tmp_path, monkeypatch
):
    path = tmp_path / "nan.jsonl"
    with logger(path) as log:
        log.receive(b'{"_id":NaN}', stream="raw")
    assert base64.b64decode(receiver.replay_log(path)[1]["raw_base64"]) == b'{"_id":NaN}'
    path = tmp_path / "io.jsonl"
    log = logger(path)
    original = receiver.os.fsync

    def fail(_fd):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(receiver.os, "fsync", fail)
    with pytest.raises(OSError, match="storage failure"):
        log.receive(b"written but durability unknown", stream="raw")
    monkeypatch.setattr(receiver.os, "fsync", original)
    log.close()
    with pytest.raises(ValueError):
        receiver.replay_log(path)
