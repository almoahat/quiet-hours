"""Parser for CloudWatch-style JSON-lines exports.

Each line is a JSON object:
    {"timestamp": 1699999999000, "logStreamName": "...", "message": "<json string>"}

`message` is itself a JSON string (CloudWatch's usual double-encoding for
structured app logs shipped through an agent) and must be decoded a second
time to reach the fields we care about: level, service, msg, pod.
"""

import json
from datetime import UTC, datetime

from quiet_hours.contracts import NormalizedEvent

SOURCE = "cloudwatch"


def parse(path: str) -> list[NormalizedEvent]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            raw_line = raw_line.rstrip("\n")
            if not raw_line.strip():
                continue
            outer = json.loads(raw_line)
            inner = json.loads(outer["message"])

            ts = datetime.fromtimestamp(outer["timestamp"] / 1000, tz=UTC)
            log_stream = outer.get("logStreamName", "")
            pod = inner.get("pod", "")

            known_inner_keys = {"level", "service", "msg", "pod"}
            attrs = {
                "logStreamName": log_stream,
                **{k: v for k, v in inner.items() if k not in known_inner_keys},
            }

            events.append(
                NormalizedEvent(
                    event_id=f"{SOURCE}:{line_no:04d}",
                    ts=ts,
                    ts_raw=str(outer["timestamp"]),
                    source=SOURCE,
                    service=inner.get("service", ""),
                    host=pod or log_stream,
                    level=inner.get("level", "").upper(),
                    message=inner.get("msg", ""),
                    source_file=path,
                    line_no=line_no,
                    raw_line=raw_line,
                    attrs=attrs,
                )
            )
    return events
