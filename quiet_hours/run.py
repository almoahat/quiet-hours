"""CLI: wire the four stages together end to end.

Usage:
    poetry run python -m quiet_hours.run \
        --cloudwatch data/generated/cloudwatch.json \
        --splunk data/generated/splunk.log

LLM_URL and LLM_MODEL configure the Stage 3 endpoint (see diagnose.py).
"""

import argparse
from datetime import timedelta

from quiet_hours.diagnose import diagnose
from quiet_hours.evidence import resolve
from quiet_hours.parsers import REGISTRY
from quiet_hours.timeline import DEFAULT_PAD_AFTER, DEFAULT_PAD_BEFORE, build_incident_window
from quiet_hours.validate import validate


def print_timeline(window):
    print(f"=== Incident window: {window.start.isoformat()} .. {window.end.isoformat()} ===")
    print(f"Trigger: {window.trigger}")
    print(f"Stats: {window.stats}")
    print(f"Events in window: {len(window.events)}\n")
    for e in window.events:
        print(f"[{e.event_id}] {e.ts.isoformat()} {e.source} {e.service}@{e.host} {e.level}: {e.message}")
    print()


def print_diagnosis(diagnosis, window):
    if diagnosis is None:
        print("=== Diagnosis: FAILED (model did not return a valid Diagnosis after retry) ===")
        return

    print(f"=== Diagnosis: {diagnosis.outcome} (confidence: {diagnosis.confidence}) ===")
    print(f"Root cause: {diagnosis.root_cause}\n")

    for claim in diagnosis.claims:
        print(f"Claim: {claim.statement}")
        for citation in resolve(claim.evidence, window):
            print(f"    - [{citation.event_id}] {citation.source_file}:{citation.line_no}  {citation.raw_line}")
        print()

    if diagnosis.unexplained:
        print("Unexplained events:")
        for citation in resolve(diagnosis.unexplained, window):
            print(f"    - [{citation.event_id}] {citation.source_file}:{citation.line_no}  {citation.raw_line}")

    problems = validate(diagnosis, window)
    if problems:
        print("\nValidation problems (should not happen post-retry):")
        for p in problems:
            print(f"    - {p}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for source in REGISTRY:
        parser.add_argument(f"--{source}", required=True, help=f"path to a {source} log file")
    parser.add_argument("--pad-before-min", type=float, default=DEFAULT_PAD_BEFORE.total_seconds() / 60)
    parser.add_argument("--pad-after-min", type=float, default=DEFAULT_PAD_AFTER.total_seconds() / 60)
    args = parser.parse_args()

    event_lists = []
    for source, parse in REGISTRY.items():
        path = getattr(args, source)
        event_lists.append(parse(path))

    window = build_incident_window(
        event_lists,
        pad_before=timedelta(minutes=args.pad_before_min),
        pad_after=timedelta(minutes=args.pad_after_min),
    )
    print_timeline(window)

    diagnosis = diagnose(window)
    print_diagnosis(diagnosis, window)


if __name__ == "__main__":
    main()
