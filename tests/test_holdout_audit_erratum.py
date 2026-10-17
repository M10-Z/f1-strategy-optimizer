"""A nullable optional audit field cannot remove targets or alter forecast features."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest

from f1_strategy_optimizer import holdout_audit_erratum as erratum
from f1_strategy_optimizer import holdout_sources as sources
from f1_strategy_optimizer.event_replay import freeze_decision, iso
from f1_strategy_optimizer.replay import timestamp


def save(root, payload, url):
    path = root / "jolpica-pitstops-0000.body"
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "url": url,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "http_and_connect": "200 200",
            }
        )
    )


@pytest.fixture
def pit_audit(tmp_path):
    target = {"driverId": "tsunoda", "lap": "27", "stop": "1", "time": "15:45:52", "duration": ""}
    race = {
        "season": "2024",
        "round": "12",
        "raceName": "British Grand Prix",
        "date": "2024-07-07",
        "time": "14:00:00Z",
        "Circuit": {"circuitId": "silverstone"},
        "PitStops": [
            target,
            {
                "driverId": "norris",
                "lap": "28",
                "stop": "1",
                "time": "15:47:02",
                "duration": "24.500",
            },
        ],
    }
    source = {
        "MRData": {
            "url": "https://api.jolpi.ca/ergast/f1/2024/12/pitstops/",
            "limit": "100",
            "offset": "0",
            "total": "2",
            "RaceTable": {"season": "2024", "round": "12", "Races": [race]},
        }
    }
    url = "https://api.jolpi.ca/ergast/f1/2024/12/pitstops/?limit=100&offset=0"
    save(tmp_path, source, url)
    document = {
        "target": {
            "file": "jolpica-pitstops-0000.body",
            "row": target,
            "body_sha256": sources.sha_file(tmp_path / "jolpica-pitstops-0000.body"),
            "metadata_sha256": sources.sha_file(tmp_path / "jolpica-pitstops-0000.meta.json"),
        }
    }
    event = {
        "slug": "british",
        "name": "British Grand Prix",
        "round": 12,
        "scheduled_start": "2024-07-07T14:00:00Z",
        "circuit": "silverstone",
    }
    return tmp_path, document, event, source, url


def test_keep_raw_blank_and_all_rows_with_unknown_normalized_seconds(pit_audit):
    root, document, event, source, url = pit_audit
    original = sources._duration
    wrapped = erratum.nullable_pit_wrapper(sources._jolpica_rows, document)
    files, availability = [], {}
    rows = wrapped(root, event, "pitstops", files, availability)
    assert len(rows) == 2
    assert rows[0]["duration"] == ""
    assert rows[0]["duration_seconds"] is None
    assert rows[1]["duration_seconds"] == 24.5
    assert sources._duration is original
    assert len(files) == 1 and files[0]["count"] == files[0]["total"] == 2
    assert json.loads((root / document["target"]["file"]).read_bytes()) == source


def test_hash_mismatch_cannot_be_repaired_or_ignored(pit_audit):
    root, document, event, source, url = pit_audit
    path = root / document["target"]["file"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        erratum.validate_target(root, document)


@pytest.mark.parametrize("failure", ["duplicate", "url"])
def test_original_page_key_and_url_checks_are_still_enforced(pit_audit, failure):
    root, document, event, source, url = pit_audit
    if failure == "duplicate":
        source["MRData"]["RaceTable"]["Races"][0]["PitStops"][1].update(
            driverId="tsunoda", stop="1"
        )
    else:
        url = url.replace("offset=0", "offset=100")
    save(root, source, url)
    document["target"]["body_sha256"] = sources.sha_file(root / document["target"]["file"])
    document["target"]["metadata_sha256"] = sources.sha_file(
        root / "jolpica-pitstops-0000.meta.json"
    )
    prior = sources._duration
    wrapped = erratum.nullable_pit_wrapper(sources._jolpica_rows, document)
    with pytest.raises(ValueError):
        wrapped(root, event, "pitstops", [], {})
    assert sources._duration is prior


def test_no_other_event_or_stream_uses_nullable_parser(pit_audit):
    root, document, event, source, url = pit_audit
    calls = []
    prior = sources._duration

    def original(*args):
        assert sources._duration is prior
        calls.append(args[2])
        return ["unchanged"]

    wrapped = erratum.nullable_pit_wrapper(original, document)
    assert wrapped(root, {"slug": "monaco"}, "pitstops", [], {}) == ["unchanged"]
    assert wrapped(root, event, "laps", [], {}) == ["unchanged"]
    assert calls == ["pitstops", "laps"]


def test_pit_audit_values_cannot_change_frozen_observation_forecast():
    start = timestamp("2024-01-01T12:00:00Z", "synthetic start")

    def at(seconds):
        return iso(start + timedelta(seconds=seconds))

    archive = {
        "session": {
            "year": 2024,
            "session_key": 1,
            "meeting_key": 1,
            "session_name": "Race",
            "date_start": at(0),
        },
        "drivers": [{"driver_number": 1, "id": "synthetic", "team": "T", "name": "Synthetic"}],
        "laps": [
            {
                "driver_number": 1,
                "lap_number": n,
                "date_start": at((n - 1) * 90),
                "lap_duration": 90.0,
                "is_pit_out_lap": False,
            }
            for n in range(1, 11)
        ],
        "stints": [],
        "weather": [],
        "race_control": [],
        "position": [],
        "intervals": [],
        "pitstops": [{"driverId": "synthetic", "lap": 8, "duration": "", "duration_seconds": None}],
    }
    first = freeze_decision(archive, at(500))
    revised = deepcopy(archive)
    revised["pitstops"] = [{"driverId": "synthetic", "lap": 2, "duration_seconds": 99999}]
    assert freeze_decision(revised, at(500)) == first
