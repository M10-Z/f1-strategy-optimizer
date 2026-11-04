"""Outcome-free forecast presentation and explicit operational readiness gates.

This service does not fit a new model or promote historical forecasts to live advice.
"""

import hashlib
from collections import Counter
from pathlib import Path

from .event_replay import digest
from .prefix_quality import assess_prefix

REASONS_ZH = {
    "missing_or_stale_lap_evidence": "完成圈证据缺失或过期，等待新数据",
    "control_active_or_clearance_unconfirmed": "赛会控制仍生效或尚未确认解除",
    "segment_warmup_requires_three_completed_laps": "当前赛段不足三个合格完成圈",
    "stale_eligible_segment": "当前赛段的合格圈样本已经过期",
    "unstable_segment_range_exceeds_four_seconds": "最近合格圈差异超过四秒，暂不预测",
    "no_fixed_target_lap": "无法确定固定目标圈",
}


def forecast_report(frozen, context=None, *, driver=None):
    """Use only a hash-verified decision prefix; never open outcome files.

    Availability means a conditional historical lap-duration reference, not
    verified target-start timing, calibrated accuracy, or operational readiness.
    """
    quality = assess_prefix(frozen, context)
    cars = frozen["state"]["cars"]
    if driver is not None and driver not in {car["id"] for car in cars}:
        raise ValueError("所选车手不在当前冻结快照中")
    selected = [car for car in cars if driver is None or car["id"] == driver]
    rows = []
    for car in selected:
        q = quality["drivers"][car["id"]]
        candidate, gap = q["candidate"], q["gap"]
        reason = candidate["reason"]
        blockers = ["source_publication_unverified", "model_acceptance_failed"]
        if car["activity"].get("status") == "unknown":
            blockers.append("driver_activity_unknown")
        if not gap["numeric_usable"]:
            blockers.append("numeric_gap_missing_or_stale")
        if reason:
            blockers.append(reason)
        rows.append(
            {
                "driver_id": car["id"],
                "driver_number": car["driver_number"],
                "name": car["name"],
                "team": car["team"],
                "target_lap": candidate["target_lap"],
                "target_start_verified": False,
                "predicted_lap_seconds": candidate["value_seconds"],
                "status": candidate["status"],
                "reason": reason,
                "reason_zh": REASONS_ZH.get(reason, reason),
                "sample_laps": candidate["sample_laps"],
                "sample_completion_times": candidate["sample_completion_times"],
                "observed_range_seconds": candidate["observed_range_seconds"],
                "range_is_not_confidence_interval": True,
                "prediction_interval": None,
                "lap_age_seconds": q["lap"]["age_seconds_at_cutoff"],
                "lap_max_age_seconds": q["lap"]["max_age_seconds"],
                "gap": {
                    "value_seconds": gap["last_reported_value"] if gap["numeric_usable"] else None,
                    "raw_reported_value": gap["last_reported_value"],
                    "age_seconds": gap["age_seconds_at_cutoff"],
                    "usable": gap["numeric_usable"],
                },
                "compound": car["compound"].get("value"),
                "activity_status": car["activity"].get("status"),
                "blocking_factors": blockers,
            }
        )
    available = sum(row["predicted_lap_seconds"] is not None for row in rows)
    report = {
        "schema_version": 1,
        "decision_sha256": frozen["decision_sha256"],
        "cutoff": frozen["cutoff"],
        "mode": "historical_replay",
        "live_ready": False,
        "model": {
            "id": "visible_segment_median_v1",
            "validation_status": "failed_acceptance",
            "validation_reference": "docs/freshness-validation.zh-CN.md",
            "validation_summary_zh": "独立验证改善 3.75%，未达到预注册的 10% 精度门槛",
            "v2_default": False,
        },
        "summary": {
            "drivers": len(rows),
            "available": available,
            "abstained": len(rows) - available,
            "abstention_reasons": dict(Counter(row["reason"] for row in rows if row["reason"])),
        },
        "drivers": rows,
        "availability_assumption": quality["availability_assumption"],
        "race_control": quality["race_control"],
        "weather": quality["weather"],
        "source_sha256": {
            "forecast_service.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "prefix_quality.py": quality["source_sha256"],
        },
        "context_sha256": quality["context_sha256"],
        "limitations": [
            "历史冻结前缀的条件圈时参考，不是实时预测或进站建议",
            "事件时间加假设延迟不等于已核验的源发布时间",
            "目标圈固定；目标开始时间尚未核验，不悄悄替换为更晚圈",
            "样本极差不是置信区间；没有校准的概率或预测区间",
            "未来进站、天气和赛会状态变化未知；车辆活动状态未知",
            "可用数量是当前快照的输出覆盖，不是准确率或真实策略收益",
        ],
    }
    report["report_sha256"] = digest(report)
    return report
