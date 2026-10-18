from copy import deepcopy

import pytest

from f1_strategy_optimizer.observation_import import inspect_import, select_horizon


def document():
    return {
        "schema_version": 1,
        "session_id": "synthetic",
        "required_streams": ["laps:16"],
        "records": [
            {
                "event_id": "lap-state",
                "source": "synthetic-receipt-fixture",
                "session_id": "synthetic",
                "stream": "laps:16",
                "kind": "lap_state",
                "event_time": "2024-01-01T00:00:10Z",
                "received_at": None,
                "sequence": 1,
                "revision": 0,
                "payload": {"current_lap": 5},
            }
        ],
    }


def inspect(d, at="2024-01-01T00:00:15Z", **kwargs):
    return inspect_import(d, at, **kwargs)


def test_unknown_receipt_never_becomes_observed_or_live():
    report = inspect(document())
    assert report["missing_streams"] == ["laps:16"]
    assert not report["snapshot_checks_passed"]
    report = inspect(document(), mode="historical_approximation", assumed_delay_seconds=3)
    assert report["snapshot_checks_passed"]
    assert report["snapshot"]["laps:16"]["received_at"] is None
    assert report["snapshot"]["laps:16"]["availability_basis"].startswith("assumed_delay")
    assert not report["publication_time_verified"]
    assert not report["model_eligible"] and not report["immediate_post_pit_target_enabled"]


def test_delayed_revision_does_not_rewrite_earlier_snapshot_and_is_order_independent():
    d = document()
    d["records"][0]["received_at"] = "2024-01-01T00:00:11Z"
    late = deepcopy(d["records"][0])
    late.update(
        revision=1, sequence=2, received_at="2024-01-01T00:00:20Z", payload={"current_lap": 6}
    )
    d["records"].append(late)
    first = inspect(d)
    d["records"].reverse()
    assert first["snapshot"] == inspect(d)["snapshot"]
    assert first["snapshot"]["laps:16"]["payload"]["current_lap"] == 5
    assert inspect(d, "2024-01-01T00:00:21Z")["snapshot"]["laps:16"]["revision"] == 1


def test_available_revision_with_missing_event_time_does_not_resurrect_old_value():
    d = document()
    d["records"][0]["received_at"] = "2024-01-01T00:00:11Z"
    d["records"].append(
        {
            **d["records"][0],
            "revision": 1,
            "sequence": 2,
            "event_time": None,
            "received_at": "2024-01-01T00:00:14Z",
        }
    )
    assert inspect(d)["missing_streams"] == ["laps:16"]


@pytest.mark.parametrize(
    "change,error",
    [
        ({"received_at": "2024-01-01T00:00:09Z"}, "precedes"),
        ({"event_time": "2024-01-01T00:00:10"}, "timezone"),
        ({"sequence": True}, "sequence"),
        ({"session_id": "other"}, "Mixed session"),
    ],
)
def test_invalid_clocks_identity_and_sequence_rejected(change, error):
    d = document()
    d["records"][0].update(change)
    with pytest.raises(ValueError, match=error):
        inspect(d)


def test_duplicate_conflict_rejected_and_null_stale_skew_are_explicit():
    d = document()
    d["records"][0]["received_at"] = "2024-01-01T00:00:11Z"
    d["records"].append({**d["records"][0], "payload": None})
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        inspect(d)
    d["records"] = d["records"][-1:]
    r = inspect(d, max_age_seconds=2)
    assert r["null_payload_streams"] == r["stale_streams"] == ["laps:16"]
    d["required_streams"].append("weather")
    d["records"].append(
        {
            **d["records"][0],
            "stream": "weather",
            "event_id": "weather",
            "event_time": "2024-01-01T00:00:01Z",
            "sequence": 2,
        }
    )
    r = inspect(d)
    assert r["snapshot_skew_seconds"] == 9 and not r["snapshot_checks_passed"]


def test_action_boundary_unknown_is_not_fabricated_and_reversed_boundary_rejected():
    d = document()
    d["records"][0].update(kind="action", effective_at=None, decided_at=None)
    assert inspect(d)["diagnostics"]["action_boundary_requires_external_validation"] == 1
    d["records"][0].update(effective_at="2024-01-01T00:00:01Z", decided_at="2024-01-01T00:00:02Z")
    with pytest.raises(ValueError, match="effective_at"):
        inspect(d)


def test_sequence_gaps_and_ambiguous_source_stream_are_blocked():
    d = document()
    d["sequence_semantics"] = "contiguous_per_stream"
    row = d["records"][0]
    row["received_at"] = "2024-01-01T00:00:11Z"
    d["records"].append({**row, "event_id": "other-state", "sequence": 3})
    assert not inspect(d)["snapshot_checks_passed"]
    d["records"][-1]["source"] = "other-provider"
    with pytest.raises(ValueError, match="distinguish sources"):
        inspect(d)


def test_explicit_horizon_never_retargets_immediate_or_assumes_missing_boundary():
    d = document()
    r = inspect(d, mode="historical_approximation", assumed_delay_seconds=3)
    args = {"driver_stream": "laps:16", "original_target_lap": 5}
    exact = select_horizon(r, horizon="immediate_post_pit", **args)
    later = select_horizon(r, horizon="first_unstarted_after_confirmation", **args)
    assert exact["selected_target_lap"] is None
    assert later["original_immediate_target_lap"] == 5
    assert later["candidate_target_lap"] == 6 and later["selected_target_lap"] is None
    assert later["availability_label"] == "retrospective assumed availability"
    row = d["records"][0]
    row.update(event_time="2024-01-01T00:00:15Z", received_at="2024-01-01T00:00:15Z")
    row["payload"]["not_started_through"] = "2024-01-01T00:00:15Z"
    selected = select_horizon(inspect(d), horizon="first_unstarted_after_confirmation", **args)
    assert selected["selected_target_lap"] == 6
    assert selected["prediction"] is None and not selected["model_eligible"]
