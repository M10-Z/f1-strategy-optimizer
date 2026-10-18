"""Bounded local receipt evidence. No network client or model integration."""

import argparse
import base64
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 10000
MAX_PAYLOAD = 256 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def utc(ns):
    seconds, nanos = divmod(ns, 10**9)
    return datetime.fromtimestamp(seconds, timezone.utc).replace(
        microsecond=nanos // 1000).isoformat()


def system_clock():
    # Adjacent, non-atomic samples, before decoding/validation/disk I/O.
    return time.time_ns(), time.monotonic_ns()


class RawReceiver:
    """One serialized caller per new log. Existing logs are never resumed/rewritten.

    A successful receive returns only after append + fsync. It is local callback
    entry time, not wire arrival or provider publication time. Injected clocks
    are accepted only for explicitly synthetic evidence.
    """

    def __init__(self, path, *, source, session_id, collector_id,
                 input_kind="local_callback", clock_evidence=None, clock=None,
                 max_bytes=MAX_BYTES, max_records=MAX_RECORDS, max_payload=MAX_PAYLOAD,
                 clock_step_threshold_seconds=1):
        for name, value in (("source", source), ("session_id", session_id),
                            ("collector_id", collector_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} requires a nonempty string")
        if input_kind not in {"local_callback", "local_file_input", "synthetic_demo"}:
            raise ValueError("Only local/offline input is implemented")
        if clock is not None and input_kind != "synthetic_demo":
            raise ValueError("Injected clocks require synthetic_demo labeling")
        for value in (max_bytes, max_records, max_payload):
            if type(value) is not int or value <= 0:
                raise ValueError("Limits must be positive integers")
        if (not isinstance(clock_step_threshold_seconds, (int, float))
                or isinstance(clock_step_threshold_seconds, bool)
                or not math.isfinite(clock_step_threshold_seconds)
                or clock_step_threshold_seconds < 0):
            raise ValueError("Clock threshold must be finite and nonnegative")
        evidence = {"source": None, "max_error_seconds": None, "evidence_ref": None,
                    **dict(clock_evidence or {})}
        for name in ("source", "evidence_ref"):
            if evidence.get(name) is not None and (
                    not isinstance(evidence[name], str) or not evidence[name].strip()):
                raise ValueError(f"Clock {name} must be null or a nonempty string")
        error = evidence.get("max_error_seconds")
        if error is not None and (isinstance(error, bool) or not isinstance(error, (int, float))
                                  or not math.isfinite(error) or error < 0):
            raise ValueError("Clock error must be null or finite and nonnegative")
        evidence["status"] = ("declared_not_verified" if evidence.get("source")
                              and evidence.get("evidence_ref") and error is not None else "unknown")
        canonical(evidence)
        self.path = Path(path)
        self.receipt_path = self.path.with_name(self.path.name + ".receipt.json")
        if self.receipt_path.exists():
            raise FileExistsError(self.receipt_path)
        self._clock = clock or system_clock
        self.source, self.session_id = source, session_id
        self.run_id = uuid.uuid4().hex
        self._limits = (max_bytes, max_records, max_payload)
        self._step_ns = clock_step_threshold_seconds * 10**9
        self._last_clock = None
        self._tainted = False
        self._mono_tainted = False
        self._state = "unknown"
        self._gap_start = None
        self._coverage_gap = False
        self._last_hash = None
        self._count = self._bytes = 0
        self._file_hash = hashlib.sha256()
        self._failed = None
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self._file = os.fdopen(fd, "wb", buffering=0)
        try:
            self._append(self._clock(), "capture_start", {
                "collector_id": collector_id, "input_kind": input_kind,
                "clock_evidence": evidence, "limits": {
                    "max_bytes": max_bytes, "max_records": max_records, "max_payload": max_payload},
                "clock_step_threshold_seconds": clock_step_threshold_seconds,
                "sampling": ("injected synthetic UTC/monotonic pair" if clock is not None
                             else "UTC time.time_ns then monotonic_ns; adjacent, not atomic"),
                "publication_time_verified": False, "live_connection_verified": False,
            })
        except BaseException:
            self._file.close()
            raise

    def _append(self, sample, kind, fields):
        if self._closed or self._failed:
            raise ValueError("Receiver closed/failed; preserve log and start a new file")
        wall, mono = sample
        if type(wall) is not int or type(mono) is not int or mono < 0:
            raise ValueError("Clock samples require integer nanoseconds")
        warnings, skew = [], None
        if self._last_clock:
            dw, dm = wall - self._last_clock[0], mono - self._last_clock[1]
            skew = dw - dm
            if dw < 0:
                warnings.append("wall_clock_rollback")
            if dm < 0:
                warnings.append("monotonic_regression")
            if abs(skew) > self._step_ns:
                warnings.append("wall_monotonic_divergence")
        tainted = self._tainted or bool(warnings)
        row = {"schema_version": 1, "run_id": self.run_id, "index": self._count,
               "type": kind, "source": self.source, "session_id": self.session_id,
               "received_at": utc(wall), "utc_unix_ns": wall, "monotonic_ns": mono,
               "clock_warnings": warnings, "utc_tainted": tainted,
               "monotonic_tainted": self._mono_tainted or "monotonic_regression" in warnings,
               "wall_minus_monotonic_delta_ns": skew, "previous_sha256": self._last_hash,
               **fields}
        row["record_sha256"] = digest(row)
        line = canonical(row) + b"\n"
        if self._count >= self._limits[1] or self._bytes + len(line) > self._limits[0]:
            self._failed = "limit_reached"
            raise ValueError("Capture limit reached; stop input and rotate to a NEW log")
        try:
            offset = 0
            while offset < len(line):
                written = self._file.write(line[offset:])
                if not written:
                    raise OSError("Zero-byte append")
                offset += written
            os.fsync(self._file.fileno())
        except OSError:
            self._failed = "io_error"
            raise
        self._file_hash.update(line)
        self._bytes += len(line)
        self._count += 1
        self._last_hash = row["record_sha256"]
        self._last_clock, self._tainted = (wall, mono), tainted
        self._mono_tainted = row["monotonic_tainted"]
        return row

    def receive(self, raw_payload, *, stream, source_sequence=None, revision_key=None,
                event_key=None):
        sample = self._clock()  # First operation; before even payload/type validation.
        if not isinstance(raw_payload, (bytes, str)):
            raise ValueError("Pass original bytes or text, not a reconstructed Python object")
        raw = raw_payload.encode("utf-8") if isinstance(raw_payload, str) else raw_payload
        if len(raw) > self._limits[2]:
            self._failed = "payload_limit_reached"
            raise ValueError("Payload limit reached; raw payload was NOT saved")
        if not isinstance(stream, str) or not stream:
            raise ValueError("stream requires a nonempty string")
        # Top-level key hints are optional; failure to parse never discards bytes.
        try:
            obj = json.loads(raw)
            canonical(obj)  # Nonstandard NaN/Infinity is not a usable key hint.
        except (ValueError, UnicodeDecodeError):
            obj = None
        hints = obj if isinstance(obj, dict) else {}
        return self._append(sample, "message", {
            "stream": stream, "raw_base64": base64.b64encode(raw).decode("ascii"),
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
            "source_sequence": source_sequence if source_sequence is not None else hints.get("_id"),
            "source_object_key": hints.get("_key"),
            "source_revision_key": revision_key if revision_key is not None
                                   else hints.get("revision"),
            "event_key": event_key if event_key is not None else hints.get("event_id"),
            "connection_state": self._state, "coverage_gap_seen": self._coverage_gap,
        })

    def connection(self, status, *, reason=None):
        sample = self._clock()
        if status not in {"connected", "disconnected"}:
            raise ValueError("Connection status must be connected or disconnected")
        gap = None
        if status == "connected" and self._gap_start is not None:
            delta = sample[1] - self._gap_start["monotonic_ns"]
            duration_ok = (delta >= 0 and not self._mono_tainted
                           and sample[1] >= self._last_clock[1])
            gap = {"from_index": self._gap_start["index"],
                   "monotonic_duration_ns": delta if duration_ok else None,
                   "lost_message_count": None, "coverage": "unknown"}
        row = self._append(sample, "connection", {
            "connection_state": status, "reason": reason, "closed_gap": gap,
            "coverage_gap_seen": self._coverage_gap or status == "disconnected",
        })
        if status == "disconnected":
            self._coverage_gap = True
            if self._gap_start is None:
                self._gap_start = row
        elif gap is not None:
            self._gap_start = None
        self._state = status
        return row

    def close(self):
        if self._closed:
            return
        self._file.close()
        self._closed = True
        receipt = {"schema_version": 1, "run_id": self.run_id, "records": self._count,
                   "bytes": self._bytes, "terminal_sha256": self._last_hash,
                   "file_sha256": self._file_hash.hexdigest(),
                   "status": self._failed or "closed", "utc_tainted": self._tainted,
                   "connection_state": self._state, "coverage_gap_seen": self._coverage_gap}
        fd = os.open(self.receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(receipt) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def replay_log(path, *, max_bytes=MAX_BYTES, max_records=MAX_RECORDS):
    """Verify complete bytes and chain before returning any records. No timestamping."""
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("Replay byte limit exceeded")
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Replay byte limit exceeded")
    if not data or not data.endswith(b"\n"):
        raise ValueError("Empty or torn log; no automatic repair")
    rows, previous = [], None
    for line in data.splitlines():
        if len(rows) >= max_records:
            raise ValueError("Replay record limit exceeded")
        row = json.loads(line)
        saved = row.pop("record_sha256")
        if (digest(row) != saved or row["previous_sha256"] != previous
                or row["index"] != len(rows)):
            raise ValueError("Record hash/order mismatch")
        row["record_sha256"] = saved
        if rows and (row["run_id"], row["source"], row["session_id"]) != (
                rows[0]["run_id"], rows[0]["source"], rows[0]["session_id"]):
            raise ValueError("Mixed capture identity")
        if row["type"] == "message":
            raw = base64.b64decode(row["raw_base64"], validate=True)
            if len(raw) != row["raw_bytes"] or hashlib.sha256(raw).hexdigest() != row["raw_sha256"]:
                raise ValueError("Raw payload hash mismatch")
        previous = saved
        rows.append(row)
    if rows[0]["type"] != "capture_start":
        raise ValueError("Missing capture header")
    receipt = json.loads(path.with_name(path.name + ".receipt.json").read_text())
    if (receipt["file_sha256"] != hashlib.sha256(data).hexdigest()
            or receipt["terminal_sha256"] != previous or receipt["records"] != len(rows)
            or receipt["bytes"] != len(data) or receipt["run_id"] != rows[0]["run_id"]):
        raise ValueError("Terminal receipt mismatch; truncated/replaced log")
    if receipt["status"] == "io_error":
        raise ValueError("Capture I/O failed; preserve raw evidence for inspection")
    return rows


def to_envelope(path, *, required_streams, binding=None):
    """Explicit normalized-JSON local adapter; arbitrary FastF1 lists stay raw.

    Unknown UTC accuracy or any detected clock anomaly quarantines receipt times.
    Connection gaps keep a required coverage stream unknown after reconnect.
    Nothing here enables a model, a horizon, or a live feed.
    """
    rows = replay_log(path)
    header = rows[0]
    clock_unknown = header["clock_evidence"]["status"] == "unknown"
    tainted = any(r["utc_tainted"] for r in rows)
    health = f"{header['source']}:local_connection_coverage"
    error = header["clock_evidence"].get("max_error_seconds")
    error_field = {"received_at_uncertainty_seconds": error} if error is not None else {}
    if health in required_streams:
        raise ValueError("Reserved connection coverage stream")
    records, rejected = [], []
    for row in rows[1:]:
        allowed = not clock_unknown and not tainted
        received = row["received_at"] if allowed else None
        capture = {"run_id": row["run_id"], "index": row["index"],
                   "monotonic_ns": row["monotonic_ns"], "local_received_at": row["received_at"],
                   "clock_evidence": header["clock_evidence"], "utc_tainted_run": tainted,
                   "input_kind": header["input_kind"], "publication_time_verified": False}
        if row["type"] == "message":
            try:
                obj = json.loads(base64.b64decode(row["raw_base64"]))
                canonical(obj)
                if not isinstance(obj, dict) or not all(k in obj for k in (
                        "event_id", "kind", "event_time", "payload")):
                    raise ValueError("No explicit normalized message schema")
                records.append({"event_id": obj["event_id"], "kind": obj["kind"],
                                "event_time": obj["event_time"], "payload": obj["payload"],
                                "revision": obj.get("revision"), "sequence": None,
                                "source_message_id": row["source_sequence"],
                                "source_revision_key": row["source_revision_key"],
                                "source_object_key": row["source_object_key"],
                                "source": row["source"], "stream": row["stream"],
                                "session_id": row["session_id"], "received_at": (
                                    received if row["connection_state"] == "connected" else None),
                                **error_field,
                                "capture": capture})
            except (ValueError, UnicodeDecodeError):
                rejected.append({"index": row["index"], "reason": "opaque_or_unsupported_payload"})
        if row["type"] in {"message", "connection"}:
            continuous = row["connection_state"] == "connected" and not row["coverage_gap_seen"]
            records.append({"event_id": f"coverage:{row['index']}", "kind": "connection_coverage",
                            "source": row["source"], "stream": health,
                            "session_id": row["session_id"], "event_time": row["received_at"],
                            "received_at": received, "revision": 0, "sequence": None,
                            **error_field,
                            "payload": {"local_continuity_only": True} if continuous else None,
                            "capture": capture})
    result = {"schema_version": 1, "session_id": header["session_id"],
              "required_streams": [*required_streams, health], "sequence_semantics": "unknown",
              "records": records, "clock_accuracy": header["clock_evidence"],
              "utc_tainted_run": tainted, "rejected_payloads": rejected,
              "label": "LOCAL_RECEIPT_EVIDENCE_NOT_VERIFIED_LIVE",
              "input_kind": header["input_kind"], "model_eligible": False,
              "data_kind": ("synthetic_fixture" if header["input_kind"] == "synthetic_demo"
                            else "local_receipt_evidence"),
              "source_publication_time": None}
    if binding:
        if set(binding) - {"decision_sha256", "driver_id", "original_immediate_target_lap"}:
            raise ValueError("Binding cannot overwrite capture/session/clock metadata")
        result.update(binding)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record-local")
    record.add_argument("input", type=Path)
    record.add_argument("--log", required=True, type=Path)
    for name in ("source", "session-id", "collector-id", "stream"):
        record.add_argument("--" + name, required=True)
    record.add_argument("--clock-evidence", type=Path)
    replay = sub.add_parser("replay")
    replay.add_argument("log", type=Path)
    export = sub.add_parser("export-envelope")
    export.add_argument("log", type=Path)
    export.add_argument("--required-stream", action="append", required=True)
    export.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "record-local":
        evidence = json.loads(args.clock_evidence.read_text()) if args.clock_evidence else None
        with RawReceiver(args.log, source=args.source, session_id=args.session_id,
                         collector_id=args.collector_id, input_kind="local_file_input",
                         clock_evidence=evidence) as receiver:
            receiver.connection("connected", reason="local file adapter opened; not a network feed")
            with args.input.open("rb") as handle:
                while line := handle.readline(MAX_PAYLOAD + 1):
                    receiver.receive(line, stream=args.stream)
            receiver.connection("disconnected", reason="local file EOF; not a network disconnect")
        print(json.dumps({"log": str(args.log), "input_kind": "local_file_input"}))
    elif args.command == "replay":
        rows = replay_log(args.log)
        print(json.dumps({"records": len(rows), "terminal_sha256": rows[-1]["record_sha256"],
                          "utc_tainted": any(r["utc_tainted"] for r in rows)}))
    else:
        envelope = to_envelope(args.log, required_streams=args.required_stream)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as handle:
            json.dump(envelope, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({"output": str(args.output), "label": envelope["label"]}))


if __name__ == "__main__":
    main()
