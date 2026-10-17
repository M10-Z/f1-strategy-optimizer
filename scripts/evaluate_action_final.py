"""One immutable three-event acquisition/freeze/score pass for the registered v2 model."""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from f1_strategy_optimizer.action_evaluation import score_prediction, summarize
from f1_strategy_optimizer.action_model import POLICY, predict
from f1_strategy_optimizer.artifacts import write_json
from f1_strategy_optimizer.event_replay import digest, dt, freeze_decision
from f1_strategy_optimizer.freshness_sources import load_candidate_archive
from f1_strategy_optimizer.holdout_evaluation import selected_metadata
from f1_strategy_optimizer.holdout_sources import MAX_PAGES, OPENF1_KINDS, BoundedFetcher, _page
from f1_strategy_optimizer.prefix_quality import assess_prefix, make_context

ROOT = Path(__file__).resolve().parents[1]


class CohortFetcher(BoundedFetcher):
    def __init__(self, commit, budget):
        super().__init__(commit)
        self.budget = budget
        self.total_bytes = 0
        self.last_openf1_started = 0

    def fetch(self, root, stem, url):
        if self.requests >= self.budget["maximum_requests"]:
            raise ValueError("Cohort request budget exceeded")
        if self.total_bytes >= self.budget["maximum_total_bytes"]:
            raise ValueError("Cohort byte budget exceeded")
        if "api.openf1.org/" in url:
            wait = self.budget["minimum_openf1_spacing_seconds"] - (
                time.monotonic() - self.last_openf1_started
            )
            if wait > 0:
                time.sleep(wait)
            self.last_openf1_started = time.monotonic()
        receipt = super().fetch(root, stem, url)
        self.total_bytes += receipt["bytes"]
        if self.total_bytes > self.budget["maximum_total_bytes"]:
            raise ValueError("Cohort byte budget exceeded by response; saved without retry")
        if receipt["curl_exit_code"] or receipt["http_and_connect"] not in {"200 200", "200 000"}:
            raise ValueError(
                f"Source failure saved: {stem} HTTP/CONNECT {receipt['http_and_connect']}"
            )
        return receipt


def acquire(fetcher, root, event):
    if root.exists():
        raise ValueError("Reserved event cache exists; no overwrite or implicit rescore")
    root.mkdir()
    write_json(root / "event.json", event)
    for kind in OPENF1_KINDS:
        fetcher.fetch(
            root,
            f"openf1-{kind}",
            "https://api.openf1.org/v1/"
            + kind
            + "?"
            + urlencode({"session_key": event["session"]["session_key"]}),
        )
    for endpoint in ["results", "laps", "pitstops"]:
        offset, expected = 0, None
        for _ in range(MAX_PAGES):
            stem = f"jolpica-{endpoint}-{offset:04d}"
            receipt = fetcher.fetch(
                root,
                stem,
                f"https://api.jolpi.ca/ergast/f1/2024/{event['round']}/{endpoint}/?"
                + urlencode({"limit": 100, "offset": offset}),
            )
            raw = json.loads((root / f"{stem}.body").read_bytes())
            race, got, limit, total = _page(raw, receipt, event, endpoint)
            if got != offset or (expected is not None and total != expected):
                raise ValueError("Pagination identity changed")
            expected = total
            count = (
                sum(len(x["Timings"]) for x in race["Laps"])
                if endpoint == "laps"
                else len(race["Results" if endpoint == "results" else "PitStops"])
            )
            if count > limit or (not count and total):
                raise ValueError("Invalid page count")
            offset += count
            if offset == total:
                break
            if offset > total:
                raise ValueError("Pagination overrun")
        else:
            raise ValueError("Pagination budget exceeded")


def verify(commit):
    file = "examples/action-model-final-freeze.json"
    raw = (ROOT / file).read_bytes()
    if subprocess.check_output(["git", "show", f"{commit}:{file}"], cwd=ROOT) != raw:
        raise ValueError("Freeze file differs from commit")
    freeze = json.loads(raw)
    if freeze["policy"] != POLICY:
        raise ValueError("Candidate policy changed")
    for name, expected in freeze["source_sha256"].items():
        current = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        saved = hashlib.sha256(
            subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT)
        ).hexdigest()
        if current != expected or saved != expected:
            raise ValueError(f"Frozen source changed: {name}")
    return freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args()
    verify(args.freeze_commit)
    reservation = json.loads((ROOT / "examples/action-model-final-reservation.json").read_text())
    out = ROOT / "output/action-final-v2"
    if out.exists():
        raise ValueError("Final evaluation already started; no automatic rerun")
    out.mkdir()
    data_root = ROOT.parent / "real-data"
    events, _ = selected_metadata(data_root, reservation)
    if events != reservation["events"]:
        raise ValueError("Frozen cohort metadata changed")
    fetcher = CohortFetcher(args.freeze_commit, reservation["budget"])
    prepared, missing = {}, []
    for event in events:
        slug = event["slug"]
        raw_root = data_root / f"action-final-2024-{slug}"
        try:
            acquire(fetcher, raw_root, event)
            loaded = load_candidate_archive(raw_root, event)
            archive = loaded["archive"]
            if archive is None:
                raise ValueError("Identity-complete archive unavailable")
            frames, forecasts, contexts, versions = [], [], [], []
            for offset in reservation["sampling"]["offset_seconds"]:
                cutoff = (dt(event["scheduled_start"]) + timedelta(seconds=offset)).isoformat()
                f = freeze_decision(archive, cutoff)
                f["partition"] = f["state"]["partition"] = "final_evaluation"
                f["data_version"]["visible_prefix_sha256"] = digest(f["state"])
                f["action_model_freeze_commit"] = args.freeze_commit
                f.pop("decision_sha256")
                f["decision_sha256"] = digest(f)
                ctx = make_context(archive, f)
                frames.append(f)
                contexts.append(ctx)
                forecasts.append(predict(f, ctx, reservation["candidate"], reservation["prior"]))
                versions.append(assess_prefix(f, ctx))
            prepared[slug] = {
                "archive": archive,
                "frames": frames,
                "contexts": contexts,
                "forecasts": forecasts,
                "v1": versions,
            }
            write_json(
                out / f"{slug}-frozen.json",
                {k: v for k, v in prepared[slug].items() if k != "archive"},
            )
            write_json(
                out / f"{slug}-source-audit.json",
                {"manifest": loaded["source_manifest"], "audit": archive["audit"]},
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            missing.append(
                {"event": slug, "error": str(exc), "status": "failed_no_substitution_or_retry"}
            )
            write_json(out / f"{slug}-source-failure.json", missing[-1])
    # All available event forecasts are durable BEFORE any target scoring starts.
    receipt = {
        "freeze_commit": args.freeze_commit,
        "all_available_events_frozen_before_scoring": True,
        "network_requests": fetcher.requests,
        "raw_bytes": fetcher.total_bytes,
        "missing": missing,
        "files": {},
    }
    for p in out.glob("*-frozen.json"):
        with p.open("rb") as stream:
            os.fsync(stream.fileno())
        receipt["files"][p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    write_json(out / "prediction-freeze-receipt.json", receipt)
    results = {}
    future = stale = 0
    for slug, prepared_event in prepared.items():
        rows = []
        for pred, f, v1 in zip(
            prepared_event["forecasts"], prepared_event["frames"], prepared_event["v1"]
        ):
            for driver in pred["drivers"]:
                if driver["stay_seconds"] is not None:
                    future += sum(dt(t) > dt(f["cutoff"]) for t in driver["sample_available_at"])
                    last = dt(driver["sample_available_at"][-1]) - timedelta(seconds=3)
                    stale += int((dt(f["cutoff"]) - last).total_seconds() > 180)
            rows.extend(score_prediction(pred, f, v1, prepared_event["archive"]))
        write_json(out / f"{slug}-scores.json", rows)
        results[slug] = summarize(rows)
    thresholds = reservation["acceptance"]
    summaries = list(results.values())
    paired_ready = summaries and all(s["paired_candidate"]["n"] for s in summaries)
    macro_mae = (
        statistics.mean(
            s["paired_candidate"]["mae"] / s["paired_baseline"]["mae"] for s in summaries
        )
        if paired_ready
        else None
    )
    macro_tail = (
        statistics.mean(
            s["paired_candidate"]["p95"] / s["paired_baseline"]["p95"] for s in summaries
        )
        if paired_ready
        else None
    )
    denominator = sum(s["applicable_slots"] for s in summaries)
    coverage = sum(s["all_scored"]["n"] for s in summaries) / denominator if denominator else None
    checks = {
        "all_three_events": len(results) == 3 and not missing,
        "macro_mae": macro_mae is not None
        and macro_mae <= thresholds["equal_event_paired_mae_ratio_at_most"],
        "macro_p95": macro_tail is not None
        and macro_tail <= thresholds["equal_event_paired_p95_ratio_at_most"],
        "per_event_regression_limit": bool(paired_ready)
        and all(
            s["paired_candidate"]["mae"] / s["paired_baseline"]["mae"]
            <= thresholds["per_event_paired_mae_ratio_at_most"]
            for s in summaries
        ),
        "coverage": coverage is not None
        and coverage >= thresholds["pooled_applicable_coverage_at_least"],
        "coverage_each_vs_v1": bool(summaries)
        and all(s["coverage"] >= s["v1_coverage"] for s in summaries),
        "paired_count": sum(s["paired_candidate"]["n"] for s in summaries)
        >= thresholds["minimum_paired_total"],
        "paired_each": bool(summaries)
        and all(
            s["paired_candidate"]["n"] >= thresholds["minimum_paired_each_event"] for s in summaries
        ),
        "no_future_or_stale": future == stale == 0,
    }
    result = {
        "candidate": reservation["candidate"],
        "freeze_commit": args.freeze_commit,
        "results": results,
        "missing": missing,
        "macro_paired_mae_ratio": macro_mae,
        "macro_paired_p95_ratio": macro_tail,
        "pooled_coverage": coverage,
        "future_violations": future,
        "stale_violations": stale,
        "checks": checks,
        "acceptance": "passed" if all(checks.values()) else "failed_or_incomplete",
        "interpretation": (
            "Three-event historical observation check; no causal strategy benefit "
            "or calibrated real-time claim"
        ),
    }
    write_json(out / "evaluation.json", result)
    verify(args.freeze_commit)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
