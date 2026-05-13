"""GET /mgmt/tm/ltm/profile/client-ssl response fixture.

Citation:
  Primary: https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_client-ssl.html
    (property table — certKeyChain, ciphers, defaultsFrom, peerCertMode,
    sniDefault, sniRequire)
  Sub-object fields confirmed:
    https://clouddocs.f5.com/products/big-iq/mgmt-api/v0.0/ApiReferences/bigiq_public_api_ref/r_profile_client_ssl.html
    (BIG-IQ public API ref — same response shape)
  Cross-validated: f5devcentral/f5-automation-config-converter
    src/lib/AS3/customMaps/profile.js lines 2123-2186 (reads certKeyChain
    sub-object with cert/key/chain fields in TMSH form),
    commit e6f9fcec (tag v1.24.0)
  Accessed: 2026-05-12

Shape notes:
  - `certKeyChain` is the iControl REST field; the TMSH equivalent is
    `certificates`. Each entry: `name` (label), `cert` (.crt path),
    `key` (.key path), optional `chain`, optional `passphrase` (empty
    string when no passphrase).
  - `ciphers` is a colon-delimited string ("DEFAULT", "ECDHE+AES", etc.).
  - `defaultsFrom: /Common/clientssl` is the canonical parent for custom
    profiles.
  - The flat top-level `cert`/`key`/`chain` fields are pre-TMOS-11.3 and
    are NOT present on modern responses — the certKeyChain array
    superseded them.
"""

from __future__ import annotations

from typing import Any


def response(hostname: str) -> dict[str, Any]:
    base = f"https://{hostname}/mgmt/tm/ltm/profile/client-ssl"
    return {
        "kind": "tm:ltm:profile:client-ssl:client-sslcollectionstate",
        "selfLink": f"{base}?ver=17.1.0",
        "items": [
            {
                "kind": "tm:ltm:profile:client-ssl:client-sslstate",
                "name": "example_clientssl",
                "fullPath": "/Common/example_clientssl",
                "generation": 1,
                "selfLink": f"{base}/~Common~example_clientssl?ver=17.1.0",
                "alertTimeout": "indefinite",
                "allowExpiredCrl": "disabled",
                "authenticateDepth": 9,
                "authenticate": "once",
                "bypassOnClientCertFail": "disabled",
                "bypassOnHandshakeAlert": "disabled",
                "cacheSize": 262144,
                "cacheTimeout": 3600,
                "certKeyChain": [
                    {
                        "name": "example_cert_key_chain",
                        "cert": "/Common/example.crt",
                        "key": "/Common/example.key",
                        "chain": "/Common/ca-bundle.crt",
                        "passphrase": "",
                    },
                ],
                "ciphers": "DEFAULT",
                "defaultsFrom": "/Common/clientssl",
                "forwardProxyBypassDefaultAction": "intercept",
                "genericAlert": "enabled",
                "handshakeTimeout": 10,
                "inheritCertkeychain": "true",
                "maxActiveHandshakes": "indefinite",
                "maxAggregateRenegotiationPerMinute": "indefinite",
                "maxRenegotiationsPerMinute": 5,
                "maximumRecordSize": 16384,
                "modSslMethods": "disabled",
                "mode": "enabled",
                "partition": "Common",
                "peerCertMode": "ignore",
                "renegotiateMaxRecordDelay": "indefinite",
                "renegotiatePeriod": "indefinite",
                "renegotiateSize": "indefinite",
                "renegotiation": "enabled",
                "retainCertificate": "true",
                "secureRenegotiation": "require",
                "serverName": "",
                "sessionMirroring": "disabled",
                "sessionTicket": "disabled",
                "sniDefault": "false",
                "sniRequire": "false",
                "sslSignHash": "any",
                "strictResume": "disabled",
                "uncleanShutdown": "enabled",
            },
        ],
    }
