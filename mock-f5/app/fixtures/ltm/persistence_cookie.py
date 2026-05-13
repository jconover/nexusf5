"""GET /mgmt/tm/ltm/persistence/cookie response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_persistence_cookie.html
    (property table — cookieName, method, mode, expiration, httpOnly, secure)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/persist.js lines 1142-1180 (reads cookieName,
    ttl, duration, iRule, passphrase fields),
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - `cookieName: "none"` in the REST response means no custom cookie name;
    ACC normalises this to empty/unset on AS3 conversion.
  - `expiration` uses HH:MM:SS format. "0:0:0" = session cookie.
  - `method` is the canonical REST field; older API versions also expose
    `mode` redundantly.
  - `defaultsFrom: /Common/cookie` is the parent for custom cookie persist
    profiles.
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/persistence/cookie"
    return {
        "kind": "tm:ltm:persistence:cookie:cookiecollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:persistence:cookie:cookiestate",
                "name": "cookie_persist",
                "fullPath": "/Common/cookie_persist",
                "generation": 1,
                "selfLink": f"{base}/~Common~cookie_persist?ver=17.1.0",
                "alwaysSend": "disabled",
                "cookieEncryption": "disabled",
                "cookieEncryptionPassphrase": "",
                "cookieName": "SERVERID",
                "defaultsFrom": "/Common/cookie",
                "description": "none",
                "expiration": "0:0:0",
                "hashLength": 0,
                "hashOffset": 0,
                "httpOnly": "enabled",
                "matchAcrossPools": "disabled",
                "matchAcrossServices": "disabled",
                "matchAcrossVirtuals": "disabled",
                "method": "insert",
                "mirror": "disabled",
                "overrideConnectionLimit": "disabled",
                "partition": "Common",
                "secure": "disabled",
                "timeout": "indefinite",
            },
        ],
    }
