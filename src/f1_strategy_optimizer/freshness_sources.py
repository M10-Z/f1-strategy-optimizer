"""Predeclared optional-audit null handling for the newly reserved event only."""

from . import holdout_sources as sources


def load_candidate_archive(root, event):
    original_rows = sources._jolpica_rows

    def audit_rows(path, selected, endpoint, files, availability):
        if endpoint != "pitstops":
            return original_rows(path, selected, endpoint, files, availability)
        prior = sources._duration
        try:
            # Every raw receipt/page/identity validation remains in the original adapter.
            # Pit duration is an optional audit field, never a prediction feature.
            sources._duration = lambda value: None if value in ("", None) else prior(value)
            return original_rows(path, selected, endpoint, files, availability)
        finally:
            sources._duration = prior

    try:
        sources._jolpica_rows = audit_rows
        result = sources.load_holdout_archive(root, event)
    finally:
        sources._jolpica_rows = original_rows
    if result["archive"] is not None:
        result["archive"]["audit"]["missing_optional_pit_durations"] = [
            r for r in result["archive"]["pitstops"] if r["duration_seconds"] is None
        ]
    return result
