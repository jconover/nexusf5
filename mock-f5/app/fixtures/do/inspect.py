"""GET /mgmt/shared/declarative-onboarding/inspect response fixture.

Citation:
  Primary: https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/do-endpoint-methods.html
    (verbatim response example reproduced below, fetched 2026-05-12)
  Brownfield availability: https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/http-methods.html
    ("In BIG-IP DO version 1.7.0 and later, you can use a GET request to
    the /inspect endpoint to retrieve the current BIG-IP configuration.")
  DO class names cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/DO/doCustomMaps.js (DNS, NTP, Provision, VLAN, SelfIp class names),
    commit e6f9fcec (tag v1.24.0)
  Schema source: mock-f5/schemas/do/v1.47.0/base.schema.json (vendored per ADR 006)
  Accessed: 2026-05-12

Verbatim shape from clouddocs do-endpoint-methods.html:

    [
        {
            "id": 0,
            "selfLink": "https://localhost/mgmt/shared/declarative-onboarding/inspect",
            "result": {"class": "Result", "code": 200, "status": "OK",
                       "message": "", "errors": []},
            "declaration": {
                "class": "DO",
                "declaration": {
                    "class": "Device",
                    "schemaVersion": "1.7.0",
                    "Common": { ... }
                }
            }
        }
    ]

Shape notes:
  - The response is a JSON ARRAY (matches the wrap pattern F5 uses for
    several /mgmt/shared/ endpoints; do_info returns the same way).
  - Each array element wraps a TASK envelope (id, selfLink, result) around
    a declaration. The declaration itself is wrapped in `class: "DO"` and
    contains an inner `class: "Device"` block.
  - The inner `declaration.declaration` is what passes the ADR 006
    validate_do_declaration() gate — that block is structurally identical
    to a valid POST body for /mgmt/shared/declarative-onboarding.
  - This double-wrapping is documented F5 contract for /inspect specifically.
    It is NOT the ADR 006 bug (which was a POST-body wrapper error); the
    /inspect GET response has different semantics from POST.
  - schemaVersion is set to "1.40.0" to match what the mock's do_info
    endpoint reports as installed (extensions.py:do_info). The vendored
    schema is 1.47.0 and accepts 1.40.0 declarations (same enum range).
"""

from __future__ import annotations

from typing import Any


def _common_tenant() -> dict[str, Any]:
    """The Common tenant block that mirrors a representative onboarded
    BIG-IP. RFC 1918 addressing only per CLAUDE.md non-negotiables.
    """
    return {
        "class": "Tenant",
        "mySystem": {
            "class": "System",
            "hostname": "bigip-lab-01.example.com",
            "cliInactivityTimeout": 0,
            "consoleInactivityTimeout": 0,
            "autoPhonehome": False,
        },
        "myDns": {
            "class": "DNS",
            "nameServers": ["192.0.2.53", "192.0.2.54"],
            "search": ["example.com", "lab.example.com"],
        },
        "myNtp": {
            "class": "NTP",
            "servers": ["192.0.2.123", "192.0.2.124"],
            "timezone": "America/Chicago",
        },
        "remoteSyslog1": {
            "class": "SyslogRemoteServer",
            "host": "192.0.2.200",
            "remotePort": 514,
        },
        "myProvisioning": {
            "class": "Provision",
            "ltm": "nominal",
            "asm": "none",
            "avr": "none",
            "gtm": "none",
        },
        "external": {
            "class": "VLAN",
            "tag": 4094,
            "mtu": 1500,
            "interfaces": [{"name": "1.1", "tagged": False}],
        },
        "internal": {
            "class": "VLAN",
            "tag": 4093,
            "mtu": 1500,
            "interfaces": [{"name": "1.2", "tagged": False}],
        },
        "external-self": {
            "class": "SelfIp",
            "address": "10.1.10.1/24",
            "vlan": "external",
            "allowService": "none",
            "trafficGroup": "traffic-group-local-only",
        },
        "internal-self": {
            "class": "SelfIp",
            "address": "10.1.20.1/24",
            "vlan": "internal",
            "allowService": "default",
            "trafficGroup": "traffic-group-local-only",
        },
    }


def device_declaration() -> dict[str, Any]:
    """The inner `class: "Device"` declaration. Used as-is for ADR 006
    schema validation; also embedded in `response()` below as the wrapped
    payload `/inspect` actually returns.
    """
    return {
        "class": "Device",
        "schemaVersion": "1.40.0",
        "label": "bigip-lab-01 inspected state",
        "Common": _common_tenant(),
    }


def response(hostname: str) -> list[dict[str, Any]]:
    """Wrap the Device declaration in F5's documented /inspect envelope:
    array of task-shaped objects, each with a `class: "DO"` outer
    wrapping a `class: "Device"` inner.
    """
    return [
        {
            "id": 0,
            "selfLink": f"https://{hostname}/mgmt/shared/declarative-onboarding/inspect",
            "result": {
                "class": "Result",
                "code": 200,
                "status": "OK",
                "message": "",
                "errors": [],
            },
            "declaration": {
                "class": "DO",
                "declaration": device_declaration(),
            },
        },
    ]
