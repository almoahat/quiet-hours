"""Verifies the incident window anchors on the real incident, not on noise,
against the full ~424-line generated dataset (regenerated fresh here rather
than relying on the gitignored data/generated/ output existing on disk)."""

import importlib.util
import json
from pathlib import Path

from quiet_hours.parsers import cloudwatch, splunk
from quiet_hours.timeline import build_incident_window

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_generate_logs():
    spec = importlib.util.spec_from_file_location("generate_logs", REPO_ROOT / "scripts" / "generate_logs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_window(tmp_path, seed=42):
    generate_logs = _load_generate_logs()
    cw_lines, sp_lines, root_cause_event_id = generate_logs.generate(seed)

    cw_path = tmp_path / "cloudwatch.json"
    sp_path = tmp_path / "splunk.log"
    cw_path.write_text("\n".join(cw_lines) + "\n")
    sp_path.write_text("\n".join(sp_lines) + "\n")

    window = build_incident_window([cloudwatch.parse(str(cw_path)), splunk.parse(str(sp_path))])
    return window, root_cause_event_id


def test_window_contains_the_ground_truth_root_cause(tmp_path):
    window, root_cause_event_id = _build_window(tmp_path)
    window_ids = {e.event_id for e in window.events}
    assert root_cause_event_id in window_ids


def test_window_contains_the_circuit_breaker_event(tmp_path):
    window, _ = _build_window(tmp_path)
    breaker_events = [e for e in window.events if "circuit breaker" in e.message.lower()]
    assert len(breaker_events) == 1


def test_trigger_names_the_anchoring_event(tmp_path):
    window, root_cause_event_id = _build_window(tmp_path)
    # The root-cause ERROR is immediately followed by the symptom storm, so
    # it qualifies as "begins a dense burst" and anchors the window itself
    # -- not some unrelated noise earlier or later in the timeline.
    assert root_cause_event_id in window.trigger


def test_no_unrelated_error_precedes_the_real_incident(tmp_path):
    """Ground-truth check: nothing at ERROR-or-higher severity fires before
    the recorded root cause anywhere in the full generated corpus.
    """
    generate_logs = _load_generate_logs()
    cw_lines, sp_lines, root_cause_event_id = generate_logs.generate(seed=42)

    cw_path = tmp_path / "cloudwatch.json"
    sp_path = tmp_path / "splunk.log"
    cw_path.write_text("\n".join(cw_lines) + "\n")
    sp_path.write_text("\n".join(sp_lines) + "\n")

    all_events = cloudwatch.parse(str(cw_path)) + splunk.parse(str(sp_path))
    all_events.sort(key=lambda e: e.ts)

    root_cause = next(e for e in all_events if e.event_id == root_cause_event_id)
    earlier_errors = [e for e in all_events if e.ts < root_cause.ts and e.level in ("ERROR", "FATAL")]
    assert earlier_errors == []


def test_incident_fixture_root_cause_matches_generator(tmp_path):
    """Sanity check that the committed ground-truth fixture agrees with what
    the generator itself reports for the default seed.
    """
    generate_logs = _load_generate_logs()
    _, _, root_cause_event_id = generate_logs.generate(seed=42)

    with open(REPO_ROOT / "data" / "fixtures" / "incident.json") as f:
        truth = json.load(f)

    assert truth["root_cause_event_id"] == root_cause_event_id
