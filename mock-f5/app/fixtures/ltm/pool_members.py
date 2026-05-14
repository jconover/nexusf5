"""GET /mgmt/tm/ltm/pool/{name}/members response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_pool.html
    (members subcollection resource)
  Operational reference: F5 K13310 (pool member state values)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/pool.js lines 114-168,
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - Member `name` in REST uses IP:port form ("10.1.20.10:8080");
    `fullPath` includes partition ("/Common/10.1.20.10:8080").
  - `session` controls admin enable/disable (user-enabled, user-disabled).
  - `state` reflects monitor result (up, down, unchecked).
  - A member with no per-member monitor reports monitor: "default".
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/pool/~Common~example_pool/members"

    def member(addr: str, session: str, state: str) -> dict[str, Any]:
        name = f"{addr}:8080"
        return {
            "kind": "tm:ltm:pool:members:membersstate",
            "name": name,
            "fullPath": f"/Common/{name}",
            "generation": 1,
            "selfLink": f"{base}/~Common~{addr}:8080?ver=17.1.0",
            "address": addr,
            "connectionLimit": 0,
            "dynamicRatio": 1,
            "ephemeral": "false",
            "fqdn": {"autopopulate": "disabled"},
            "inheritProfile": "enabled",
            "logging": "disabled",
            "monitor": "default",
            "partition": "Common",
            "priorityGroup": 0,
            "rateLimit": "disabled",
            "ratio": 1,
            "session": session,
            "state": state,
        }

    return {
        "kind": "tm:ltm:pool:members:memberscollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            member("10.1.20.10", "user-enabled", "up"),
            member("10.1.20.11", "user-enabled", "up"),
            member("10.1.20.12", "user-disabled", "down"),
        ],
    }
