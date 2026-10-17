"""Frozen, bounded public archive acquisition for the three reserved 2024 events.

This module never infers online availability or passes classification fields to
features. Raw receipts are immutable caches, including failed HTTP responses.
No automatic retry, host substitution, authentication or CSV fallback is used.
"""

import argparse
import hashlib
import json
import math
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .artifacts import write_json
from .event_sources import _duration, _integer, _read, _unique, _url
from .replay import timestamp

CANDIDATE_COMMIT = "d466efa50375a28d05795d46740c89e6dcf80e8a"
EVENTS = (
    {
        "slug": "monaco",
        "name": "Monaco Grand Prix",
        "circuit": "monaco",
        "country": "Monaco",
        "openf1_circuit": "Monte Carlo",
    },
    {
        "slug": "british",
        "name": "British Grand Prix",
        "circuit": "silverstone",
        "country": "Great Britain",
        "openf1_circuit": "Silverstone",
    },
    {
        "slug": "italian",
        "name": "Italian Grand Prix",
        "circuit": "monza",
        "country": "Italy",
        "openf1_circuit": "Monza",
    },
)
OPENF1_KINDS = (
    "drivers",
    "laps",
    "stints",
    "position",
    "intervals",
    "weather",
    "race_control",
    "pit",
)
MAX_REQUESTS = 150
MAX_PAGES = 40
MAX_BYTES = 20_000_000


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_protocol(protocol, repo):
    """Verify pinned source and reservation bytes before data access or scoring."""
    repo = Path(repo)
    if protocol["candidate_commit"] != CANDIDATE_COMMIT or protocol["schema_version"] != 1:
        raise ValueError("Wrong frozen candidate/protocol version")
    for name, expected in protocol["source_sha256"].items():
        if sha_file(repo / name) != expected:
            raise ValueError(f"Frozen source hash mismatch: {name}")
    lock = repo / protocol["reservation_file"]
    if sha_file(lock) != protocol["reservation_sha256"]:
        raise ValueError("Original holdout reservation hash mismatch")
    reservation = json.loads(lock.read_bytes())
    if protocol["sampling"] != reservation["sampling"]:
        raise ValueError("Frozen sampling differs from the original reservation")
    expected = [(r["season"], r["event"]) for r in reservation["holdout_events"]]
    if expected != [(2024, e["name"]) for e in EVENTS]:
        raise ValueError("Reserved events differ; substitutions forbidden")
    if protocol["events"] != list(EVENTS):
        raise ValueError("Frozen adapter event identities differ")
    return protocol


def verify_freeze(protocol_file, freeze_commit, repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[2])
    path = Path(protocol_file).resolve()
    protocol = verify_protocol(json.loads(path.read_bytes()), repo)
    relative = path.relative_to(repo).as_posix()
    saved = subprocess.run(
        ["git", "show", f"{freeze_commit}:{relative}"], cwd=repo, check=True, capture_output=True
    ).stdout
    if saved != path.read_bytes():
        raise ValueError("Protocol is not the exact committed pre-acquisition freeze")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", CANDIDATE_COMMIT, freeze_commit],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    for name, expected in protocol["source_sha256"].items():
        saved = subprocess.run(
            ["git", "show", f"{freeze_commit}:{name}"], cwd=repo, check=True, capture_output=True
        ).stdout
        if hashlib.sha256(saved).hexdigest() != expected:
            raise ValueError(f"Freeze commit does not bind source: {name}")
    return protocol


def _now():
    return datetime.now(timezone.utc).isoformat()


class BoundedFetcher:
    """One ordinary GET per uncached URL; preserve failures without retry."""

    def __init__(self, freeze_commit):
        self.freeze_commit = freeze_commit
        self.requests = 0

    def fetch(self, root, stem, url):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        body, headers, meta = (root / f"{stem}{ext}" for ext in (".body", ".headers", ".meta.json"))
        if meta.exists():
            receipt = json.loads(meta.read_bytes())
            if (
                receipt["url"] != url
                or sha_file(body) != receipt["sha256"]
                or body.stat().st_size != receipt["bytes"]
            ):
                raise ValueError(f"Cache URL/hash mismatch: {body}")
            return receipt
        if body.exists() or headers.exists():
            raise ValueError(f"Incomplete prior cache; do not overwrite or retry: {body}")
        if self.requests >= MAX_REQUESTS:
            raise ValueError("Acquisition request budget exceeded")
        parsed_host = url.split("/", 3)[2]
        if not url.startswith("https://") or parsed_host not in {"api.openf1.org", "api.jolpi.ca"}:
            raise ValueError("Only the two frozen public source hosts are permitted")
        self.requests += 1
        started = _now()
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "15",
                "--max-time",
                "60",
                "--retry",
                "0",
                "--max-filesize",
                str(MAX_BYTES),
                "--dump-header",
                str(headers),
                "--output",
                str(body),
                "--write-out",
                "%{http_code} %{http_connect}",
                url,
            ],
            capture_output=True,
            text=True,
        )
        if not body.exists():
            body.write_bytes(b"")
        header_text = headers.read_text(errors="replace") if headers.exists() else ""
        dates = [
            line.partition(":")[2].strip()
            for line in header_text.splitlines()
            if line.lower().startswith("date:")
        ]
        receipt = {
            "url": url,
            "method": "GET",
            "started_at_utc": started,
            "retrieved_at_utc": _now(),
            "curl_exit_code": result.returncode,
            "http_and_connect": result.stdout.strip(),
            "stderr": result.stderr,
            "bytes": body.stat().st_size,
            "sha256": sha_file(body),
            "source_date": dates[-1] if dates else None,
            "freeze_commit": self.freeze_commit,
            "retries": 0,
        }
        write_json(meta, receipt)
        print(f"GET {url}: {receipt['http_and_connect']} bytes={receipt['bytes']}", flush=True)
        # Source-friendly request spacing; not a retry or alternate access path.
        time.sleep(1)
        return receipt


def _try_read(root, stem, namespace, files, availability):
    body, meta = Path(root) / f"{stem}.body", Path(root) / f"{stem}.meta.json"
    if not meta.exists() or not body.exists():
        availability[stem] = {"status": "missing", "reason": "no_saved_response"}
        return None
    receipt = json.loads(meta.read_bytes())
    if sha_file(body) != receipt["sha256"] or body.stat().st_size != receipt["bytes"]:
        raise ValueError(f"Archive hash/bytes mismatch: {body}")
    if receipt.get("curl_exit_code", 0) != 0 or receipt.get("http_and_connect") not in {
        "200 200",
        "200 000",
    }:
        availability[stem] = {
            "status": "missing",
            "reason": "unsuccessful_HTTP_or_transport",
            "receipt": receipt,
        }
        files.append(
            {
                "file": f"{namespace}/{stem}.body",
                "sha256": receipt["sha256"],
                "metadata_sha256": sha_file(meta),
                "url": receipt["url"],
                "http_and_connect": receipt.get("http_and_connect"),
                "bytes": receipt["bytes"],
            }
        )
        return None
    document, receipt, entry = _read(Path(root), f"{stem}.body", namespace, files)
    availability[stem] = {"status": "available", "url": receipt["url"]}
    return document, receipt, entry


def _schedule_rows(document):
    mr = document["MRData"]
    _url(mr["url"], "api.jolpi.ca", "/ergast/f1/2024/")
    if str(mr["RaceTable"]["season"]) != "2024":
        raise ValueError("Wrong schedule season")
    rows = mr["RaceTable"]["Races"]
    if int(mr["offset"]) != 0 or len(rows) != int(mr["total"]) or len(rows) > int(mr["limit"]):
        raise ValueError("Incomplete schedule metadata")
    _unique(rows, lambda row: row["round"], "schedule round")
    return rows


def _race(document, event, endpoint):
    mr = document["MRData"]
    _url(mr["url"], "api.jolpi.ca", f"/ergast/f1/2024/{event['round']}/{endpoint}/")
    table = mr["RaceTable"]
    if str(table["season"]) != "2024" or str(table["round"]) != str(event["round"]):
        raise ValueError("Wrong Jolpica race table")
    if len(table["Races"]) != 1:
        raise ValueError("Expected exactly one reserved race")
    race = table["Races"][0]
    if (
        str(race["season"]) != "2024"
        or str(race["round"]) != str(event["round"])
        or race["raceName"] != event["name"]
        or race["Circuit"]["circuitId"] != event["circuit"]
        or timestamp(f"{race['date']}T{race['time']}", "race time")
        != timestamp(event["scheduled_start"], "scheduled start")
    ):
        raise ValueError("Wrong Jolpica reserved event identity")
    return mr, race


def _page(document, receipt, event, endpoint):
    mr, race = _race(document, event, endpoint)
    offset, limit, total = (
        _integer(mr[k], k, 1 if k == "limit" else 0) for k in ("offset", "limit", "total")
    )
    query = _url(receipt["url"], "api.jolpi.ca", f"/ergast/f1/2024/{event['round']}/{endpoint}/")
    if query != {"limit": str(limit), "offset": str(offset)}:
        raise ValueError("Jolpica URL pagination mismatch")
    if total > 4000 or limit != 100:
        raise ValueError("Frozen pagination budget/limit exceeded")
    return race, offset, limit, total


def _name_tokens(value):
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", value).casefold() if not unicodedata.combining(c)
    )
    for mark in "-.'’":
        normalized = normalized.replace(mark, " ")
    return sorted(normalized.split())


def _drivers(raw, results):
    _unique(raw, lambda row: row["driver_number"], "OpenF1 driver")
    _unique(results, lambda row: _integer(row["number"], "race number", 1), "race number")
    _unique(results, lambda row: row["Driver"]["driverId"], "historical driver")
    by_number = {_integer(row["number"], "race number", 1): row["Driver"] for row in results}
    if not raw or {row["driver_number"] for row in raw} != set(by_number):
        raise ValueError("Historical registered driver fields differ")
    drivers = []
    for row in raw:
        driver = by_number[row["driver_number"]]
        full_name = f"{driver['givenName']} {driver['familyName']}"
        if _name_tokens(row["full_name"]) != _name_tokens(full_name):
            raise ValueError("Historical race number/name mismatch")
        if not row.get("team_name") or not driver.get("driverId"):
            raise ValueError("Missing historical driver/team identity")
        drivers.append(
            {
                "driver_number": row["driver_number"],
                "id": driver["driverId"],
                "team": row["team_name"],
                "name": row["full_name"],
            }
        )
    return sorted(drivers, key=lambda row: row["driver_number"])


def _open_rows(document, receipt, event, kind, quarantine):
    if _url(receipt["url"], "api.openf1.org", f"/v1/{kind}") != {
        "session_key": str(event["session"]["session_key"])
    }:
        raise ValueError("Expected exact full-session OpenF1 URL")
    if not isinstance(document, list) or len(document) > 100_000:
        raise ValueError("Expected bounded OpenF1 row list")
    accepted = []
    for index, row in enumerate(document):
        if (
            row.get("session_key") != event["session"]["session_key"]
            or row.get("meeting_key") != event["session"]["meeting_key"]
        ):
            raise ValueError("Cross-event OpenF1 record")
        try:
            if kind == "laps":
                _integer(row["driver_number"], "driver number", 1)
                _integer(row["lap_number"], "lap number", 1)
                timestamp(row["date_start"], "date_start")
                duration = row.get("lap_duration")
                if duration is not None and (
                    not isinstance(duration, (int, float))
                    or isinstance(duration, bool)
                    or not math.isfinite(duration)
                    or duration <= 0
                ):
                    raise ValueError("Invalid nonnull duration")
            elif kind == "stints":
                for field in ("driver_number", "stint_number", "lap_start"):
                    _integer(row[field], field, 1)
                _integer(row["tyre_age_at_start"], "initial tyre age")
                if not isinstance(row["compound"], str) or not row["compound"]:
                    raise ValueError("Unknown compound")
            elif kind != "drivers":
                timestamp(row["date"], "date")
        except (ValueError, TypeError, KeyError) as exc:
            quarantine.append(
                {"endpoint": kind, "row_index": index, "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        accepted.append(row)
    if kind in {"drivers", "laps", "stints"}:
        keys = {"drivers": "driver_number", "laps": "lap_number", "stints": "stint_number"}
        _unique(document, lambda r: (r.get("driver_number"), r.get(keys[kind])), kind)
    elif kind in {"position", "intervals"}:
        _unique(accepted, lambda r: (r["driver_number"], timestamp(r["date"], "date")), kind)
    elif kind == "weather":
        _unique(accepted, lambda r: timestamp(r["date"], "date"), kind)
    elif kind == "race_control":
        _unique(accepted, lambda r: json.dumps(r, sort_keys=True), kind)
    return accepted


def _jolpica_rows(root, event, endpoint, files, availability):
    records, expected, offset = [], None, 0
    for page_index in range(MAX_PAGES):
        stem = f"jolpica-{endpoint}-{offset:04d}"
        loaded = _try_read(root, stem, event["slug"], files, availability)
        if loaded is None:
            return None
        document, receipt, entry = loaded
        race, actual_offset, limit, total = _page(document, receipt, event, endpoint)
        if expected is None:
            expected = total
        if actual_offset != offset or total != expected:
            raise ValueError("Jolpica page gap/overlap/changed total")
        if endpoint == "laps":
            batch = [
                {
                    "driverId": timing["driverId"],
                    "lap": _integer(lap["number"], "lap", 1),
                    "time": timing["time"],
                    "lap_duration": _duration(timing["time"]),
                    "position": _integer(timing["position"], "position", 1),
                }
                for lap in race["Laps"]
                for timing in lap["Timings"]
            ]
        elif endpoint == "pitstops":
            batch = [
                {
                    "driverId": row["driverId"],
                    "lap": _integer(row["lap"], "lap", 1),
                    "stop": _integer(row["stop"], "stop", 1),
                    "time": row["time"],
                    "duration": row["duration"],
                    "duration_seconds": _duration(row["duration"]),
                }
                for row in race["PitStops"]
            ]
        else:
            batch = race["Results"]
        if len(batch) > limit or (not batch and total):
            raise ValueError("Jolpica page count invalid")
        entry.update(offset=offset, count=len(batch), total=total, limit=limit)
        records.extend(batch)
        offset += len(batch)
        if offset == expected:
            break
        if offset > expected:
            raise ValueError("Jolpica total exceeded")
    else:
        raise ValueError("Jolpica pagination budget exceeded")
    if endpoint != "results":
        key = "lap" if endpoint == "laps" else "stop"
        _unique(records, lambda row: (row["driverId"], row[key]), f"Jolpica {endpoint}")
    extra = set(Path(root).glob(f"jolpica-{endpoint}-*.body"))
    expected_files = {
        Path(root) / e["file"].split("/", 1)[1]
        for e in files
        if e["file"].startswith(f"{event['slug']}/jolpica-{endpoint}-")
    }
    if extra - expected_files:
        raise ValueError("Unexpected extra Jolpica page files")
    return records


def load_holdout_archive(root, event):
    """Return event archive and audit; no classification fields enter features."""
    root = Path(root)
    files, availability, quarantine = [], {}, []
    rows = {}
    for kind in OPENF1_KINDS:
        loaded = _try_read(root, f"openf1-{kind}", event["slug"], files, availability)
        rows[kind] = _open_rows(*loaded[:2], event, kind, quarantine) if loaded else []
    raw_driver_count = len(rows["drivers"])
    results = _jolpica_rows(root, event, "results", files, availability)
    if not rows["drivers"] or results is None:
        return {
            "archive": None,
            "registered_driver_count": raw_driver_count
            or (len(results) if results is not None else None),
            "reason": "missing_verified_driver_identity",
            "source_manifest": {"files": files},
            "availability": availability,
        }
    drivers = _drivers(rows["drivers"], results)
    numbers = {d["driver_number"] for d in drivers}
    for kind, records in rows.items():
        if any(
            r.get("driver_number") is not None and r["driver_number"] not in numbers
            for r in records
        ):
            raise ValueError(f"Unknown registered driver in {kind}")
    jp_laps = _jolpica_rows(root, event, "laps", files, availability)
    pitstops = _jolpica_rows(root, event, "pitstops", files, availability)
    mapping = {d["driver_number"]: d["id"] for d in drivers}
    if any(r["driverId"] not in set(mapping.values()) for r in (jp_laps or []) + (pitstops or [])):
        raise ValueError("Unknown Jolpica audit driver")
    of_laps = {(mapping[r["driver_number"]], r["lap_number"]): r for r in rows["laps"]}
    jp_by_key = {(r["driverId"], r["lap"]): r for r in jp_laps or []}
    differences = [
        {
            "driverId": key[0],
            "lap": key[1],
            "openf1_seconds": row["lap_duration"],
            "jolpica_seconds": jp_by_key[key]["lap_duration"],
        }
        for key, row in sorted(of_laps.items())
        if key in jp_by_key
        and row["lap_duration"] is not None
        and abs(row["lap_duration"] - jp_by_key[key]["lap_duration"]) > 0.001000001
    ]
    manifest = {"event": event["name"], "files": sorted(files, key=lambda r: r["file"])}
    manifest["sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    audit = {
        "availability": availability,
        "quarantined_rows": quarantine,
        "counts": {kind: len(records) for kind, records in rows.items()},
        "identity": "same-race Results.number plus accent/case-insensitive name token equality",
        "null_duration_laps": [list(k) for k, r in of_laps.items() if r["lap_duration"] is None],
        "duration_disagreements": differences,
        "openf1_only_keys": [list(k) for k in sorted(set(of_laps) - set(jp_by_key))]
        if jp_laps is not None
        else None,
        "jolpica_only_keys": [list(k) for k in sorted(set(jp_by_key) - set(of_laps))]
        if jp_laps is not None
        else None,
        "jolpica_lap_count": len(jp_laps) if jp_laps is not None else None,
        "jolpica_pit_count": len(pitstops) if pitstops is not None else None,
    }
    archive = {
        "session": event["session"],
        "drivers": drivers,
        **{
            k: rows[k]
            for k in ("laps", "stints", "position", "intervals", "weather", "race_control")
        },
        "pitstops": pitstops or [],
        "source_manifest": manifest,
        "audit": audit,
    }
    return {
        "archive": archive,
        "registered_driver_count": len(drivers),
        "reason": None,
        "source_manifest": manifest,
        "availability": availability,
    }


def acquire_selected_events(data_root, protocol_file, freeze_commit):
    protocol = verify_freeze(protocol_file, freeze_commit)
    root = Path(data_root)
    metadata = root / "holdout-2024-metadata"
    fetcher = BoundedFetcher(freeze_commit)
    fetcher.fetch(metadata, "jolpica-schedule", "https://api.jolpi.ca/ergast/f1/2024/?limit=100")
    fetcher.fetch(
        metadata,
        "openf1-sessions",
        "https://api.openf1.org/v1/sessions?year=2024&session_name=Race",
    )
    files, availability = [], {}
    schedule = _try_read(metadata, "jolpica-schedule", "metadata", files, availability)
    sessions = _try_read(metadata, "openf1-sessions", "metadata", files, availability)
    selected = []
    if schedule is None or sessions is None:
        result = {
            "freeze_commit": freeze_commit,
            "events": [],
            "missing_metadata": availability,
            "metadata_receipts": files,
            "reason": "No replacement sources or events permitted",
        }
        write_json(metadata / "selection.json", result)
        return result
    schedules = _schedule_rows(schedule[0])
    for reserved in protocol["events"]:
        matches = [
            r
            for r in schedules
            if r["raceName"] == reserved["name"]
            and r["Circuit"]["circuitId"] == reserved["circuit"]
        ]
        if len(matches) != 1:
            selected.append(
                {**reserved, "status": "missing", "reason": "schedule_identity_not_unique"}
            )
            continue
        race = matches[0]
        start = timestamp(f"{race['date']}T{race['time']}", "official scheduled start")
        matching_sessions = [
            s
            for s in sessions[0]
            if s["year"] == 2024
            and s["session_name"] == "Race"
            and s["session_type"] == "Race"
            and s["country_name"] == reserved["country"]
            and timestamp(s["date_start"], "session start") == start
        ]
        if len(matching_sessions) != 1:
            selected.append(
                {**reserved, "status": "missing", "reason": "session_identity_not_unique"}
            )
            continue
        session = matching_sessions[0]
        event = {
            **reserved,
            "round": int(race["round"]),
            "scheduled_start": start.isoformat(),
            "session": session,
            "status": "selected",
        }
        event_root = root / f"holdout-2024-{reserved['slug']}"
        event_root.mkdir(parents=True, exist_ok=True)
        write_json(event_root / "event.json", event)
        for kind in OPENF1_KINDS:
            url = (
                "https://api.openf1.org/v1/"
                + kind
                + "?"
                + urlencode({"session_key": session["session_key"]})
            )
            fetcher.fetch(event_root, f"openf1-{kind}", url)
        for endpoint in ("results", "laps", "pitstops"):
            offset, expected = 0, None
            for page in range(MAX_PAGES):
                url = (
                    f"https://api.jolpi.ca/ergast/f1/2024/{event['round']}/{endpoint}/?"
                    + urlencode({"limit": 100, "offset": offset})
                )
                stem = f"jolpica-{endpoint}-{offset:04d}"
                receipt = fetcher.fetch(event_root, stem, url)
                if (
                    receipt["http_and_connect"] not in {"200 200", "200 000"}
                    or receipt["curl_exit_code"]
                ):
                    break
                document = json.loads((event_root / f"{stem}.body").read_bytes())
                returned_race, returned_offset, limit, total = _page(
                    document, receipt, event, endpoint
                )
                if returned_offset != offset or (expected is not None and total != expected):
                    raise ValueError("Acquisition pagination changed; no retry")
                expected = total
                count = (
                    sum(len(lap["Timings"]) for lap in returned_race["Laps"])
                    if endpoint == "laps"
                    else len(returned_race["Results" if endpoint == "results" else "PitStops"])
                )
                if count > limit or (not count and total):
                    raise ValueError("Invalid pagination count; no retry")
                offset += count
                if offset == total:
                    break
                if offset > total:
                    raise ValueError("Pagination overrun; no retry")
            else:
                raise ValueError("Pagination page budget exceeded")
        selected.append(event)
    result = {
        "freeze_commit": freeze_commit,
        "events": selected,
        "metadata_receipts": files,
        "network_requests_this_run": fetcher.requests,
        "protocol_sha256": sha_file(protocol_file),
    }
    write_json(metadata / "selection.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args(argv)
    try:
        acquire_selected_events(args.data_root, args.freeze, args.freeze_commit)
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
