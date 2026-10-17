"""Synthetic metadata-only checks for a pre-outcome country alias correction."""

import hashlib
import json
from copy import deepcopy

import pytest

from f1_strategy_optimizer import holdout_identity_erratum as erratum
from f1_strategy_optimizer.holdout_sources import EVENTS


def save(root, name, document, url):
    raw = json.dumps(document).encode()
    (root / f"{name}.body").write_bytes(raw)
    (root / f"{name}.meta.json").write_text(
        json.dumps(
            {
                "url": url,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "http_and_connect": "200 200",
                "curl_exit_code": 0,
            }
        )
    )


@pytest.fixture
def metadata(tmp_path):
    root = tmp_path / "holdout-2024-metadata"
    root.mkdir()
    race = {
        "season": "2024",
        "round": "12",
        "raceName": "British Grand Prix",
        "Circuit": {"circuitId": "silverstone"},
        "date": "2024-07-07",
        "time": "14:00:00Z",
    }
    schedule = {
        "MRData": {
            "url": "https://api.jolpi.ca/ergast/f1/2024/",
            "limit": "100",
            "offset": "0",
            "total": "1",
            "RaceTable": {"season": "2024", "Races": [race]},
        }
    }
    session = {
        "year": 2024,
        "session_type": "Race",
        "session_name": "Race",
        "session_key": 9558,
        "meeting_key": 1240,
        "country_name": "United Kingdom",
        "date_start": "2024-07-07T14:00:00+00:00",
    }
    save(root, "jolpica-schedule", schedule, "https://api.jolpi.ca/ergast/f1/2024/?limit=100")
    save(
        root,
        "openf1-sessions",
        [session],
        "https://api.openf1.org/v1/sessions?year=2024&session_name=Race",
    )
    correction = {
        "event": "British Grand Prix",
        "from_country": "Great Britain",
        "to_country": "United Kingdom",
        "session_key": 9558,
        "meeting_key": 1240,
        "scheduled_start": "2024-07-07T14:00:00Z",
    }
    return tmp_path, {"events": list(EVENTS)}, correction


def test_alias_changes_country_only_and_preserves_reserved_calendar_identity(metadata):
    root, protocol, correction = metadata
    event = erratum.corrected_event(root, protocol, correction)
    assert event["name"] == "British Grand Prix"
    assert event["circuit"] == "silverstone"
    assert event["round"] == 12
    assert event["country"] == "United Kingdom"
    assert event["session"]["session_key"] == 9558
    assert event["scheduled_start"] == "2024-07-07T14:00:00+00:00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("to_country", "Italy"),
        ("from_country", "UK"),
        ("session_key", 9999),
        ("scheduled_start", "2024-07-07T14:01:00Z"),
    ],
)
def test_correction_cannot_retarget_event_or_start(metadata, field, value):
    root, protocol, correction = metadata
    correction[field] = value
    with pytest.raises(ValueError):
        erratum.corrected_event(root, protocol, correction)


def test_selection_wrapper_preserves_other_two_events_and_fixed_sampling(metadata):
    root, protocol, correction = metadata
    events = [{**e, "status": "selected", "marker": e["slug"]} for e in EVENTS]
    events[1] = {**EVENTS[1], "status": "missing", "reason": "session_identity_not_unique"}
    before = deepcopy(events)
    selected, receipts = erratum.corrected_selection(
        root, protocol, correction, lambda *args: (events, [])
    )
    assert selected[0] == before[0]
    assert selected[2] == before[2]
    assert selected[1]["status"] == "selected"
    assert protocol == {"events": list(EVENTS)}
    assert receipts == []


def test_british_fetch_cannot_start_without_committed_erratum(metadata, monkeypatch):
    root, protocol, correction = metadata

    def reject(*args):
        raise ValueError("No committed erratum")

    monkeypatch.setattr(erratum, "verify_erratum", reject)
    monkeypatch.setattr(
        erratum.BoundedFetcher, "fetch", lambda *args: pytest.fail("network called")
    )
    with pytest.raises(ValueError, match="committed"):
        erratum.acquire_british(root, root / "erratum.json", "unknown")
    assert not (root / "holdout-2024-british").exists()
