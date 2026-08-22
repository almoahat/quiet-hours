import os
from datetime import UTC, datetime

from quiet_hours.parsers import cloudwatch

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "cloudwatch_sample.json")


def test_parses_every_line():
    events = cloudwatch.parse(FIXTURE)
    assert len(events) == 20


def test_field_mapping_for_root_cause_line():
    events = cloudwatch.parse(FIXTURE)
    error_events = [e for e in events if e.level == "ERROR"]
    assert len(error_events) == 1

    e = error_events[0]
    assert e.source == "cloudwatch"
    assert e.service == "order-service"
    assert e.host == "order-service-390062-b2lkk"
    assert e.message == "connection pool exhausted: active=20 idle=0 waiting=37"
    assert e.attrs == {
        "logStreamName": "/ecs/order-service",
        "pool": "payments-db",
        "active": 20,
        "idle": 0,
        "waiting": 37,
    }


def test_root_cause_warn_and_error_land_on_the_same_pod():
    """Pods are stable, reused across events -- and specifically, the two
    root-cause events (checkout-timeout WARN, then pool-exhausted ERROR)
    must be the same instance having the same problem, not two different
    pods that happen to log similar messages.
    """
    events = cloudwatch.parse(FIXTURE)
    warn = next(e for e in events if e.level == "WARN" and e.service == "order-service")
    error = next(e for e in events if e.level == "ERROR" and e.service == "order-service")
    assert warn.host == error.host


def test_utc_conversion():
    events = cloudwatch.parse(FIXTURE)
    e = events[0]
    assert e.ts.tzinfo is not None
    assert e.ts.utcoffset().total_seconds() == 0
    # epoch ms 1787379510000 -> 2026-08-22T06:38:30Z
    assert e.ts == datetime.fromtimestamp(1787379510000 / 1000, tz=UTC)


def test_event_id_format():
    events = cloudwatch.parse(FIXTURE)
    for i, e in enumerate(events, start=1):
        assert e.event_id == f"cloudwatch:{i:04d}"
        assert e.line_no == i
        assert e.source_file == FIXTURE
