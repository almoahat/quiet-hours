"""Registry of log-source parsers.

Adding a third source is one new module exposing `parse(path) -> list[NormalizedEvent]`
plus one entry here.
"""

from quiet_hours.parsers import cloudwatch, splunk

REGISTRY = {
    cloudwatch.SOURCE: cloudwatch.parse,
    splunk.SOURCE: splunk.parse,
}
