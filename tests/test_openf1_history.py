"""History selection, bounded fetches and isolation from frozen prediction."""

import io
import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from f1_strategy_optimizer.openf1_history import (
    MAX_RESPONSE_BYTES,
    HistoryAPI,
    HistoryError,
    _NoRedirect,
)
from f1_strategy_optimizer.workbench import Handler, Workbench

NOW = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)
SESSION = {
    "session_key": 7953,
    "meeting_key": 1141,
    "year": 2023,
    "session_type": "Race",
    "session_name": "Race",
    "country_name": "Bahrain",
    "location": "Sakhir",
    "date_start": "2023-03-05T15:00:00+00:00",
    "date_end": "2023-03-05T17:00:00+00:00",
}
DRIVER = {
    "session_key": 7953,
    "meeting_key": 1141,
    "driver_number": 16,
    "full_name": "Charles LECLERC",
    "name_acronym": "LEC",
    "team_name": "Ferrari",
}
LAP = {
    "session_key": 7953,
    "meeting_key": 1141,
    "driver_number": 16,
    "lap_number": 1,
    "date_start": "2023-03-05T15:03:38+00:00",
    "lap_duration": 99.0,
    "is_pit_out_lap": False,
}


class Response(io.BytesIO):
    status = 200

    def __init__(self, url, data, headers=None):
        super().__init__(data)
        self.url = url
        self.headers = headers or {}

    def geturl(self):
        return self.url


class Opener:
    def __init__(self):
        self.rows = {
            "sessions": [deepcopy(SESSION)],
            "drivers": [deepcopy(DRIVER)],
            "laps": [deepcopy(LAP)],
            "stints": [],
        }
        self.calls = []
        self.fail = False
        self.raw = None
        self.headers = {}

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        assert timeout == 12
        assert request.full_url.startswith("https://api.openf1.org/v1/")
        assert "Authorization" not in request.headers
        if self.fail:
            raise URLError("offline")
        kind = urlsplit(request.full_url).path.rsplit("/", 1)[1]
        data = self.raw if self.raw is not None else json.dumps(self.rows[kind]).encode()
        return Response(request.full_url, data, self.headers)


def api():
    opener = Opener()
    return HistoryAPI(opener=opener, now=lambda: NOW, min_interval=0), opener


def test_offline_initialization_and_historical_times_are_separate():
    service, opener = api()
    assert opener.calls == []
    result = service.history(7953, 16)
    assert len(opener.calls) == 4
    assert result["laps"][0]["date_start"].startswith("2023-")
    assert result["source"]["received_at_utc"].startswith("2026-")
    assert result["source"]["availability_basis"] == "post_event_download"
    assert result["source"]["live"] is False
    assert result["forecast_created"] is False
    assert result["source"]["source_publication_verified"] is False
    assert all(row["raw_sha256"] for row in result["source"]["receipts"])
    before = result["source"]["received_at_utc"]
    result["laps"][0]["lap_duration"] = 1
    again = service.history(7953, 16)
    assert len(opener.calls) == 4
    assert again["laps"][0]["lap_duration"] == 99.0
    assert again["source"]["cache_status"] == "hit"
    assert again["source"]["received_at_utc"] == before


@pytest.mark.parametrize(
    "selector",
    ["latest", "../sessions", "https://evil.test", "7953&year=2024", -1, True, "1.2", " 7953"],
)
def test_invalid_selectors_never_fetch(selector):
    service, opener = api()
    with pytest.raises(HistoryError):
        service.drivers(selector)
    assert opener.calls == []


@pytest.mark.parametrize("session", [9539, 9566, 9574, 9582])
def test_known_sealed_sessions_never_fetch(session):
    service, opener = api()
    with pytest.raises(HistoryError, match="封存"):
        service.history(session, 16)
    assert opener.calls == []


@pytest.mark.parametrize("change", ["future", "live", "cancelled", "protected_country", "not_race"])
def test_session_policy_blocks_before_driver_or_lap_requests(change):
    service, opener = api()
    row = opener.rows["sessions"][0]
    if change == "future":
        row.update(year=2026, date_start="2026-12-01T12:00:00Z", date_end="2026-12-01T15:00:00Z")
    elif change == "live":
        row.update(year=2026, date_start="2026-11-03T22:00:00Z", date_end="2026-11-04T01:00:00Z")
    elif change == "cancelled":
        row["is_cancelled"] = True
    elif change == "protected_country":
        row.update(year=2024, country_name="Belgium")
    else:
        row["session_type"] = "Practice"
    with pytest.raises(HistoryError):
        service.drivers(7953)
    assert len(opener.calls) == 1
    assert "/sessions?" in opener.calls[0]


def test_sessions_show_blocked_rows_without_loading_outcomes():
    service, opener = api()
    opener.rows["sessions"][0].update(year=2024, session_key=9574, country_name="Belgium")
    result = service.sessions(2024)
    assert result["races"][0]["available"] is False
    assert "封存" in result["races"][0]["blocked_reason"]
    assert len(opener.calls) == 1


def test_failure_uses_only_same_query_cache_and_preserves_receipt():
    service, opener = api()
    before = service.history(7953, 16)
    service.ttl = -1
    opener.fail = True
    after = service.history(7953, 16)
    assert after["source"]["cache_status"] == "stale_fallback"
    assert after["source"]["received_at_utc"] == before["source"]["received_at_utc"]
    assert after["source"]["warnings"]
    calls = len(opener.calls)
    with pytest.raises(HistoryError):
        service.drivers(9999)
    assert len(opener.calls) == calls + 1  # No automatic retry or alternative endpoint.


@pytest.mark.parametrize("kind", ["body", "content_length", "nan"])
def test_response_limits_and_nonstandard_json_are_rejected(kind):
    service, opener = api()
    if kind == "body":
        opener.raw = b" " * (MAX_RESPONSE_BYTES + 1)
    elif kind == "content_length":
        opener.headers = {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}
    else:
        opener.raw = b'[{"value":NaN}]'
    with pytest.raises(HistoryError):
        service.sessions(2023)
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    "change", ["wrong_session", "wrong_driver", "duplicate_lap", "negative_time"]
)
def test_foreign_or_invalid_laps_are_not_returned(change):
    service, opener = api()
    lap = opener.rows["laps"][0]
    if change == "wrong_session":
        lap["session_key"] = 9539
    elif change == "wrong_driver":
        lap["driver_number"] = 44
    elif change == "duplicate_lap":
        opener.rows["laps"].append(deepcopy(lap))
    else:
        lap["lap_duration"] = -1
    with pytest.raises(HistoryError):
        service.history(7953, 16)


def test_missing_lap_duration_stays_null_and_unknown_driver_does_not_fetch_laps():
    service, opener = api()
    opener.rows["laps"][0]["lap_duration"] = None
    assert service.history(7953, 16)["laps"][0]["lap_duration"] is None
    before = len(opener.calls)
    with pytest.raises(HistoryError, match="车手"):
        service.history(7953, 44)
    assert len(opener.calls) == before


def test_rate_budget_and_redirect_are_not_retried():
    service, opener = api()
    service.ttl = -1
    for _ in range(30):
        service.sessions(2023)
    with pytest.raises(HistoryError) as error:
        service.sessions(2023)
    assert error.value.status == 429
    assert len(opener.calls) == 30
    with pytest.raises(HistoryError, match="重定向"):
        _NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test")


def test_http_history_is_separate_from_frozen_cases_and_rejects_extra_params():
    app = Workbench()
    service, opener = api()
    app.history_api = service
    frozen_before = deepcopy(app.cases)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.app = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(
            base + "/api/openf1/history?session_key=7953&driver_number=16", timeout=5
        ) as r:
            result = json.load(r)
        assert result["driver"]["driver_number"] == 16
        assert app.cases == frozen_before
        assert app.jobs == {} and app.revealed == {}
        before = len(opener.calls)
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/openf1/drivers?session_key=7953&session_key=9574", timeout=5)
        assert error.value.code == 400
        assert len(opener.calls) == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "values",
    [
        {"stint_number": -1},
        {"stint_number": True},
        {"tyre_age_at_start": -1},
        {"lap_start": 10, "lap_end": 5},
        {"lap_start": "3"},
        {"compound": {}},
        {"compound": ""},
        {"lap_end": 501},
    ],
)
def test_invalid_optional_stint_fields_are_rejected(values):
    service, opener = api()
    opener.rows["stints"] = [{**DRIVER, **values}]
    with pytest.raises(HistoryError):
        service.history(7953, 16)


def test_missing_stint_fields_stay_null():
    service, opener = api()
    opener.rows["stints"] = [
        {
            **DRIVER,
            "stint_number": None,
            "lap_start": None,
            "lap_end": None,
            "compound": None,
            "tyre_age_at_start": None,
        }
    ]
    row = service.history(7953, 16)["stints"][0]
    assert all(
        row[name] is None
        for name in ("stint_number", "lap_start", "lap_end", "compound", "tyre_age_at_start")
    )


def test_network_in_flight_does_not_block_cache_or_queue_requests():
    service, opener = api()
    service.sessions(2023)
    service.history(7953, 16)
    for url, entry in service.cache.items():
        if "/laps?" in url:
            entry["saved_at"] = -1e12
    entered, release = threading.Event(), threading.Event()
    original = opener.open
    results, errors = [], []

    def blocking(request, timeout):
        if "/laps?" in request.full_url:
            entered.set()
            assert release.wait(5)
        return original(request, timeout)

    def work():
        try:
            results.append(service.history(7953, 16))
        except Exception as exc:
            errors.append(exc)

    opener.open = blocking
    thread = threading.Thread(target=work)
    thread.start()
    assert entered.wait(5)
    try:
        assert service.sessions(2023)["source"]["cache_status"] == "hit"
        before = len(opener.calls)
        with pytest.raises(HistoryError) as error:
            service.sessions(2024)
        assert error.value.status == 429
        assert len(opener.calls) == before
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors and results


def test_ttl_and_lru_cache_entry_eviction(monkeypatch):
    from f1_strategy_optimizer import openf1_history as module

    service, opener = api()
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    service.ttl = 10
    service.sessions(2023)
    service.sessions(2023)
    assert len(opener.calls) == 1
    clock[0] += 11
    assert service.sessions(2023)["source"]["cache_status"] == "miss"
    assert len(opener.calls) == 2
    monkeypatch.setattr(module, "MAX_CACHE_ENTRIES", 1)
    service.drivers(7953)
    assert len(service.cache) == 1
    assert service.cache_bytes == sum(item["size"] for item in service.cache.values())
    before = len(opener.calls)
    service.sessions(2023)
    assert len(opener.calls) == before + 1


def test_cache_byte_budget_evicts_oversized_single_entry(monkeypatch):
    from f1_strategy_optimizer import openf1_history as module

    service, opener = api()
    monkeypatch.setattr(module, "MAX_CACHE_BYTES", 1)
    service.sessions(2023)
    assert not service.cache and service.cache_bytes == 0
    service.sessions(2023)
    assert len(opener.calls) == 2


def test_upstream_429_has_no_automatic_retry():
    service, opener = api()

    def limited(request, timeout):
        opener.calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    opener.open = limited
    with pytest.raises(HistoryError) as error:
        service.sessions(2023)
    assert error.value.status == 429
    assert len(opener.calls) == 1


def test_slow_body_hits_monotonic_deadline(monkeypatch):
    from f1_strategy_optimizer import openf1_history as module

    service, opener = api()
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    original = opener.open

    def slow(request, timeout):
        response = original(request, timeout)
        read = response.read1

        def chunk(size):
            clock[0] += 13
            return read(size)

        response.read1 = chunk
        return response

    opener.open = slow
    with pytest.raises(HistoryError, match="超时"):
        service.sessions(2023)
    assert not service.cache


@pytest.mark.parametrize("interleaving", ["evicted", "refreshed"])
def test_cache_snapshot_is_rechecked_after_acquiring_network_gate(monkeypatch, interleaving):
    from f1_strategy_optimizer import openf1_history as module

    service, opener = api()
    service.sessions(2023)
    service.ttl = -1
    monkeypatch.setattr(module, "MAX_CACHE_ENTRIES", 1)
    paused, resume = threading.Event(), threading.Event()
    original_gate = service.network_gate

    class PausingGate:
        def acquire(self, blocking=False):
            if threading.current_thread().name == "stale-caller":
                paused.set()
                assert resume.wait(5)
            return original_gate.acquire(blocking=blocking)

        def release(self):
            return original_gate.release()

    service.network_gate = PausingGate()
    results, errors = [], []

    def work():
        try:
            results.append(service.sessions(2023))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=work, name="stale-caller")
    thread.start()
    assert paused.wait(5)
    try:
        if interleaving == "evicted":
            service._fetch("sessions", {"session_key": 7953}, 1)
        else:
            service.sessions(2023)
            service.ttl = 3600
    finally:
        resume.set()
        thread.join(5)
    assert not thread.is_alive() and not errors and results
    assert service.cache_bytes == sum(entry["size"] for entry in service.cache.values())
    assert service.cache_bytes > 0 and len(service.cache) == 1
    assert len(opener.calls) == (3 if interleaving == "evicted" else 2)
    if interleaving == "refreshed":
        assert results[0]["source"]["cache_status"] == "hit"
