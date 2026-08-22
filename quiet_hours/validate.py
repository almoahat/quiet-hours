"""Sanity checks on a Diagnosis before it's trusted.

Pure functions, no I/O. Used by diagnose.py to decide whether a retry is
needed and by run.py to decide whether to trust the final result.
"""

from quiet_hours.contracts import Diagnosis, IncidentWindow


def validate(d: Diagnosis, w: IncidentWindow) -> list[str]:
    """Return a list of problem strings; empty means valid."""
    problems = []
    valid_ids = {e.event_id for e in w.events}

    for i, claim in enumerate(d.claims):
        if not claim.evidence:
            problems.append(f"claim {i} ({claim.statement!r}) has empty evidence")
        for event_id in claim.evidence:
            if event_id not in valid_ids:
                problems.append(f"claim {i} references unknown event_id {event_id!r}")

    for event_id in d.unexplained:
        if event_id not in valid_ids:
            problems.append(f"unexplained references unknown event_id {event_id!r}")

    if d.outcome == "root_cause_identified" and d.root_cause is None:
        problems.append("outcome is 'root_cause_identified' but root_cause is None")

    return problems
