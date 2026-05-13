"""GET /mgmt/tm/ltm/monitor/http response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_monitor_http.html
    (property table — send, recv, interval, timeout, defaultsFrom, destination)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/monitor.js lines 738-763 (ltm monitor http handler;
    reads `send` and renames REST `recv` to AS3 `receive` on conversion),
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - The REST field is `recv` (short form). ACC renames it to `receive` on
    AS3 conversion; the brownfield extractor must do the same.
  - `send` and `recv` contain literal CRLF bytes in real F5 responses
    (\\r\\n encoded as JSON escape, decoded to actual \\r and \\n bytes).
  - `defaultsFrom` references the parent monitor profile (/Common/http).
  - System built-in monitors (e.g. /Common/http) appear in the collection
    too — the extractor must filter on `partition`/`defaultsFrom` to avoid
    re-exporting built-ins.
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/monitor/http"
    return {
        "kind": "tm:ltm:monitor:http:httpcollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:monitor:http:httpstate",
                "name": "example_http_monitor",
                "fullPath": "/Common/example_http_monitor",
                "generation": 1,
                "selfLink": f"{base}/~Common~example_http_monitor?ver=17.1.0",
                "adaptive": "disabled",
                "adaptiveDivergenceType": "relative",
                "adaptiveDivergenceValue": 25,
                "adaptiveLimit": 200,
                "adaptiveSamplingTimespan": 300,
                "defaultsFrom": "/Common/http",
                "destination": "*:*",
                "interval": 5,
                "ipDscp": 0,
                "manualResume": "disabled",
                "partition": "Common",
                "recv": "HTTP/1.",
                "recvDisable": "",
                "reverse": "disabled",
                "send": ("GET /health HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n"),
                "timeUntilUp": 0,
                "timeout": 16,
                "transparent": "disabled",
                "upInterval": 0,
            },
        ],
    }
