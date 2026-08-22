"""render_window() is what the model actually sees -- it must withhold the
trigger (names the root cause) and the full host breakdown (context waste),
while the IncidentWindow object itself keeps both for logging/the UI.
"""

from datetime import UTC, datetime

from quiet_hours.contracts import IncidentWindow, NormalizedEvent
from quiet_hours.diagnose import render_window


def _event(event_id, host, level="ERROR", message="pool exhausted"):
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    return NormalizedEvent(
        event_id=event_id,
        ts=ts,
        ts_raw=ts.isoformat(),
        source="cloudwatch",
        service="order-service",
        host=host,
        level=level,
        message=message,
        source_file="fake.json",
        line_no=1,
        raw_line="{}",
        attrs={},
    )


def _window():
    events = [_event(f"cloudwatch:{i:04d}", host=f"pod-{i}") for i in range(5)]
    stats = {
        "total": 5,
        "by_source": {"cloudwatch": 5},
        "by_service": {"order-service": 5},
        "by_host": {f"pod-{i}": 1 for i in range(5)},
        "by_level": {"ERROR": 5},
    }
    return IncidentWindow(
        start=events[0].ts,
        end=events[0].ts,
        events=events,
        trigger="first ERROR event at ... (cloudwatch:0000): 'pool exhausted'",
        stats=stats,
    )


def test_rendered_text_omits_trigger():
    window = _window()
    text = render_window(window)
    assert "Trigger" not in text
    assert window.trigger not in text
    # trigger stays on the object itself, for logging/the UI
    assert window.trigger


def test_rendered_text_omits_per_host_breakdown_but_keeps_a_count():
    window = _window()
    text = render_window(window)
    stats_line = next(line for line in text.splitlines() if line.startswith("Stats:"))
    assert "by_host" not in stats_line  # no per-host breakdown in the stats block
    assert "pod-" not in stats_line
    assert "distinct_hosts': 5" in stats_line or 'distinct_hosts": 5' in stats_line
    # the full breakdown stays on the object itself
    assert window.stats["by_host"] == {f"pod-{i}": 1 for i in range(5)}


def test_rendered_text_keeps_source_service_and_level_counts():
    window = _window()
    text = render_window(window)
    stats_line = next(line for line in text.splitlines() if line.startswith("Stats:"))
    assert "by_source" in stats_line
    assert "by_service" in stats_line
    assert "by_level" in stats_line
    assert "cloudwatch" in text  # from by_source, not from event lines only
    assert "order-service" in stats_line  # from by_service
