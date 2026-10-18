"""Browser horizon staging over frozen prefixes or explicitly unverified imports."""

import hashlib
from copy import deepcopy
from pathlib import Path

from .event_replay import digest, verify_frozen
from .observation_import import inspect_import, select_horizon


def source_manifest():
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("workbench_horizon.py", "observation_import.py")
    }


def build_horizon_report(frozen, driver, request=None):
    verify_frozen(frozen)
    request = deepcopy(request or {})
    horizon = request.get("horizon", "immediate_post_pit")
    if horizon not in {"immediate_post_pit", "first_unstarted_after_confirmation"}:
        raise ValueError("未知 horizon；必须显式选择原即时目标或确认后的完整圈")
    mode = request.get("mode", "historical_approximation")
    delay = request.get("assumed_delay_seconds", 3) if mode == "historical_approximation" else None
    car = next(c for c in frozen["state"]["cars"] if c["id"] == driver)
    stream = f"driver:{driver}:lap_state"
    outlaps = [x for x in car["completed_lap_history"] if x["is_pit_out_lap"] is True]
    original = outlaps[-1]["lap_number"] + 1 if outlaps else None
    envelope = request.get("envelope")
    imported = envelope is not None
    if imported:
        if not isinstance(envelope, dict):
            raise ValueError("导入消息必须是 JSON 对象")
        if (
            envelope.get("decision_sha256") != frozen["decision_sha256"]
            or envelope.get("driver_id") != driver
            or envelope.get("session_id") != str(frozen["state"]["session"]["session_key"])
        ):
            raise ValueError("导入消息与当前冻结时点、车手或会话不匹配")
        if stream not in envelope.get("required_streams", []):
            raise ValueError("导入 required_streams 缺少所选车手 lap_state")
        # Imported original-target declarations are explicit and unverified;
        # they cannot override an original target already known in the prefix.
        declared = envelope.get("original_immediate_target_lap")
        if original is not None and declared is not None and declared != original:
            raise ValueError("导入原即时目标与冻结记录不匹配")
        if original is None:
            original = declared
    else:
        last = car["last_started_lap"]
        envelope = {
            "schema_version": 1,
            "session_id": str(frozen["state"]["session"]["session_key"]),
            "decision_sha256": frozen["decision_sha256"],
            "driver_id": driver,
            "required_streams": [stream],
            "data_kind": "cached_archive_event_time_only",
            "records": [
                {
                    "event_id": f"{driver}:last-visible-lap",
                    "stream": stream,
                    "session_id": str(frozen["state"]["session"]["session_key"]),
                    "source": last.get("source") or "unknown-archive-source",
                    "kind": "lap_state",
                    "event_time": last.get("event_at"),
                    "received_at": None,
                    "sequence": None,
                    "revision": None,
                    "payload": {"current_lap": last.get("value")},
                }
            ],
        }
    report = inspect_import(
        envelope,
        frozen["cutoff"],
        mode=mode,
        assumed_delay_seconds=delay,
        max_age_seconds=180,
        max_skew_seconds=2,
    )
    if original is not None:
        selection = select_horizon(
            report, horizon=horizon, driver_stream=stream, original_target_lap=original
        )
    else:
        selection = {
            "requested_horizon": horizon,
            "original_immediate_target_lap": None,
            "confirmation_at": frozen["cutoff"],
            "selected_target_lap": None,
            "candidate_target_lap": None,
            "prediction": None,
            "model_eligible": False,
            "availability_label": (
                "retrospective assumed availability"
                if mode == "historical_approximation"
                else "imported received_at; provenance unverified"
            ),
            "reason": "no_prefix_confirmed_completed_outlap",
        }
    normalized = {
        "horizon": horizon,
        "mode": mode,
        "assumed_delay_seconds": delay,
        "envelope": envelope if imported else None,
    }
    return {
        "schema_version": 1,
        "decision_sha256": frozen["decision_sha256"],
        "driver": driver,
        "request": normalized,
        "selection": selection,
        "availability": report,
        "clock_source": "imported_message_envelope_unverified"
        if imported
        else "cached_archive_event_time_only",
        "data_label": (
            "synthetic_fixture_unverified"
            if imported and envelope.get("data_kind") == "synthetic_fixture"
            else "user_import_unverified"
            if imported
            else "cached_archive"
        ),
        "assumptions": {
            "publication_delay_seconds": delay,
            "max_age_seconds": 180,
            "max_skew_seconds": 2,
            "full_field_synchronized": False,
        },
        "default_model": "v1",
        "v2_status": "experimental_failed_accuracy_gates",
        "prediction_enabled": False,
        "notice": "独立目标门控；不改变下方人工场景模拟，不提供实盘预测。导入时钟未经核验。",
    }


def verify_horizon_record(record):
    if record["horizon_source_sha256"] != source_manifest():
        raise ValueError("目标门控版本不同；请恢复导出记录对应的代码")
    result = build_horizon_report(
        record["frozen_decision"], record["selection"]["driver"], record["horizon_request"]
    )
    if digest(result) != digest(record["horizon_report"]):
        raise ValueError("目标或可用性门控与导出不同；不能宣称已复现")
    return {
        "horizon": result["selection"]["requested_horizon"],
        "horizon_report_sha256": digest(result),
        "prediction_enabled": False,
    }
