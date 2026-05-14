"""GET /mgmt/tm/ltm/rule response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_rule.html
    (property table — apiAnonymous field for iRule source body)
  Confirmed: F5 DevCentral, "The Real World: iControl REST and iRules
    Deployment" — https://community.f5.com/kb/technicalarticles/the-real-world-icontrol-rest-and-irules-deployment/285892
    (POST/GET with apiAnonymous containing verbatim TCL)
  Confirmed: F5 K11799414 — https://my.f5.com/manage/s/article/K11799414
  Accessed: 2026-05-12

Shape notes:
  - `apiAnonymous` carries the raw multi-line TCL body verbatim, including
    newlines and indentation, exactly as entered in TMSH. Field name is
    `apiAnonymous` — not `body`, `code`, or `iRule`.
  - In collection responses the full TCL body is inlined; no truncation.
  - System built-in iRules (e.g. /Common/_sys_auth_radius) appear in the
    collection too — the extractor filters on partition and name prefix.

The example TCL body in this fixture intentionally mixes a fast-path
health-check response with a header-driven pool select to give the
brownfield extractor a non-trivial iRule shape to round-trip.
"""

from __future__ import annotations

from typing import Any

_IRULE_BODY = """when HTTP_REQUEST {
    if { [HTTP::uri] starts_with "/health" } {
        HTTP::respond 200 content "OK"
    }
    if { [HTTP::header exists "X-Forward-To"] } {
        pool [HTTP::header "X-Forward-To"]
    }
}"""


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/rule"
    return {
        "kind": "tm:ltm:rule:rulecollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:rule:rulestate",
                "name": "example_irule",
                "fullPath": "/Common/example_irule",
                "generation": 1,
                "selfLink": f"{base}/~Common~example_irule?ver=17.1.0",
                "apiAnonymous": _IRULE_BODY,
                "partition": "Common",
            },
        ],
    }
