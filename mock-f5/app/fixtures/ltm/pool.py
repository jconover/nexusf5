"""GET /mgmt/tm/ltm/pool response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_pool.html
    (property table — loadBalancingMode, monitor, minActiveMembers)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/pool.js lines 93-173,
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - monitor is a SPACE-SEPARATED STRING. Single monitor: "/Common/http".
    Multi-monitor min-N: "min 1 of { /Common/http /Common/tcp }". ACC
    splits on " and " for the all-monitor case and on " of { " for min-N.
  - membersReference is a link object pointing at the members subcollection.
    Members are NOT inlined unless `?expandSubcollections=true` is passed.
  - loadBalancingMode values use hyphen-separated names (round-robin,
    least-connections-member, etc.).
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/pool"
    members_link = f"{base}/~Common~example_pool/members?ver=17.1.0"
    return {
        "kind": "tm:ltm:pool:poolcollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:pool:poolstate",
                "name": "example_pool",
                "fullPath": "/Common/example_pool",
                "generation": 1,
                "selfLink": f"{base}/~Common~example_pool?ver=17.1.0",
                "allowNat": "yes",
                "allowSnat": "yes",
                "ignorePersistedWeight": "disabled",
                "ipTosToClient": "pass-through",
                "ipTosToServer": "pass-through",
                "linkQosToClient": "pass-through",
                "linkQosToServer": "pass-through",
                "loadBalancingMode": "round-robin",
                "minActiveMembers": 0,
                "minUpMembers": 0,
                "minUpMembersAction": "failover",
                "minUpMembersChecking": "disabled",
                "monitor": "/Common/example_http_monitor",
                "partition": "Common",
                "queueDepthLimit": 0,
                "queueOnConnectionLimit": "disabled",
                "queueTimeLimit": 0,
                "reselectTries": 0,
                "serviceDownAction": "none",
                "slowRampTime": 10,
                "membersReference": {"link": members_link, "isSubcollection": True},
            },
        ],
    }
