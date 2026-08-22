#!/usr/bin/env python3
"""Seeded synthetic log generator for the quiet-hours incident fixture.

Writes:
    data/generated/cloudwatch.json  (JSON lines, structured app logs)
    data/generated/splunk.log       (raw key=value text, gateway/access logs)
    data/fixtures/incident.json     (ground truth: the true root-cause event_id)

The incident: a DB connection pool for the 'payments-db' pool exhausts,
causing checkout timeouts in order-service, which cascade into upstream 500s
at the gateway and eventually trip a circuit breaker.

  - The ROOT CAUSE appears once, quietly, in CloudWatch: a WARN about slow
    pool checkouts, followed a bit later by an ERROR that the pool is fully
    exhausted (with active/idle/waiting counts).
  - The SYMPTOMS are loud and repetitive in Splunk: ~50 near-identical
    upstream 500s from the gateway, then a single circuit-breaker WARN.
  - Everything else is boring, deterministic chatter: health checks every
    15s, routine 200s, an unrelated service's routine logs, and a recurring
    deprecation warning that has nothing to do with the incident. Noise
    outnumbers signal by more than 10 to 1.

Given the same --seed, output is byte-identical: no wall-clock time, no
unordered-collection iteration, no unseeded randomness.
"""

import argparse
import json
import os
import random
from datetime import UTC, datetime, timedelta, timezone

SPLUNK_TZ = timezone(timedelta(hours=-4))  # fixed "-0400" offset, as specified

# Fixed synthetic start time -- deterministic, not wall-clock.
BASE_TIME = datetime(2026, 8, 22, 6, 0, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=35)

POOL_WARN_OFFSET = timedelta(minutes=20)  # incident starts here
POOL_ERROR_OFFSET = POOL_WARN_OFFSET + timedelta(seconds=90)
STORM_START_OFFSET = POOL_ERROR_OFFSET + timedelta(seconds=15)
STORM_COUNT = 50
STORM_SPAN = timedelta(minutes=5)

# Splunk identifies hosts as VMs (host=gw-prod-04); CloudWatch identifies
# them as pods (a service name plus a replicaset/pod hash). Deliberately
# different formats -- this is part of the schema mismatch the project is
# built to survive.
GATEWAY_HOSTS = ["gw-prod-01", "gw-prod-02", "gw-prod-03"]
AUTH_HOSTS = ["auth-prod-01", "auth-prod-02"]

# A gateway access line names the downstream service it proxied to via
# upstream=, not service= -- Splunk has no "service" concept of its own.
PATH_UPSTREAM = {
    "/api/orders": "order-service",
    "/api/orders/status": "order-service",
    "/api/cart": "cart-service",
    "/api/checkout": "checkout-service",
    "/api/catalog": "catalog-service",
}
REQUEST_PATHS = list(PATH_UPSTREAM)

# Real pods are stable, not invented fresh per log line: each service gets a
# fixed roster, generated once, then reused across every event it emits.
CLOUDWATCH_SERVICES = ["order-service", "inventory-service", "gateway", "billing-service", "reporting-service"]
POD_ROSTER_SIZE = 3


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def splunk_ts(dt: datetime) -> str:
    local = dt.astimezone(SPLUNK_TZ)
    return local.strftime("%m/%d/%Y %H:%M:%S.") + f"{local.microsecond // 1000:03d} -0400"


def pod_name(rng: random.Random, service: str) -> str:
    """A k8s-style pod name: <service>-<replicaset hash>-<pod suffix>."""
    replicaset = f"{rng.randint(0, 0xFFFFFF):06x}"
    suffix = "".join(rng.choice("bcdfghjklmnpqrstvwxyz0123456789") for _ in range(5))
    return f"{service}-{replicaset}-{suffix}"


def build_pod_rosters(rng: random.Random, services: list[str]) -> dict[str, list[str]]:
    """A fixed set of POD_ROSTER_SIZE pods per service, generated once up
    front and reused for every event that service emits.
    """
    return {service: [pod_name(rng, service) for _ in range(POD_ROSTER_SIZE)] for service in services}


def cw_line(dt: datetime, log_stream: str, level: str, service: str, msg: str, pod: str, **extra) -> str:
    inner = {"level": level, "service": service, "msg": msg, "pod": pod, **extra}
    outer = {"timestamp": ms(dt), "logStreamName": log_stream, "message": json.dumps(inner)}
    return json.dumps(outer)


def splunk_line(
    dt: datetime, host: str, source: str, sourcetype: str, level: str, msg: str, upstream: str | None = None
) -> str:
    upstream_field = f"upstream={upstream} " if upstream else ""
    return (
        f'{splunk_ts(dt)} host={host} source={source} sourcetype={sourcetype} level={level} {upstream_field}msg="{msg}"'
    )


def generate(seed: int) -> tuple[list[str], list[str], str]:
    rng = random.Random(seed)
    pod_rosters = build_pod_rosters(rng, CLOUDWATCH_SERVICES)

    cw_events = []  # list of (datetime, line)
    sp_events = []

    # --- CloudWatch noise: health checks every 15s, rotating across services ---
    hc_services = ["order-service", "inventory-service", "gateway", "billing-service"]
    t = BASE_TIME
    i = 0
    while t < BASE_TIME + WINDOW:
        service = hc_services[i % len(hc_services)]
        pod = rng.choice(pod_rosters[service])
        cw_events.append((t, cw_line(t, f"/ecs/{service}", "INFO", service, "health check ok", pod)))
        t += timedelta(seconds=15)
        i += 1

    # --- CloudWatch noise: recurring deprecation WARN, irrelevant to the incident ---
    t = BASE_TIME + timedelta(seconds=30)
    while t < BASE_TIME + WINDOW:
        pod = rng.choice(pod_rosters["gateway"])
        cw_events.append(
            (
                t,
                cw_line(
                    t,
                    "/ecs/gateway",
                    "WARN",
                    "gateway",
                    "DeprecationWarning: header 'X-Legacy-Auth' is deprecated, use 'Authorization' instead",
                    pod,
                ),
            )
        )
        t += timedelta(seconds=120)

    # --- CloudWatch noise: an unrelated service doing its own routine thing ---
    t = BASE_TIME + timedelta(seconds=60)
    batch_no = 0
    while t < BASE_TIME + WINDOW:
        pod = rng.choice(pod_rosters["reporting-service"])
        batch_no += 1
        cw_events.append(
            (
                t,
                cw_line(
                    t,
                    "/ecs/reporting-service",
                    "INFO",
                    "reporting-service",
                    f"nightly export batch {batch_no} progress: {rng.randint(1, 100)}%",
                    pod,
                ),
            )
        )
        t += timedelta(seconds=180)

    # --- CloudWatch SIGNAL: the quiet root cause ---
    # Both events land on the same pod: a pool doesn't exhaust across a
    # whole service at once, it exhausts on the one instance holding the
    # connections that are timing out.
    root_cause_pod = rng.choice(pod_rosters["order-service"])
    warn_t = BASE_TIME + POOL_WARN_OFFSET
    warn_pod = root_cause_pod
    cw_events.append(
        (
            warn_t,
            cw_line(
                warn_t,
                "/ecs/order-service",
                "WARN",
                "order-service",
                "connection checkout exceeded timeout: waited 4500ms for pool 'payments-db'",
                warn_pod,
            ),
        )
    )

    error_t = BASE_TIME + POOL_ERROR_OFFSET
    error_pod = root_cause_pod
    root_cause_line = cw_line(
        error_t,
        "/ecs/order-service",
        "ERROR",
        "order-service",
        "connection pool exhausted: active=20 idle=0 waiting=37",
        error_pod,
        pool="payments-db",
        active=20,
        idle=0,
        waiting=37,
    )
    cw_events.append((error_t, root_cause_line))

    # --- Splunk noise: routine gateway 200s ---
    # A gateway access line names the downstream service it proxied to via
    # upstream=; no service= key exists here at all, by design.
    t = BASE_TIME
    req_no = 0
    while t < BASE_TIME + WINDOW:
        req_no += 1
        host = GATEWAY_HOSTS[rng.randint(0, len(GATEWAY_HOSTS) - 1)]
        path = REQUEST_PATHS[rng.randint(0, len(REQUEST_PATHS) - 1)]
        latency = rng.randint(8, 60)
        sp_events.append(
            (
                t,
                splunk_line(
                    t,
                    host,
                    "/var/log/gateway/access.log",
                    "gateway_access",
                    "INFO",
                    f"GET {path} 200 {latency}ms req={req_no:06d}",
                    upstream=PATH_UPSTREAM[path],
                ),
            )
        )
        t += timedelta(seconds=18)

    # --- Splunk noise: unrelated auth-service traffic ---
    # auth-service isn't proxied through the gateway, so these lines carry
    # no upstream= at all -- the parser must fall back to sourcetype.
    t = BASE_TIME + timedelta(seconds=10)
    while t < BASE_TIME + WINDOW:
        host = AUTH_HOSTS[rng.randint(0, len(AUTH_HOSTS) - 1)]
        sp_events.append(
            (
                t,
                splunk_line(
                    t,
                    host,
                    "/var/log/auth/app.log",
                    "auth_events",
                    "INFO",
                    "user login succeeded",
                ),
            )
        )
        t += timedelta(seconds=25)

    # --- Splunk SIGNAL: the loud, repetitive symptom ---
    storm_start = BASE_TIME + STORM_START_OFFSET
    storm_gap = STORM_SPAN / STORM_COUNT
    t = storm_start
    for n in range(STORM_COUNT):
        host = GATEWAY_HOSTS[rng.randint(0, len(GATEWAY_HOSTS) - 1)]
        latency = rng.randint(4800, 5200)
        sp_events.append(
            (
                t,
                splunk_line(
                    t,
                    host,
                    "/var/log/gateway/access.log",
                    "gateway_access",
                    "ERROR",
                    f"upstream connect error or disconnect/reset before headers. reset reason: "
                    f"connection timeout calling order-service after {latency}ms req={100000 + n:06d}",
                    upstream="order-service",
                ),
            )
        )
        t += storm_gap + timedelta(milliseconds=rng.randint(-200, 200))

    breaker_t = t + timedelta(seconds=2)
    sp_events.append(
        (
            breaker_t,
            splunk_line(
                breaker_t,
                GATEWAY_HOSTS[0],
                "/var/log/gateway/access.log",
                "gateway_access",
                "WARN",
                "circuit breaker OPEN for upstream 'order-service' after 50 consecutive failures",
                upstream="order-service",
            ),
        )
    )

    cw_events.sort(key=lambda pair: pair[0])
    sp_events.sort(key=lambda pair: pair[0])

    cw_lines = [line for _, line in cw_events]
    sp_lines = [line for _, line in sp_events]

    # line_no is 1-based position in file -> event_id is f"cloudwatch:{line_no:04d}"
    root_cause_line_no = cw_lines.index(root_cause_line) + 1
    root_cause_event_id = f"cloudwatch:{root_cause_line_no:04d}"

    return cw_lines, sp_lines, root_cause_event_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generated_dir = os.path.join(repo_root, "data", "generated")
    fixtures_dir = os.path.join(repo_root, "data", "fixtures")
    os.makedirs(generated_dir, exist_ok=True)
    os.makedirs(fixtures_dir, exist_ok=True)

    cw_lines, sp_lines, root_cause_event_id = generate(args.seed)

    cw_path = os.path.join(generated_dir, "cloudwatch.json")
    sp_path = os.path.join(generated_dir, "splunk.log")
    incident_path = os.path.join(fixtures_dir, "incident.json")

    with open(cw_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cw_lines) + "\n")

    with open(sp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sp_lines) + "\n")

    incident = {
        "seed": args.seed,
        "root_cause_event_id": root_cause_event_id,
        "root_cause": (
            "The connection pool for 'payments-db' in order-service exhausted "
            "(active=20 idle=0 waiting=37) after a period of slow checkouts, "
            "causing checkout timeouts that cascaded into gateway upstream 500s "
            "and tripped a circuit breaker for order-service."
        ),
    }
    with open(incident_path, "w", encoding="utf-8") as f:
        json.dump(incident, f, indent=2)
        f.write("\n")

    total = len(cw_lines) + len(sp_lines)
    print(f"wrote {len(cw_lines)} cloudwatch lines, {len(sp_lines)} splunk lines ({total} total)")
    print(f"root cause: {root_cause_event_id}")


if __name__ == "__main__":
    main()
