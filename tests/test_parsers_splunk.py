import os
from datetime import UTC, datetime

from quiet_hours.parsers import splunk

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "splunk_sample.log")


def test_parses_every_line():
    events = splunk.parse(FIXTURE)
    assert len(events) == 20


def test_field_mapping_for_circuit_breaker_line():
    events = splunk.parse(FIXTURE)
    warn_events = [e for e in events if e.level == "WARN"]
    assert len(warn_events) == 1

    e = warn_events[0]
    assert e.source == "splunk"
    assert e.service == "order-service"  # derived from upstream=order-service, not a "service" key
    assert e.host == "gw-prod-01"
    assert e.attrs == {"source": "/var/log/gateway/access.log", "sourcetype": "gateway_access"}
    assert e.message == "circuit breaker OPEN for upstream 'order-service' after 50 consecutive failures"


def test_utc_conversion_applies_fixed_offset():
    events = splunk.parse(FIXTURE)
    e = events[0]
    assert e.ts_raw == "08/22/2026 02:25:32.321 -0400"
    assert e.ts.tzinfo is not None
    assert e.ts.utcoffset().total_seconds() == 0
    assert e.ts == datetime(2026, 8, 22, 6, 25, 32, 321000, tzinfo=UTC)


def test_event_id_format():
    events = splunk.parse(FIXTURE)
    for i, e in enumerate(events, start=1):
        assert e.event_id == f"splunk:{i:04d}"
        assert e.line_no == i
        assert e.source_file == FIXTURE
