"""Stage 4: Evidence.

Deterministic lookup from an event_id (as cited by the model in Stage 3)
back to the exact raw log line it came from. No LLM involved.
"""

from dataclasses import dataclass

from quiet_hours.contracts import IncidentWindow


@dataclass(frozen=True)
class Citation:
    event_id: str
    source_file: str
    line_no: int
    raw_line: str


def build_index(window: IncidentWindow) -> dict[str, Citation]:
    return {
        e.event_id: Citation(
            event_id=e.event_id,
            source_file=e.source_file,
            line_no=e.line_no,
            raw_line=e.raw_line,
        )
        for e in window.events
    }


def resolve(event_ids: list[str], window: IncidentWindow) -> list[Citation]:
    """Resolve event_ids to citations, in the given order. Raises KeyError on
    an event_id that doesn't exist in the window (should not happen for a
    Diagnosis that passed validate()).
    """
    index = build_index(window)
    return [index[event_id] for event_id in event_ids]
