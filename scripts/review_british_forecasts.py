"""Post-observation development diagnostic; never changes frozen forecasts or scores."""

import json
import statistics
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from f1_strategy_optimizer.event_replay import digest, dt, verify_frozen


def main():
    root = Path(__file__).resolve().parents[2] / "real-data/holdout-2024-british"
    report = json.loads(Path("output/whole-race-holdout/final/british-evaluation.json").read_text())
    decisions = json.loads(
        Path("output/whole-race-holdout/final/british-decisions.json").read_text()
    )
    raw = json.loads((root / "openf1-laps.body").read_text())
    laps = {(r["driver_number"], r["lap_number"]): r for r in raw}
    weather = json.loads((root / "openf1-weather.body").read_text())
    pits = {
        (r["driverId"], int(r["lap"]))
        for r in json.loads((root / "jolpica-pitstops-0000.body").read_text())["MRData"][
            "RaceTable"
        ]["Races"][0]["PitStops"]
    }
    jolpica = {}
    for file in sorted(root.glob("jolpica-laps-*.body")):
        for lap in json.loads(file.read_text())["MRData"]["RaceTable"]["Races"][0]["Laps"]:
            for row in lap["Timings"]:
                minutes, seconds = row["time"].split(":")
                jolpica[row["driverId"], int(lap["number"])] = 60 * float(minutes) + float(seconds)
    ends = {
        driver: max(
            (
                dt(r["date_start"]) + timedelta(seconds=r["lap_duration"])
                for r in raw
                if r["driver_number"] == driver and r["date_start"] and r["lap_duration"]
            ),
            default=None,
        )
        for driver in {r["driver_number"] for r in raw}
    }
    end = max(e for e in ends.values() if e is not None)
    groups, exclusions, rows, sync_rejections, cutoff_metrics = (
        defaultdict(list),
        defaultdict(Counter),
        [],
        [],
        [],
    )
    mismatch, timings, prefix_availability_violations = [], [], []
    gap_prefix_reasons = Counter()
    for frozen, evaluation in zip(decisions, report["evaluations"]):
        verify_frozen(frozen)
        assert frozen["decision_sha256"] == evaluation["decision_sha256"]
        forecasts = {f["driver_id"]: f for f in frozen["observation_forecasts"]}
        cars = {c["id"]: c for c in frozen["state"]["cars"]}
        at = dt(frozen["cutoff"])
        cutoff_rows = []
        for item in evaluation["drivers"]:
            driver = item["driver_id"]
            number = item["driver_number"]
            f = forecasts[driver]
            r = item["lap"]
            for h in cars[driver]["completed_lap_history"]:
                if dt(h["assumed_available_at"]) > at:
                    prefix_availability_violations.append(
                        (frozen["cutoff"], driver, h["lap_number"])
                    )
            for kind in ("lap", "gap"):
                if item[kind]["errors"] is None:
                    period = (
                        "after_latest_recorded_finish"
                        if at > end
                        else "before_latest_recorded_finish"
                    )
                    exclusions[kind][period + ":" + item[kind]["reason"]] += 1
            if (
                at <= end
                and item["gap"]["reason"] == "insufficient_or_stale_numeric_interval_prefix"
            ):
                gap_prefix_reasons[
                    cars[driver]["gap_seconds"].get("reason", "short_numeric_prefix")
                ] += 1
            if r["errors"] is None:
                if r["reason"] == "target_already_started":
                    target = laps[number, f["lap"]["target_lap"]]
                    sync_rejections.append(
                        {
                            "cutoff": frozen["cutoff"],
                            "driver": driver,
                            "lag_seconds": (at - dt(target["date_start"])).total_seconds(),
                        }
                    )
                continue
            assert r["target_lap"] == f["lap"]["target_lap"] and dt(r["start_at"]) > at
            target = laps[number, r["target_lap"]]
            target_end = dt(r["start_at"]) + timedelta(seconds=r["actual"])
            wet = [w for w in weather if w["date"] and dt(w["date"]) <= target_end]
            rainfall = wet[-1].get("rainfall") if wet else None
            pit = (driver, r["target_lap"]) in pits or target.get("is_pit_out_lap") is True
            history = [
                h
                for h in cars[driver]["completed_lap_history"]
                if h["lap_number"] > 1 and h["is_pit_out_lap"] is False
            ][-frozen["config"]["lap_window"] :]
            contaminated = any((driver, h["lap_number"]) in pits for h in history)
            assert (
                statistics.median(h["lap_duration"] for h in history)
                == f["lap"]["predictions"]["prefix_median"]
            )
            jp = jolpica.get((driver, r["target_lap"]))
            delta = abs(jp - r["actual"]) if jp else None
            if delta is not None:
                mismatch.append(delta)
            nxt = laps.get((number, r["target_lap"] + 1))
            start_delta = (
                (dt(nxt["date_start"]) - dt(target["date_start"])).total_seconds() - r["actual"]
                if nxt and nxt["date_start"]
                else None
            )
            if start_delta is not None:
                timings.append(abs(start_delta))
            row = {
                "cutoff": frozen["cutoff"],
                "driver": driver,
                "target_lap": r["target_lap"],
                "actual": r["actual"],
                "prediction": f["lap"]["predictions"]["prefix_median"],
                "errors": r["errors"],
                "pit_related": pit,
                "rainfall_last_report_by_target_end": rainfall,
                "prefix_contains_pit_in_lap": contaminated,
                "jolpica_abs_difference": delta,
                "next_start_minus_duration": start_delta,
                "history_laps": [h["lap_number"] for h in history],
                "history_durations": [h["lap_duration"] for h in history],
            }
            rows.append(row)
            cutoff_rows.append(row)
            for key in [
                "all",
                "pit_related" if pit else "not_pit_related",
                "rain_report" if rainfall else "no_rain_report",
                "prefix_pit_in" if contaminated else "prefix_no_pit_in",
            ]:
                groups[key].append(row)
        cutoff_metrics.append(
            {
                "cutoff": frozen["cutoff"],
                "scored": len(cutoff_rows),
                "median_baseline_mae": statistics.mean(
                    r["errors"]["prefix_median"] for r in cutoff_rows
                )
                if cutoff_rows
                else None,
            }
        )

    def metric(items):
        return {
            "n": len(items),
            "mae": {m: statistics.mean(r["errors"][m] for r in items) for m in rows[0]["errors"]},
            "median_baseline_absolute_error_sum": sum(r["errors"]["prefix_median"] for r in items),
        }

    output = {
        "purpose": "post_observation_development_diagnostic_not_untouched_holdout",
        "source_evaluation_sha256": digest(report),
        "source_decisions_sha256": digest(decisions),
        "latest_recorded_finish": end.isoformat(),
        "summary_unchanged": report["summary"],
        "groups_overlap": True,
        "groups": {k: metric(v) for k, v in groups.items()},
        "exclusions_by_recorded_finish": {k: dict(v) for k, v in exclusions.items()},
        "gap_prefix_exclusions_before_latest_finish": dict(gap_prefix_reasons),
        "target_already_started": sync_rejections,
        "prefix_availability_violations": prefix_availability_violations,
        "scored_target_start_violations": 0,
        "jolpica_comparison": {
            "matched": len(mismatch),
            "max_difference_seconds": max(mismatch),
            "over_0_1s": sum(v > 0.1 for v in mismatch),
        },
        "next_start_duration_check": {
            "matched": len(timings),
            "max_abs_delta_seconds": max(timings),
            "over_1s": sum(v > 1 for v in timings),
        },
        "by_cutoff": cutoff_metrics,
        "largest_default_errors": sorted(
            rows, key=lambda r: r["errors"]["prefix_median"], reverse=True
        )[:20],
        "all_scored_rows": rows,
        "cautions": [
            "Rainfall is a weather report, not measured track wetness or causal attribution.",
            "Pit-related and prefix-pit groups overlap other groups; "
            "no target exclusions or recomputed official MAE.",
            "Latest recorded finish is posthoc audit only, not a proposed live filter.",
            "Correlated repeated drivers and times are not independent samples.",
        ],
    }
    path = Path("output/value-review/british-diagnostics.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in output.items()
                if k not in {"all_scored_rows", "largest_default_errors", "summary_unchanged"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
