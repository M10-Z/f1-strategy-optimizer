"""Small synthetic receipts exercise the offline archive boundary."""

import hashlib
import json

import pytest

from f1_strategy_optimizer.event_sources import load_archive


def write_source(root, filename, payload, url, *, jolpica=False):
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    path.write_bytes(raw)
    receipt = {
        "url": url,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "retrieved_at_utc": "2026-10-17T19:00:00Z",
    }
    receipt.update({"http_code": 200} if jolpica else {"http_and_connect": "200 200"})
    path.with_suffix(".meta.json").write_text(json.dumps(receipt))


def jolpica(endpoint, rows, offset=0, total=None, limit=2):
    field = {"results": "Results", "laps": "Laps", "pitstops": "PitStops"}[endpoint]
    race = {
        "season": "2023",
        "round": "1",
        "date": "2023-03-05",
        "time": "15:00:00Z",
        "raceName": "Bahrain Grand Prix",
        "Circuit": {"circuitId": "bahrain"},
        field: rows,
    }
    return {
        "MRData": {
            "url": f"https://api.jolpi.ca/ergast/f1/2023/1/{endpoint}/",
            "offset": str(offset),
            "total": str(len(rows) if total is None else total),
            "limit": str(limit),
            "RaceTable": {"season": "2023", "round": "1", "Races": [race]},
        }
    }


def mutate(root, filename, change):
    path = root / filename
    payload = json.loads(path.read_bytes())
    change(payload)
    receipt = json.loads(path.with_suffix(".meta.json").read_bytes())
    write_source(root, filename, payload, receipt["url"], jolpica=filename.endswith(".json"))


def test_identity_uses_separate_names_when_display_name_order_differs(archive_dirs):
    of, jp = archive_dirs

    def reorder(rows):
        rows[0].update(full_name="VERSTAPPEN Max", first_name="Max", last_name="Verstappen")

    mutate(of, "drivers.body", reorder)
    assert load_archive(of, jp)["drivers"][0]["id"] == "max_verstappen"


@pytest.fixture
def archive_dirs(tmp_path):
    of, jp = tmp_path / "openf1", tmp_path / "jolpica"
    base = {"meeting_key": 1141, "session_key": 7953}
    identity = [
        (1, "max_verstappen", "Max", "Verstappen"),
        (4, "norris", "Lando", "Norris"),
        (16, "leclerc", "Charles", "Leclerc"),
    ]
    sessions = [
        {
            **base,
            "year": 2023,
            "country_name": "Bahrain",
            "session_name": "Race",
            "session_type": "Race",
            "date_start": "2023-03-05T15:00:00Z",
        }
    ]
    rows = {
        "sessions": sessions,
        "drivers": [
            {
                **base,
                "driver_number": number,
                "full_name": f"{first} {last}",
                "team_name": f"Team {number}",
            }
            for number, _, first, last in identity
        ],
        "laps": [
            {
                **base,
                "driver_number": number,
                "lap_number": lap,
                "lap_duration": 90.3 if lap == 1 else 90.0 if lap == 2 else None,
                "date_start": f"2023-03-05T15:0{lap * 2}:00Z",
            }
            for number, *_ in identity
            for lap in (1, 2, 3)
        ],
        "stints": [
            {
                **base,
                "driver_number": number,
                "stint_number": 1,
                "lap_start": 1,
                "lap_end": 3,
                "compound": "SOFT",
                "tyre_age_at_start": 0,
            }
            for number, *_ in identity
        ],
        "weather": [
            {**base, "date": "2023-03-05T15:00:00Z", "rainfall": 0, "track_temperature": 30}
        ],
        "race_control": [
            {
                **base,
                "date": "2023-03-05T15:00:00Z",
                "category": "Flag",
                "message": "GREEN LIGHT - PIT EXIT OPEN",
                "scope": "Track",
            }
        ],
        "position": [{**base, "driver_number": 1, "date": "2023-03-05T15:00:00Z", "position": 1}],
        "intervals": [
            {
                **base,
                "driver_number": 1,
                "date": "2023-03-05T15:00:00Z",
                "gap_to_leader": 0,
                "interval": None,
            }
        ],
    }
    for kind, records in rows.items():
        query = (
            "year=2023&country_name=Bahrain&session_name=Race"
            if kind == "sessions"
            else ("session_key=7953")
        )
        write_source(of, f"{kind}.body", records, f"https://api.openf1.org/v1/{kind}?{query}")
    results = [
        {
            "number": str(number),
            "position": str(i + 1),
            "status": "Finished",
            "Driver": {
                "driverId": driver,
                "givenName": first,
                "familyName": last,
                "permanentNumber": "1" if driver == "norris" else "3",
            },
            "Time": {"millis": "999999"},
        }
        for i, (number, driver, first, last) in enumerate(identity)
    ]
    write_source(
        of,
        "jolpica-results.body",
        jolpica("results", results, limit=100),
        "https://api.jolpi.ca/ergast/f1/2023/1/results/?limit=100",
    )
    timings = [(lap, driver) for lap in (1, 2) for _, driver, *_ in identity]
    for offset in (0, 2, 4):
        # Pages can split the same lap group, so the adapter counts timings, not groups.
        laps = [
            {
                "number": str(lap),
                "Timings": [{"driverId": driver, "time": "1:30.000", "position": "1"}],
            }
            for lap, driver in timings[offset : offset + 2]
        ]
        write_source(
            jp,
            f"raw/laps-{offset:04d}.json",
            jolpica("laps", laps, offset, 6),
            f"https://api.jolpi.ca/ergast/f1/2023/1/laps/?limit=2&offset={offset}",
            jolpica=True,
        )
    pits = [
        {"driverId": "norris", "lap": "2", "stop": "1", "time": "18:03:00", "duration": "24.500"}
    ]
    write_source(
        jp,
        "raw/pitstops-0000.json",
        jolpica("pitstops", pits),
        "https://api.jolpi.ca/ergast/f1/2023/1/pitstops/?limit=2&offset=0",
        jolpica=True,
    )
    (jp / "laps.csv").write_text("malicious,csv,ignored")
    return of, jp


def test_archive_preserves_source_timings_and_historical_identity(archive_dirs):
    result = load_archive(*archive_dirs)
    assert {d["driver_number"]: d["id"] for d in result["drivers"]} == {
        1: "max_verstappen",
        4: "norris",
        16: "leclerc",
    }
    assert all(set(d) == {"driver_number", "id", "team", "name"} for d in result["drivers"])
    assert result["audit"]["completed_lap_records"] == 6
    assert len(result["audit"]["null_duration_laps"]) == 3
    assert result["audit"]["first_lap_disagreements"] == 3
    assert result["laps"][0]["lap_duration"] == 90.3
    assert result["jolpica_laps"][0]["lap_duration"] == 90.0
    assert result["pitstops"][0]["duration_seconds"] == 24.5
    assert "available_at" not in result["pitstops"][0]
    assert not result["audit"]["replay_ready"]
    files = result["source_manifest"]["files"]
    pages = [r for r in files if r["file"].startswith("jolpica/raw/laps-")]
    assert [(r["offset"], r["count"], r["total"]) for r in pages] == [
        (0, 2, 6),
        (2, 2, 6),
        (4, 2, 6),
    ]
    assert load_archive(*archive_dirs)["source_manifest"] == result["source_manifest"]


@pytest.mark.parametrize("failure", ["bytes", "sha256", "http"])
def test_receipt_integrity_fails_closed(archive_dirs, failure):
    of, jp = archive_dirs
    meta = jp / "raw/laps-0000.meta.json"
    receipt = json.loads(meta.read_bytes())
    receipt[{"bytes": "bytes", "sha256": "sha256", "http": "http_code"}[failure]] = (
        "0" * 64 if failure == "sha256" else 0
    )
    meta.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="mismatch|Unsuccessful"):
        load_archive(of, jp)


@pytest.mark.parametrize("failure", ["missing", "offset", "total", "url", "duplicate"])
def test_bad_pagination_fails_closed(archive_dirs, failure):
    of, jp = archive_dirs
    filename = "raw/laps-0002.json"
    if failure == "missing":
        (jp / filename).unlink()
    elif failure == "url":
        meta = (jp / filename).with_suffix(".meta.json")
        receipt = json.loads(meta.read_bytes())
        receipt["url"] = receipt["url"].replace("offset=2", "offset=0")
        meta.write_text(json.dumps(receipt))
    elif failure in {"offset", "total"}:
        mutate(jp, filename, lambda d: d["MRData"].update({failure: "5"}))
    else:
        first = json.loads((jp / "raw/laps-0000.json").read_bytes())
        duplicate = first["MRData"]["RaceTable"]["Races"][0]["Laps"][0]
        mutate(
            jp,
            filename,
            lambda d: d["MRData"]["RaceTable"]["Races"][0]["Laps"].__setitem__(0, duplicate),
        )
    with pytest.raises(ValueError, match="pagination|Duplicate|filename|Incomplete"):
        load_archive(of, jp)


@pytest.mark.parametrize("failure", ["name", "number", "race", "session", "duplicate"])
def test_identity_and_duplicate_keys_fail_closed(archive_dirs, failure):
    of, jp = archive_dirs
    if failure in {"name", "number"}:

        def change(document):
            row = document["MRData"]["RaceTable"]["Races"][0]["Results"][0]
            if failure == "name":
                row["Driver"]["familyName"] = "Wrong"
            else:
                row["number"] = "99"

        mutate(of, "jolpica-results.body", change)
    elif failure == "race":
        mutate(
            jp,
            "raw/laps-0000.json",
            lambda d: d["MRData"]["RaceTable"]["Races"][0].update({"date": "2023-03-06"}),
        )
    elif failure == "session":
        mutate(of, "laps.body", lambda d: d[0].update({"session_key": 9999}))
    else:
        mutate(of, "laps.body", lambda d: d.append(d[0]))
    with pytest.raises(ValueError):
        load_archive(of, jp)


def test_sample_cannot_replace_missing_full_session(archive_dirs):
    of, jp = archive_dirs
    (of / "position.body").rename(of / "position-sample-corrected.body")
    (of / "position.meta.json").rename(of / "position-sample-corrected.meta.json")
    result = load_archive(of, jp)
    assert result["position"] == []
    assert result["audit"]["coverage"]["position"] == "missing_full_session_response"
    assert all("sample" not in row["file"] for row in result["source_manifest"]["files"])


def test_filtered_response_cannot_claim_full_session(archive_dirs):
    of, jp = archive_dirs
    meta = of / "intervals.meta.json"
    receipt = json.loads(meta.read_bytes())
    receipt["url"] += "&date%3E=2023-03-05T15:00:00Z"
    meta.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="full session"):
        load_archive(of, jp)


def test_manifest_changes_when_receipt_changes(archive_dirs):
    of, jp = archive_dirs
    before = load_archive(of, jp)["source_manifest"]["sha256"]
    meta = of / "weather.meta.json"
    receipt = json.loads(meta.read_bytes())
    receipt["retrieved_at_utc"] = "2026-10-18T00:00:00Z"
    meta.write_text(json.dumps(receipt))
    assert load_archive(of, jp)["source_manifest"]["sha256"] != before
