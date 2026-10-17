"""Strict, offline adapters for the archived 2023 Bahrain race.

The returned package is an archive, never a planner packet. OpenF1 rows retain
source semantics (including null unfinished laps and future stint ends). Receipt
and cross-source evidence live at package level. No CSV, profile-derived value,
network request, availability timestamp or final classification is imported.
"""

import hashlib
import json
import math
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .replay import timestamp

_MAX_BYTES = 20_000_000
_MAX_PAGES = 40
_MAX_RECORDS = 100_000


def _integer(value, name, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{name}: invalid integer")
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: invalid integer") from exc
    if str(result) != str(value) or result < minimum:
        raise ValueError(f"{name}: invalid integer")
    return result


def _positive_seconds(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name}: expected positive seconds")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: expected positive seconds") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name}: expected positive seconds")
    return result


def _duration(value):
    parts = str(value).split(":")
    if len(parts) not in (1, 2):
        raise ValueError("Invalid Jolpica duration")
    try:
        seconds = float(parts[-1])
    except ValueError as exc:
        raise ValueError("Invalid Jolpica duration") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Invalid Jolpica duration")
    if len(parts) == 2:
        if seconds >= 60:
            raise ValueError("Invalid Jolpica duration seconds")
        seconds += 60 * _integer(parts[0], "duration minutes")
    return _positive_seconds(seconds, "duration")


def _unique(rows, key, name):
    seen = set()
    for row in rows:
        value = key(row)
        if value in seen:
            raise ValueError(f"Duplicate {name} key: {value}")
        seen.add(value)


def _url(url, host, path):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != host or parsed.path != path:
        raise ValueError(f"Unexpected source URL: {url}")
    if parsed.fragment:
        raise ValueError("Source URL must not have a fragment")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(v) != 1 for v in query.values()):
        raise ValueError("Duplicate source URL query key")
    return {k: v[0] for k, v in query.items()}


def _read(root, filename, namespace, manifest):
    body_path = root / filename
    meta_path = body_path.with_suffix(".meta.json")
    if body_path.stat().st_size > _MAX_BYTES or meta_path.stat().st_size > _MAX_BYTES:
        raise ValueError(f"Archive file exceeds byte budget: {filename}")
    raw, meta_raw = body_path.read_bytes(), meta_path.read_bytes()
    receipt = json.loads(meta_raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != receipt.get("sha256") or len(raw) != receipt.get("bytes"):
        raise ValueError(f"SHA-256 or byte count mismatch: {filename}")
    if "http_code" in receipt:
        success = receipt["http_code"] == 200 and receipt.get("proxy_connect", 200) == 200
    else:
        success = receipt.get("http_and_connect") in ("200 200", "200 000")
    if not success or receipt.get("curl_exit_code", 0) != 0:
        raise ValueError(f"Unsuccessful archive receipt: {filename}")
    entry = {
        "file": f"{namespace}/{filename}",
        "sha256": digest,
        "bytes": len(raw),
        "metadata_sha256": hashlib.sha256(meta_raw).hexdigest(),
        "url": receipt["url"],
        "retrieved_at_utc": receipt.get("retrieved_at_utc"),
    }
    manifest.append(entry)
    return json.loads(raw), receipt, entry


def _openf1(root, kind, manifest, optional=False):
    filename = f"{kind}.body"
    if optional and not (root / filename).exists():
        return []
    rows, receipt, entry = _read(root, filename, "openf1", manifest)
    query = _url(receipt["url"], "api.openf1.org", f"/v1/{kind}")
    if kind == "sessions" and query != {
        "year": "2023",
        "country_name": "Bahrain",
        "session_name": "Race",
    }:
        raise ValueError("Unexpected OpenF1 session discovery filters")
    if kind != "sessions" and query != {"session_key": "7953"}:
        raise ValueError(f"Expected full session 7953 response: {kind}")
    if not isinstance(rows, list) or len(rows) > _MAX_RECORDS:
        raise ValueError(f"Expected bounded OpenF1 row list: {kind}")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Invalid OpenF1 row: {kind}")
        if row.get("session_key") != 7953 or row.get("meeting_key") != 1141:
            raise ValueError(f"Wrong OpenF1 session/meeting: {kind}")
    entry["count"] = len(rows)
    return rows


def _race(document, endpoint):
    mr = document["MRData"]
    _url(mr["url"], "api.jolpi.ca", f"/ergast/f1/2023/1/{endpoint}/")
    table = mr["RaceTable"]
    if str(table["season"]) != "2023" or str(table["round"]) != "1":
        raise ValueError("Wrong Jolpica RaceTable identity")
    races = table["Races"]
    if len(races) != 1:
        raise ValueError("Expected exactly one Jolpica race")
    race = races[0]
    if (
        str(race["season"]) != "2023"
        or str(race["round"]) != "1"
        or race["date"] != "2023-03-05"
        or race["Circuit"]["circuitId"] != "bahrain"
        or race["raceName"] != "Bahrain Grand Prix"
    ):
        raise ValueError("Wrong Jolpica race identity")
    if timestamp(f"{race['date']}T{race['time']}", "Jolpica race time") != timestamp(
        "2023-03-05T15:00:00Z", "race start"
    ):
        raise ValueError("Wrong Jolpica race start")
    return mr, race


def _page(document, receipt, endpoint):
    mr, race = _race(document, endpoint)
    offset = _integer(mr["offset"], "page offset")
    total = _integer(mr["total"], "page total")
    limit = _integer(mr["limit"], "page limit", 1)
    query = _url(receipt["url"], "api.jolpi.ca", f"/ergast/f1/2023/1/{endpoint}/")
    if set(query) - {"limit", "offset"}:
        raise ValueError("Unexpected pagination filter")
    if (
        _integer(query.get("offset", "0"), "URL offset") != offset
        or _integer(query.get("limit", "30"), "URL limit", 1) != limit
    ):
        raise ValueError("Jolpica URL pagination mismatch")
    if total > _MAX_RECORDS or limit > _MAX_RECORDS:
        raise ValueError("Jolpica record budget exceeded")
    return race, offset, total, limit


def _jolpica_pages(root, kind, manifest):
    files = sorted((root / "raw").glob(f"{kind}-*.json"))
    files = [p for p in files if not p.name.endswith(".meta.json")]
    if not files or len(files) > _MAX_PAGES:
        raise ValueError(f"Missing or excessive Jolpica {kind} pages")
    pages = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        document, receipt, entry = _read(root, relative, "jolpica", manifest)
        race, offset, total, limit = _page(document, receipt, kind)
        if path.stem != f"{kind}-{offset:04d}":
            raise ValueError("Jolpica filename/offset mismatch")
        batch = []
        if kind == "laps":
            for lap in race["Laps"]:
                number = _integer(lap["number"], "lap", 1)
                batch.extend(
                    {
                        "season": 2023,
                        "round": 1,
                        "driverId": timing["driverId"],
                        "lap": number,
                        "position": _integer(timing["position"], "position", 1),
                        "time": timing["time"],
                        "lap_duration": _duration(timing["time"]),
                    }
                    for timing in lap["Timings"]
                )
        else:
            batch = [
                {
                    "season": 2023,
                    "round": 1,
                    "driverId": row["driverId"],
                    "lap": _integer(row["lap"], "pit lap", 1),
                    "stop": _integer(row["stop"], "stop", 1),
                    "time": row["time"],
                    "duration": row["duration"],
                    "duration_seconds": _duration(row["duration"]),
                }
                for row in race["PitStops"]
            ]
        if len(batch) > limit or (not batch and total):
            raise ValueError("Invalid Jolpica page count")
        entry.update(offset=offset, count=len(batch), total=total, limit=limit)
        pages.append((offset, total, batch))
    rows, expected = [], pages[0][1]
    for offset, total, batch in sorted(pages):
        if offset != len(rows) or total != expected:
            raise ValueError("Jolpica pagination gap, overlap or changed total")
        rows.extend(batch)
    if len(rows) != expected:
        raise ValueError("Incomplete Jolpica pagination")
    key = "lap" if kind == "laps" else "stop"
    _unique(rows, lambda row: (row["driverId"], row[key]), f"Jolpica {kind}")
    return rows


def _name(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value).casefold() if c.isalnum())


def _drivers(root, raw_drivers, manifest):
    document, receipt, entry = _read(root, "jolpica-results.body", "openf1", manifest)
    race, offset, total, limit = _page(document, receipt, "results")
    results = race["Results"]
    if not results:
        raise ValueError("Missing historical driver identities")
    if offset != 0 or len(results) != total or len(results) > limit:
        raise ValueError("Incomplete historical driver identity results")
    entry.update(offset=offset, count=len(results), total=total, limit=limit)
    _unique(results, lambda r: _integer(r["number"], "result number", 1), "race number")
    _unique(results, lambda r: r["Driver"]["driverId"], "race driver id")
    _unique(raw_drivers, lambda r: r["driver_number"], "OpenF1 driver")
    by_number = {_integer(r["number"], "number", 1): r for r in results}
    if {d["driver_number"] for d in raw_drivers} != set(by_number):
        raise ValueError("OpenF1/Jolpica race driver fields differ")
    drivers = []
    for row in raw_drivers:
        number = _integer(row["driver_number"], "driver number", 1)
        identity = by_number[number]["Driver"]
        name = f"{identity['givenName']} {identity['familyName']}"
        source_name = (
            f"{row['first_name']} {row['last_name']}"
            if row.get("first_name") and row.get("last_name")
            else row["full_name"]
        )
        if _name(source_name) != _name(name):
            raise ValueError(f"Historical race number/name mismatch: {number}")
        if not row.get("team_name") or not identity.get("driverId"):
            raise ValueError("Missing historical team or driver identity")
        drivers.append(
            {
                "driver_number": number,
                "id": identity["driverId"],
                "team": row["team_name"],
                "name": row["full_name"],
            }
        )
    return sorted(drivers, key=lambda row: row["driver_number"])


def load_archive(openf1_dir, jolpica_dir):
    """Read verified raw receipts and return this race's source-separated archive.

    Missing full-session position/intervals yield empty arrays and audit warnings;
    minute samples are never substituted. All required files and each supplied
    full-session file fail closed on integrity, event identity or duplicate keys.
    ``audit.completed_lap_records`` excludes null lap durations. Neither the
    archive nor its audit asserts historical online availability or replay readiness.
    """
    of_root, jp_root, files = Path(openf1_dir), Path(jolpica_dir), []
    sessions = _openf1(of_root, "sessions", files)
    if len(sessions) != 1:
        raise ValueError("Expected exactly one OpenF1 race session")
    session = sessions[0]
    if (
        session["year"] != 2023
        or session["country_name"] != "Bahrain"
        or session["session_name"] != "Race"
        or session["session_type"] != "Race"
        or timestamp(session["date_start"], "session.date_start")
        != timestamp("2023-03-05T15:00:00Z", "race start")
    ):
        raise ValueError("Wrong OpenF1 race identity")
    drivers = _drivers(of_root, _openf1(of_root, "drivers", files), files)
    archive = {"session": session, "drivers": drivers}
    mapping = {row["driver_number"]: row["id"] for row in drivers}
    for kind in ("laps", "stints", "weather", "race_control", "position", "intervals"):
        rows = _openf1(of_root, kind, files, optional=kind in {"position", "intervals"})
        for row in rows:
            if row.get("driver_number") is not None and row["driver_number"] not in mapping:
                raise ValueError(f"Unknown OpenF1 driver: {kind}")
            if kind in {"laps", "stints"}:
                _integer(row["driver_number"], "driver_number", 1)
            if kind == "laps":
                _integer(row["lap_number"], "lap_number", 1)
                timestamp(row["date_start"], "lap.date_start")
                if row.get("lap_duration") is not None:
                    _positive_seconds(row["lap_duration"], "lap_duration")
            elif kind == "stints":
                _integer(row["stint_number"], "stint_number", 1)
                start = _integer(row["lap_start"], "stint.lap_start", 1)
                end = _integer(row["lap_end"], "stint.lap_end", 1)
                _integer(row["tyre_age_at_start"], "stint.tyre_age_at_start")
                if end < start or not row.get("compound"):
                    raise ValueError("Invalid archival stint bounds or compound")
            else:
                timestamp(row["date"], f"{kind}.date")
        if kind in {"laps", "stints"}:
            suffix = "lap_number" if kind == "laps" else "stint_number"
            _unique(rows, lambda r: (r["driver_number"], r[suffix]), kind)
        elif kind in {"position", "intervals"}:
            _unique(rows, lambda r: (r["driver_number"], timestamp(r["date"], "date")), kind)
        elif kind == "weather":
            _unique(rows, lambda r: timestamp(r["date"], "date"), kind)
        else:
            _unique(rows, lambda r: json.dumps(r, sort_keys=True), kind)
        archive[kind] = rows
    jp_laps = _jolpica_pages(jp_root, "laps", files)
    archive["jolpica_laps"] = jp_laps
    archive["pitstops"] = _jolpica_pages(jp_root, "pitstops", files)
    ids = set(mapping.values())
    if any(r["driverId"] not in ids for r in jp_laps + archive["pitstops"]):
        raise ValueError("Unknown Jolpica lap/pit driver")
    of_laps = {(mapping[r["driver_number"]], r["lap_number"]): r for r in archive["laps"]}
    jp_by_key = {(r["driverId"], r["lap"]): r for r in jp_laps}
    if any((r["driverId"], r["lap"]) not in jp_by_key for r in archive["pitstops"]):
        raise ValueError("Jolpica pit record has no matching completed lap")
    differences = []
    for key in sorted(set(of_laps) & set(jp_by_key)):
        of_duration, jp_duration = of_laps[key]["lap_duration"], jp_by_key[key]["lap_duration"]
        if of_duration is not None and abs(of_duration - jp_duration) > 0.001000001:
            differences.append(
                {
                    "driverId": key[0],
                    "lap_number": key[1],
                    "openf1_seconds": of_duration,
                    "jolpica_seconds": jp_duration,
                    "jolpica_minus_openf1_seconds": round(jp_duration - of_duration, 6),
                }
            )
    nulls = [list(key) for key, r in sorted(of_laps.items()) if r["lap_duration"] is None]
    files.sort(key=lambda row: row["file"])
    manifest = {"schema_version": 1, "event": "2023-1-bahrain", "files": files}
    manifest["sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    archive["source_manifest"] = manifest
    archive["audit"] = {
        "event": "2023-1-bahrain",
        "session_key": 7953,
        "identity_method": "same-race Results.number plus normalized full name",
        "counts": {key: len(value) for key, value in archive.items() if isinstance(value, list)},
        "completed_lap_records": len(of_laps) - len(nulls),
        "null_duration_laps": nulls,
        "openf1_only_keys": [list(k) for k in sorted(set(of_laps) - set(jp_by_key))],
        "jolpica_only_keys": [list(k) for k in sorted(set(jp_by_key) - set(of_laps))],
        "duration_disagreements": differences,
        "first_lap_disagreements": sum(r["lap_number"] == 1 for r in differences),
        "coverage": {
            kind: "full_session_response" if archive[kind] else "missing_full_session_response"
            for kind in ("position", "intervals")
        },
        "replay_ready": False,
        "limitations": [
            "date_start is approximate event time, not historical publication/availability time",
            "null-duration laps are unfinished observations, never completed or zero-duration laps",
            "first-lap durations retain separate source definitions; no blending",
            "stint lap_end and later stints are future archive information",
            "pit lap/time does not establish an exact pit-action boundary or changed compound",
            "full-session asynchronous updates do not prove a complete synchronized field",
            "missing weather or control messages do not establish DRY or GREEN",
            "source_manifest and audit are archival evidence, never planner features",
        ],
    }
    return archive
