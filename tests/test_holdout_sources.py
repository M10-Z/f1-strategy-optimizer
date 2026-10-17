"""Synthetic adapter/protocol checks; no real holdout outcomes are used here."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from f1_strategy_optimizer import holdout_evaluation as evaluation
from f1_strategy_optimizer import holdout_sources as sources
from f1_strategy_optimizer.event_replay import EventTimePolicy, iso, verify_frozen
from f1_strategy_optimizer.replay import timestamp


def save(root, stem, document, url):
    root.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(document, separators=(",", ":")).encode()
    (root / f"{stem}.body").write_bytes(raw)
    receipt = {
        "url": url,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "http_and_connect": "200 200",
        "curl_exit_code": 0,
    }
    (root / f"{stem}.meta.json").write_text(json.dumps(receipt))


def mutate(root, stem, change):
    document = json.loads((root / f"{stem}.body").read_bytes())
    change(document)
    receipt = json.loads((root / f"{stem}.meta.json").read_bytes())
    save(root, stem, document, receipt["url"])


def jp(event, endpoint, rows, offset, total):
    key = {"results": "Results", "laps": "Laps", "pitstops": "PitStops"}[endpoint]
    return {
        "MRData": {
            "url": f"https://api.jolpi.ca/ergast/f1/2024/8/{endpoint}/",
            "limit": "100",
            "offset": str(offset),
            "total": str(total),
            "RaceTable": {
                "season": "2024",
                "round": "8",
                "Races": [
                    {
                        "season": "2024",
                        "round": "8",
                        "raceName": event["name"],
                        "Circuit": {"circuitId": "monaco"},
                        "date": "2024-05-26",
                        "time": "13:00:00Z",
                        key: rows,
                    }
                ],
            },
        }
    }


@pytest.fixture
def archived(tmp_path):
    event = {
        **sources.EVENTS[0],
        "round": 8,
        "scheduled_start": "2024-05-26T13:00:00Z",
        "status": "selected",
        "session": {
            "year": 2024,
            "session_key": 9999,
            "meeting_key": 1234,
            "session_name": "Race",
            "session_type": "Race",
            "country_name": "Monaco",
            "date_start": "2024-05-26T13:00:00Z",
        },
    }
    root = tmp_path / "holdout-2024-monaco"
    base = {"session_key": 9999, "meeting_key": 1234}

    def at(seconds):
        return iso(timestamp(event["scheduled_start"], "start") + timedelta(seconds=seconds))

    drivers = [
        {**base, "driver_number": number, "full_name": name, "team_name": team}
        for number, name, team in [
            (1, "Max VERSTAPPEN", "Red Bull"),
            (4, "Lando NORRIS", "McLaren"),
        ]
    ]
    of = {
        "drivers": drivers,
        "laps": [
            {
                **base,
                "driver_number": number,
                "lap_number": lap,
                "date_start": at((lap - 1) * 90),
                "lap_duration": 90.3 if lap == 1 else 90.0,
                "is_pit_out_lap": False,
            }
            for lap in range(1, 52)
            for number in (1, 4)
        ],
        "stints": [
            {
                **base,
                "driver_number": n,
                "stint_number": 1,
                "lap_start": 1,
                "lap_end": None,
                "compound": "SOFT",
                "tyre_age_at_start": 0,
            }
            for n in (1, 4)
        ],
        "intervals": [
            {**base, "driver_number": n, "date": at(t), "gap_to_leader": 0 if n == 1 else 1.0}
            for t in range(0, 4501, 10)
            for n in (1, 4)
        ],
        "position": [],
        "weather": [],
        "race_control": [],
        "pit": [],
    }
    of["laps"] += [
        {
            **base,
            "driver_number": n,
            "lap_number": 52,
            "date_start": at(4590),
            "lap_duration": None,
            "is_pit_out_lap": False,
        }
        for n in (1, 4)
    ]
    for kind, rows in of.items():
        save(root, f"openf1-{kind}", rows, f"https://api.openf1.org/v1/{kind}?session_key=9999")
    results = [
        {
            "number": "1",
            "position": "1",
            "status": "Finished",
            "Time": {"millis": "111"},
            "Driver": {
                "driverId": "max_verstappen",
                "givenName": "Max",
                "familyName": "Verstappen",
                "permanentNumber": "3",
            },
        },
        {
            "number": "4",
            "position": "2",
            "status": "Finished",
            "Driver": {
                "driverId": "norris",
                "givenName": "Lando",
                "familyName": "Norris",
                "permanentNumber": "1",
            },
        },
    ]
    all_laps = [
        (lap, driver, pos)
        for lap in range(1, 52)
        for driver, pos in (("max_verstappen", "1"), ("norris", "2"))
    ]
    pages = {"results": [(0, results, 2)], "pitstops": [(0, [], 0)], "laps": []}
    for offset in (0, 100):
        batch = [
            {
                "number": str(lap),
                "Timings": [{"driverId": driver, "time": "1:30.000", "position": pos}],
            }
            for lap, driver, pos in all_laps[offset : offset + 100]
        ]
        pages["laps"].append((offset, batch, len(all_laps)))
    for endpoint, values in pages.items():
        for offset, rows, total in values:
            save(
                root,
                f"jolpica-{endpoint}-{offset:04d}",
                jp(event, endpoint, rows, offset, total),
                f"https://api.jolpi.ca/ergast/f1/2024/8/{endpoint}/?limit=100&offset={offset}",
            )
    return root, event


def test_archive_validates_historical_identity_and_isolates_classification(archived):
    root, event = archived
    loaded = sources.load_holdout_archive(root, event)
    archive = loaded["archive"]
    assert archive["drivers"][1]["id"] == "norris"
    assert all(set(d) == {"driver_number", "id", "team", "name"} for d in archive["drivers"])
    assert len(archive["audit"]["null_duration_laps"]) == 2
    assert len(archive["audit"]["duration_disagreements"]) == 2
    assert archive["audit"]["jolpica_lap_count"] == 102
    assert archive["stints"][0]["lap_end"] is None
    assert "Finished" not in json.dumps(archive)
    files = archive["source_manifest"]["files"]
    assert [
        (f["offset"], f["count"], f["total"]) for f in files if "jolpica-laps-" in f["file"]
    ] == [(0, 100, 102), (100, 2, 102)]


@pytest.mark.parametrize(
    "failure", ["hash", "number", "name", "session", "duplicate", "total", "offset"]
)
def test_integrity_and_identity_fail_closed(archived, failure):
    root, event = archived
    if failure == "hash":
        path = root / "openf1-laps.body"
        path.write_bytes(path.read_bytes() + b" ")
    elif failure in {"number", "name"}:

        def change(document):
            row = document["MRData"]["RaceTable"]["Races"][0]["Results"][0]
            if failure == "number":
                row["number"] = "99"
            else:
                row["Driver"]["familyName"] = "Wrong"

        mutate(root, "jolpica-results-0000", change)
    elif failure in {"total", "offset"}:
        mutate(root, "jolpica-laps-0100", lambda d: d["MRData"].update({failure: "101"}))
    elif failure == "session":
        mutate(root, "openf1-laps", lambda rows: rows[0].update(session_key=8888))
    else:
        mutate(root, "openf1-laps", lambda rows: rows.append(rows[0]))
    with pytest.raises(ValueError):
        sources.load_holdout_archive(root, event)


def test_missing_source_and_invalid_timestamp_are_disclosed_not_fabricated(archived):
    root, event = archived
    (root / "openf1-intervals.body").unlink()
    mutate(root, "openf1-laps", lambda rows: rows[0].update(date_start=None))
    loaded = sources.load_holdout_archive(root, event)
    assert loaded["archive"]["intervals"] == []
    assert loaded["availability"]["openf1-intervals"]["status"] == "missing"
    assert loaded["archive"]["audit"]["quarantined_rows"][0]["endpoint"] == "laps"
    assert len(loaded["archive"]["laps"]) == 103


def test_incomplete_jolpica_audit_is_not_csv_fallback_or_required_feature(archived):
    root, event = archived
    (root / "jolpica-laps-0100.body").unlink()
    (root / "laps.csv").write_text("invented,csv")
    loaded = sources.load_holdout_archive(root, event)
    assert loaded["archive"]["audit"]["jolpica_lap_count"] is None
    assert len(loaded["archive"]["laps"]) == 104


def test_failed_response_is_cached_without_retry(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        from pathlib import Path

        Path(args[args.index("--output") + 1]).write_text("source denied")
        Path(args[args.index("--dump-header") + 1]).write_text("HTTP/1.1 403 Forbidden\n")
        return SimpleNamespace(returncode=0, stdout="403 200", stderr="")

    monkeypatch.setattr(sources.subprocess, "run", fake_run)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    fetcher = sources.BoundedFetcher("frozen-commit")
    url = "https://api.openf1.org/v1/laps?session_key=9999"
    first = fetcher.fetch(tmp_path, "laps", url)
    assert first["http_and_connect"] == "403 200"
    assert fetcher.fetch(tmp_path, "laps", url) == first
    assert len(calls) == 1


def test_acquisition_cannot_start_before_committed_protocol(monkeypatch, tmp_path):
    def denied(*args):
        raise ValueError("No verified committed freeze")

    monkeypatch.setattr(sources, "verify_freeze", denied)
    monkeypatch.setattr(
        sources.BoundedFetcher, "fetch", lambda *args: pytest.fail("network called")
    )
    with pytest.raises(ValueError, match="freeze"):
        sources.acquire_selected_events(tmp_path, tmp_path / "freeze.json", "unknown")


def test_partition_metadata_is_corrected_before_hash_without_changing_predictions(archived):
    root, event = archived
    archive = sources.load_holdout_archive(root, event)["archive"]
    policy = EventTimePolicy()
    cutoff = iso(timestamp(event["scheduled_start"], "start") + timedelta(seconds=600))
    from f1_strategy_optimizer.event_replay import freeze_decision

    old = freeze_decision(archive, cutoff, policy)
    new = evaluation.holdout_freeze(archive, cutoff, policy, "protocol", "commit")
    assert new["partition"] == new["state"]["partition"] == "holdout"
    assert new["observation_forecasts"] == old["observation_forecasts"]
    verify_frozen(new)
    assert "source_manifest" not in json.dumps(new)


def test_all_three_event_batches_are_durable_before_any_scoring(archived, tmp_path, monkeypatch):
    root, event = archived
    loaded = sources.load_holdout_archive(root, event)
    protocol = {
        "policy": __import__("dataclasses").asdict(EventTimePolicy()),
        "sampling": {"offset_seconds": list(range(600, 7201, 300))},
        "candidate_commit": sources.CANDIDATE_COMMIT,
        "reservation_sha256": "locked",
    }
    freeze_file = tmp_path / "protocol.json"
    freeze_file.write_text(json.dumps(protocol))
    output = tmp_path / "evaluation"
    monkeypatch.setattr(evaluation, "verify_freeze", lambda *args: protocol)
    monkeypatch.setattr(
        evaluation,
        "selected_metadata",
        lambda *args: (
            [{**event, "slug": e["slug"], "name": e["name"]} for e in sources.EVENTS],
            [],
        ),
    )
    monkeypatch.setattr(evaluation, "load_holdout_archive", lambda *args: deepcopy(loaded))
    original = evaluation.evaluate_frozen
    calls = []

    def spy(frozen, data):
        packets = json.loads((output / "decisions.json").read_bytes())
        assert len(packets) == 3 and all(len(p["decisions"]) == 23 for p in packets)
        assert frozen["partition"] == "holdout"
        calls.append(frozen["decision_sha256"])
        return original(frozen, data)

    monkeypatch.setattr(evaluation, "evaluate_frozen", spy)
    report = evaluation.run_holdouts(tmp_path, output, freeze_file, "freeze-commit")
    assert len(calls) == 69
    assert report["equal_race_aggregate"]["lap"]["total_registered_driver_cutoffs"] == 138
    assert all(r["summary"]["partition"] == "holdout" for r in report["races"])
    assert report["equal_race_aggregate"]["strategy_scored"] == 0
    with pytest.raises(ValueError, match="exists"):
        evaluation.run_holdouts(tmp_path, output, freeze_file, "freeze-commit")


def test_equal_event_aggregate_does_not_weight_by_target_count():
    races = []
    for value, count in [(1, 1), (3, 10), (8, 100)]:
        row = {
            "scored": count,
            "attempted": 100,
            "default_mae_seconds": value,
            "mae_seconds": {"prefix_linear": value + 1, "prefix_median": value},
        }
        races.append({"summary": {"lap": row, "gap": row}})
    result = evaluation.equal_race_aggregate(races)
    assert result["lap"]["equal_race_default_mae_seconds"] == 4
    assert (
        result["lap"]["paired_linear_minus_baseline_equal_race_mae_seconds"]["prefix_median"] == 1
    )


def test_protocol_binds_original_lock_and_exact_source_bytes(tmp_path):
    source = tmp_path / "adapter.py"
    source.write_text("frozen = True\n")
    sampling = {"offset_seconds": list(range(600, 7201, 300))}
    reservation = {
        "sampling": sampling,
        "holdout_events": [{"season": 2024, "event": e["name"]} for e in sources.EVENTS],
    }
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(reservation))
    protocol = {
        "candidate_commit": sources.CANDIDATE_COMMIT,
        "schema_version": 1,
        "source_sha256": {"adapter.py": sources.sha_file(source)},
        "reservation_file": "lock.json",
        "reservation_sha256": sources.sha_file(lock),
        "sampling": sampling,
        "events": list(sources.EVENTS),
    }
    assert sources.verify_protocol(protocol, tmp_path) == protocol
    source.write_text("frozen = False\n")
    with pytest.raises(ValueError, match="source hash"):
        sources.verify_protocol(protocol, tmp_path)
    source.write_text("frozen = True\n")
    lock.write_text(json.dumps({**reservation, "sampling": {"offset_seconds": [900]}}))
    with pytest.raises(ValueError, match="reservation hash"):
        sources.verify_protocol(protocol, tmp_path)
