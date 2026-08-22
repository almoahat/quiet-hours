"""Stage 2: Localize.

Deterministic merge of events from every source into one sorted timeline,
then selection of the incident window: pad around the event that anchors the
incident. No LLM involved.
"""

from datetime import timedelta

from quiet_hours.contracts import IncidentWindow, NormalizedEvent

LEVEL_SEVERITY = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}

DEFAULT_PAD_BEFORE = timedelta(minutes=2)
# Sized to comfortably cover a multi-minute symptom burst plus whatever
# fires shortly after it (e.g. a circuit breaker trip a few seconds past
# the last failure in the burst), not just the anchoring event itself.
DEFAULT_PAD_AFTER = timedelta(minutes=6)

# An isolated ERROR-or-higher event is easy to mistake for the start of an
# incident when it's really just a one-off blip. Anchor selection prefers
# the first event that begins a dense burst -- several ERROR-or-higher
# events packed within a short span -- over an isolated one, since a burst
# is a much stronger signal that something real is happening. This doesn't
# change anything about our own generated incident (the quiet root-cause
# ERROR is itself immediately followed by the symptom storm, so it already
# qualifies as "begins a burst"), but it keeps the window from anchoring on
# unrelated noise if some shows up.
BURST_WINDOW = timedelta(seconds=60)
BURST_THRESHOLD = 3


def merge_events(event_lists: list[list[NormalizedEvent]]) -> list[NormalizedEvent]:
    """Flatten events from all sources and sort them by timestamp, ascending."""
    merged = [event for events in event_lists for event in events]
    merged.sort(key=lambda e: e.ts)
    return merged


def compute_stats(events: list[NormalizedEvent]) -> dict:
    stats = {"total": len(events), "by_source": {}, "by_service": {}, "by_host": {}, "by_level": {}}
    for e in events:
        for bucket, key in (
            ("by_source", e.source),
            ("by_service", e.service),
            ("by_host", e.host),
            ("by_level", e.level),
        ):
            stats[bucket][key] = stats[bucket].get(key, 0) + 1
    return stats


def _select_anchor(error_events: list[NormalizedEvent]) -> tuple[NormalizedEvent, int]:
    """Among ERROR-or-higher events (chronological order), pick the first one
    that begins a dense burst -- itself plus BURST_THRESHOLD-1 more within
    BURST_WINDOW of it. Falls back to the very first ERROR-or-higher event
    if none qualifies. Returns (anchor, burst_size).
    """
    for i, event in enumerate(error_events):
        burst_end = event.ts + BURST_WINDOW
        burst_size = sum(1 for e in error_events[i:] if e.ts <= burst_end)
        if burst_size >= BURST_THRESHOLD:
            return event, burst_size
    return error_events[0], 1


def select_window(
    events: list[NormalizedEvent],
    pad_before: timedelta = DEFAULT_PAD_BEFORE,
    pad_after: timedelta = DEFAULT_PAD_AFTER,
) -> IncidentWindow:
    """Pick the incident window: pad_before/pad_after around the anchor event
    (see _select_anchor). Falls back to the full timeline if nothing reaches
    ERROR severity.
    """
    if not events:
        raise ValueError("cannot select a window from an empty event list")

    error_events = [e for e in events if LEVEL_SEVERITY.get(e.level, 0) >= LEVEL_SEVERITY["ERROR"]]

    if not error_events:
        start, end = events[0].ts, events[-1].ts
        window_events = events
        trigger = "no ERROR-or-higher event found; window covers the full timeline"
    else:
        trigger_event, burst_size = _select_anchor(error_events)
        start, end = trigger_event.ts - pad_before, trigger_event.ts + pad_after
        window_events = [e for e in events if start <= e.ts <= end]
        if burst_size >= BURST_THRESHOLD:
            trigger = (
                f"first {trigger_event.level} event that begins a burst of {burst_size} "
                f"ERROR-or-higher events within {int(BURST_WINDOW.total_seconds())}s, at "
                f"{trigger_event.ts.isoformat()} ({trigger_event.event_id}): {trigger_event.message!r}"
            )
        else:
            trigger = (
                f"first {trigger_event.level} event at {trigger_event.ts.isoformat()} "
                f"({trigger_event.event_id}): {trigger_event.message!r}"
            )

    return IncidentWindow(
        start=start,
        end=end,
        events=window_events,
        trigger=trigger,
        stats=compute_stats(window_events),
    )


def build_incident_window(
    event_lists: list[list[NormalizedEvent]],
    pad_before: timedelta = DEFAULT_PAD_BEFORE,
    pad_after: timedelta = DEFAULT_PAD_AFTER,
) -> IncidentWindow:
    """Convenience wrapper: merge then select in one call."""
    return select_window(merge_events(event_lists), pad_before=pad_before, pad_after=pad_after)
