"""GET /mgmt/tm/ltm/virtual response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_virtual.html
    (property table — destination, pool, mask, ipProtocol, rules, persist,
    profiles fields)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/service.js lines 391-501,
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - destination encodes /Partition/IP:port as a single string. IPv6 uses
    `.` as the port delimiter instead of `:`.
  - profiles is an OBJECT keyed by full profile path, each value carrying
    a `context` field (clientside/serverside/all) — not an array.
  - persist is an object keyed by profile path with a `default` flag.
  - rules is an object keyed by rule path (preserving insertion order).
  - selfLink uses `?ver=` query suffix on real F5; preserved for fidelity.
  - type encodes SNAT mode at the top level.
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/virtual"
    pool_link = f"https://{hostname}/mgmt/tm/ltm/pool/~Common~example_pool?ver=17.1.0"
    return {
        "kind": "tm:ltm:virtual:virtualcollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:virtual:virtualstate",
                "name": "example_http_vs",
                "fullPath": "/Common/example_http_vs",
                "generation": 1,
                "selfLink": f"{base}/~Common~example_http_vs?ver=17.1.0",
                "addressStatus": "yes",
                "autoLasthop": "default",
                "cmpEnabled": "yes",
                "connectionLimit": 0,
                "destination": "/Common/10.1.10.10:80",
                "enabled": True,
                "gtmScore": 0,
                "ipProtocol": "tcp",
                "mask": "255.255.255.255",
                "mirror": "disabled",
                "mobileAppTunnel": "disabled",
                "nat64": "disabled",
                "partition": "Common",
                "pool": "/Common/example_pool",
                "poolReference": {"link": pool_link},
                "profiles": {
                    "/Common/http": {"context": "all", "name": "http", "partition": "Common"},
                    "/Common/tcp": {"context": "all", "name": "tcp", "partition": "Common"},
                },
                "rules": {
                    "/Common/example_irule": {"name": "example_irule", "partition": "Common"},
                },
                "persist": {
                    "/Common/cookie_persist": {
                        "default": "yes",
                        "name": "cookie_persist",
                        "partition": "Common",
                    },
                },
                "source": "0.0.0.0/0",
                "sourceAddressTranslation": {"type": "automap"},
                "type": "standard",
                "vlansEnabled": False,
                "vsIndex": 1,
            },
            {
                "kind": "tm:ltm:virtual:virtualstate",
                "name": "example_https_vs",
                "fullPath": "/Common/example_https_vs",
                "generation": 2,
                "selfLink": f"{base}/~Common~example_https_vs?ver=17.1.0",
                "addressStatus": "yes",
                "autoLasthop": "default",
                "cmpEnabled": "yes",
                "connectionLimit": 0,
                "destination": "/Common/10.1.10.10:443",
                "enabled": True,
                "gtmScore": 0,
                "ipProtocol": "tcp",
                "mask": "255.255.255.255",
                "mirror": "disabled",
                "mobileAppTunnel": "disabled",
                "nat64": "disabled",
                "partition": "Common",
                "pool": "/Common/example_pool",
                "poolReference": {"link": pool_link},
                "profiles": {
                    "/Common/http": {"context": "all", "name": "http", "partition": "Common"},
                    "/Common/tcp": {"context": "all", "name": "tcp", "partition": "Common"},
                    "/Common/example_clientssl": {
                        "context": "clientside",
                        "name": "example_clientssl",
                        "partition": "Common",
                    },
                },
                "rules": {
                    "/Common/example_irule": {"name": "example_irule", "partition": "Common"},
                },
                "persist": {
                    "/Common/cookie_persist": {
                        "default": "yes",
                        "name": "cookie_persist",
                        "partition": "Common",
                    },
                },
                "source": "0.0.0.0/0",
                "sourceAddressTranslation": {"type": "automap"},
                "type": "standard",
                "vlansEnabled": False,
                "vsIndex": 2,
            },
        ],
    }
