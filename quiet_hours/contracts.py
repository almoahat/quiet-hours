"""Shared data contracts passed between the four pipeline stages.

Stage 1 Normalize -> NormalizedEvent
Stage 2 Localize  -> IncidentWindow
Stage 3 Diagnose  -> Diagnosis (the only stage that calls an LLM)
Stage 4 Evidence  -> resolves event_id back to a raw log line
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str  # "splunk:0412" = f"{source}:{line_no:04d}"
    ts: datetime  # UTC, timezone-aware
    ts_raw: str  # original timestamp string
    source: str  # "cloudwatch" | "splunk"
    service: str
    host: str
    level: str  # DEBUG|INFO|WARN|ERROR|FATAL
    message: str
    source_file: str
    line_no: int
    raw_line: str
    attrs: dict


@dataclass
class IncidentWindow:
    start: datetime
    end: datetime
    events: list[NormalizedEvent]  # merged, sorted by ts ascending
    trigger: str  # why this window was chosen
    stats: dict  # counts by source, service, host, level


@dataclass
class Claim:
    statement: str
    evidence: list[str]  # event_ids, never empty


@dataclass
class Diagnosis:
    outcome: str  # "root_cause_identified" | "insufficient_evidence"
    root_cause: str | None
    confidence: str  # "high" | "medium" | "low"
    claims: list[Claim] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)
