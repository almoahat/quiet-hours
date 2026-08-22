"""Parser for raw Splunk-style text exports.

Each line looks like:
    08/22/2026 14:32:10.123 -0400 host=gw-prod-04 source=/var/log/gw/app.log \
        sourcetype=gateway_access level=INFO upstream=order-service msg="request ok"

A fixed-width timestamp (with a literal UTC offset, here US Eastern -0400)
is followed by whitespace-separated key=value pairs, where a value may be a
double-quoted string containing spaces.

Splunk has no "service" field of its own -- this is the schema mismatch the
project exists to survive. A gateway access line instead names the
downstream service it proxied to via upstream=; other sourcetypes (e.g.
auth_events) carry no such key at all. NormalizedEvent.service is derived:
upstream= if present, else the leading word of sourcetype=, else "unknown".
"""

import re
from datetime import UTC, datetime

from quiet_hours.contracts import NormalizedEvent

SOURCE = "splunk"

TS_RE = re.compile(r"^(?P<ts>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{4})\s+(?P<rest>.*)$")
KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')

TS_FORMAT = "%m/%d/%Y %H:%M:%S.%f %z"

# Keys already captured by a dedicated NormalizedEvent field. Everything
# else (source=, sourcetype=, and any other key=value pairs) falls through
# to `attrs`.
KNOWN_KEYS = {"host", "level", "upstream", "msg"}


def _parse_kv(rest: str) -> dict:
    kv = {}
    for key, value in KV_RE.findall(rest):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        kv[key] = value
    return kv


def _derive_service(kv: dict) -> str:
    """upstream= is the reliable signal. Failing that, guess from sourcetype
    (e.g. "auth_events" -> "auth"). Never raises -- worst case is "unknown".
    """
    upstream = kv.get("upstream")
    if upstream:
        return upstream

    sourcetype = kv.get("sourcetype")
    if sourcetype:
        return sourcetype.split("_")[0]

    return "unknown"


def parse(path: str) -> list[NormalizedEvent]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            raw_line = raw_line.rstrip("\n")
            if not raw_line.strip():
                continue

            match = TS_RE.match(raw_line)
            if not match:
                raise ValueError(f"{path}:{line_no}: line does not start with a Splunk timestamp: {raw_line!r}")

            ts_raw = match.group("ts")
            ts = datetime.strptime(ts_raw, TS_FORMAT).astimezone(UTC)

            kv = _parse_kv(match.group("rest"))
            attrs = {k: v for k, v in kv.items() if k not in KNOWN_KEYS}

            events.append(
                NormalizedEvent(
                    event_id=f"{SOURCE}:{line_no:04d}",
                    ts=ts,
                    ts_raw=ts_raw,
                    source=SOURCE,
                    service=_derive_service(kv),
                    host=kv.get("host", ""),
                    level=kv.get("level", "").upper(),
                    message=kv.get("msg", ""),
                    source_file=path,
                    line_no=line_no,
                    raw_line=raw_line,
                    attrs=attrs,
                )
            )
    return events
