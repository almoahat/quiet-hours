"""Schema-mismatch proof: CloudWatch and Splunk name the same service two
different ways (nested "service" JSON key vs. a Splunk upstream= tag), and
identify hosts two different ways (a k8s-style pod vs. a VM hostname). Both
sources must still normalize to the same NormalizedEvent.service, while
NormalizedEvent.host is allowed -- expected -- to differ in format.
"""

import json

from quiet_hours.parsers import cloudwatch, splunk


def test_service_normalizes_across_sources_despite_different_field_names(tmp_path):
    cw_path = tmp_path / "cloudwatch.json"
    outer = {
        "timestamp": 1755838800000,
        "logStreamName": "/ecs/payments-api",
        "message": json.dumps(
            {
                "level": "INFO",
                "service": "payments-api",
                "msg": "payment processed",
                "pod": "payments-api-7d4f9c-x2n1",
            }
        ),
    }
    cw_path.write_text(json.dumps(outer) + "\n")

    sp_path = tmp_path / "splunk.log"
    sp_path.write_text(
        "08/22/2026 06:00:00.000 -0400 host=gw-prod-04 source=/var/log/gateway/access.log "
        'sourcetype=gateway_access level=INFO upstream=payments-api msg="POST /api/payments 200 12ms"\n'
    )

    cw_event = cloudwatch.parse(str(cw_path))[0]
    sp_event = splunk.parse(str(sp_path))[0]

    # The proof: two different field names (nested "service" vs. upstream=)
    # normalize to the same service.
    assert cw_event.service == "payments-api"
    assert sp_event.service == "payments-api"

    # The other proof: host formats are expected to differ (pod vs. VM),
    # not converge, because a pod and a VM hostname are genuinely different
    # things.
    assert cw_event.host == "payments-api-7d4f9c-x2n1"
    assert sp_event.host == "gw-prod-04"
    assert cw_event.host != sp_event.host


def test_splunk_service_falls_back_to_sourcetype_when_no_upstream(tmp_path):
    sp_path = tmp_path / "splunk.log"
    sp_path.write_text(
        "08/22/2026 06:00:00.000 -0400 host=auth-prod-01 source=/var/log/auth/app.log "
        'sourcetype=auth_events level=INFO msg="user login succeeded"\n'
    )
    event = splunk.parse(str(sp_path))[0]
    assert event.service == "auth"  # derived from "auth_events"


def test_splunk_service_falls_back_to_unknown_when_nothing_to_derive_from(tmp_path):
    sp_path = tmp_path / "splunk.log"
    sp_path.write_text('08/22/2026 06:00:00.000 -0400 host=gw-prod-04 level=INFO msg="mystery line"\n')
    event = splunk.parse(str(sp_path))[0]
    assert event.service == "unknown"
