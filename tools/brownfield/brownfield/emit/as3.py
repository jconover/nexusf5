"""AS3 declaration emitter.

Takes the walker's raw F5 LTM extraction and produces an AS3 declaration
matching the project's existing AS3 envelope shape (per
terraform/modules/as3-declaration/templates/as3.json.tftpl) and the
literal-partition tenant naming pattern (per ADR 007 Addendum 2026-05-13).

Layout:

    {
      "class": "AS3",
      "action": "deploy",
      "persist": True,
      "declaration": {
        "class": "ADC",
        "schemaVersion": "3.50.0",
        "id": "brownfield-<hostname>-<partition>",
        "label": "brownfield-<hostname>",
        "<partition>": {
          "class": "Tenant",
          "<partition>": {                  # Application named after partition
            "class": "Application",
            "template": "generic",
            "<monitor_name>": {...},        # Monitor_HTTP
            "<persist_name>": {...},        # Persist
            "<profile_name>": {...},        # TLS_Server (clientssl in AS3)
            "<irule_name>": {...},          # iRule
            "<pool_name>": {...},           # Pool
            "<virtual_name>": {...},        # Service_HTTP / Service_HTTPS / ...
          }
        }
      }
    }

Application name = literal partition name per the Checkpoint 3 pre-flight
decision: "literal partition name as the application name, so
bigip_lab_01_Common.Common — application named after the partition it
represents. Clean, deterministic, survives re-extraction."

Determinism: all dict construction uses sorted keys where the AS3
contract doesn't impose an order. JSON serialization is sort_keys=True at
the file-writing boundary in cli.py.

Built-in filtering: applied to monitors, profiles, persistence, and
iRules before emission. Virtuals and pools are operator-defined and don't
get filtered. The user's discipline requirement: the test
test_emitted_as3_excludes_builtins enforces this.
"""

from __future__ import annotations

from typing import Any

from brownfield.builtins import BIGIP_BUILTIN_PROFILE_NAMES, filter_builtins
from brownfield.emit._shape import parse_destination
from brownfield.walker import WalkerOutput

AS3_SCHEMA_VERSION = "3.50.0"  # matches project's existing as3-declaration template


def emit_as3(
    walker_output: WalkerOutput,
    *,
    hostname: str,
    partition: str = "Common",
) -> dict[str, Any]:
    """Build an AS3 envelope declaration from extracted LTM state.

    The tenant and Application are both named with the literal partition
    per ADR 007 Addendum 2026-05-13. Multi-device disambiguation lives
    at the Terraform resource-name layer, not here.
    """
    application = _build_application(walker_output, partition=partition)
    tenant: dict[str, Any] = {
        "class": "Tenant",
        partition: application,  # Application named after the partition
    }
    declaration: dict[str, Any] = {
        "class": "ADC",
        "schemaVersion": AS3_SCHEMA_VERSION,
        "id": f"brownfield-{hostname}-{partition}",
        "label": f"brownfield-{hostname}",
        partition: tenant,
    }
    return {
        "class": "AS3",
        "action": "deploy",
        "persist": True,
        "declaration": declaration,
    }


def _build_application(walker_output: WalkerOutput, *, partition: str) -> dict[str, Any]:
    """Assemble one AS3 Application containing every extracted object.

    Order of construction is monitor → persist → profile → iRule → pool
    → virtual, which is the dependency order: virtuals reference pools
    (and rules, persists, profiles); pools reference monitors. Producing
    the dependent objects first keeps the application dict construction
    readable; AS3 itself doesn't require a specific declaration order.
    """
    app: dict[str, Any] = {
        "class": "Application",
        "template": "generic",
    }
    # Monitors — filter built-ins.
    for monitor in filter_builtins(walker_output.monitors_http):
        app[monitor["name"]] = _monitor_http(monitor)
    # Persistence — filter built-ins.
    for persist in filter_builtins(walker_output.persistence_cookie):
        app[persist["name"]] = _persist_cookie(persist)
    # ClientSSL profiles — filter built-ins.
    for profile in filter_builtins(walker_output.profiles_clientssl):
        app[profile["name"]] = _profile_clientssl(profile)
    # iRules — filter built-ins.
    for rule in filter_builtins(walker_output.rules):
        app[rule["name"]] = _irule(rule)
    # Pools — virtuals/operator-owned, no built-in filter.
    for pool in walker_output.pools:
        app[pool["name"]] = _pool(pool)
    # Virtuals — same.
    for virtual in walker_output.virtuals:
        app[virtual["name"]] = _virtual(virtual, partition=partition)
    return app


def _monitor_http(monitor: dict[str, Any]) -> dict[str, Any]:
    """Map iControl REST monitor/http to AS3 Monitor.

    Field rename: iControl REST `recv` → AS3 `receive`. Confirmed by
    three independent primary sources, all consistent:

    1. F5 iControl REST API reference for HTTP monitor declares `recv`
       as the response-expectation field on the wire:
       https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_monitor_http.html
       (verified in Checkpoint 1 fixture under mock-f5/app/fixtures/ltm/
       monitor_http.py).

    2. ACC (f5-automation-config-converter) v1.24.0
       src/lib/AS3/customMaps/monitor.js line 137 declares the
       `'ltm monitor http'` keyValueRemap as
       `receive: (key, val) => ({ receive: ... })` — explicitly emitting
       the AS3 field name `receive`.
       https://github.com/f5devcentral/f5-automation-config-converter/blob/v1.24.0/src/lib/AS3/customMaps/monitor.js#L137

    3. F5's own published AS3 HTTP-monitor declaration example uses
       `"receive": "HTTP/2."`:
       https://github.com/F5Networks/f5-appsvcs-extension/blob/v3.51.0/examples/declarations/example-http2-monitor.json

    Send and recv strings are carried verbatim including embedded CRLF.
    """
    out: dict[str, Any] = {
        "class": "Monitor",
        "monitorType": "http",
        "interval": int(monitor.get("interval", 5)),
        "timeout": int(monitor.get("timeout", 16)),
        "send": monitor.get("send", "GET /\r\n"),
        "receive": monitor.get("recv", ""),
    }
    return out


def _persist_cookie(persist: dict[str, Any]) -> dict[str, Any]:
    """Map iControl REST persistence/cookie to AS3 Persist cookie.

    F5 `method` field maps to AS3's persistence method. We only handle
    the `insert` mode here — the most common; other modes (rewrite,
    passive, hash) deferred to a later PR per ADR 007 §Out of scope.
    """
    out: dict[str, Any] = {
        "class": "Persist",
        "persistenceMethod": "cookie",
        "cookieMethod": persist.get("method", "insert"),
    }
    if (cookie_name := persist.get("cookieName")) and cookie_name != "none":
        out["cookieName"] = cookie_name
    return out


def _profile_clientssl(profile: dict[str, Any]) -> dict[str, Any]:
    """Map iControl REST profile/client-ssl to AS3 TLS_Server.

    AS3's ClientSSL profile class is `TLS_Server` (terminology mirror —
    "server" from the BIG-IP's perspective is the side that terminates
    the client's TLS). The certKeyChain array becomes AS3's
    `certificates` list.
    """
    certificates = []
    for entry in profile.get("certKeyChain", []):
        cert_entry: dict[str, Any] = {
            "certificate": entry["cert"],
            "key": entry["key"],
        }
        if chain := entry.get("chain"):
            cert_entry["chain"] = chain
        certificates.append(cert_entry)
    return {
        "class": "TLS_Server",
        "certificates": certificates,
    }


def _irule(rule: dict[str, Any]) -> dict[str, Any]:
    """Map iControl REST rule to AS3 iRule with verbatim TCL body.

    The TCL body in `apiAnonymous` is passed through unchanged — AS3's
    iRule class accepts the raw TCL via the `iRule` field. Operators
    hand-review for deprecation against the target TMOS version per
    ADR 007 §Consequences.
    """
    return {
        "class": "iRule",
        "iRule": rule.get("apiAnonymous", ""),
    }


def _pool(pool: dict[str, Any]) -> dict[str, Any]:
    """Map iControl REST pool (with embedded _members from the walker)
    to AS3 Pool.

    Monitor reference: F5 pool.monitor is a space-separated path string
    (`/Common/example_http_monitor`). For the simple single-monitor
    case, AS3 accepts a string list `["example_http_monitor"]`
    referencing the tenant-local monitor. Multi-monitor "min N of { ... }"
    parsing is deferred to a later PR per ADR 007 §Out of scope.
    """
    members = []
    for m in pool.get("_members", []):
        members.append(
            {
                "servicePort": _member_port(m["name"]),
                "serverAddresses": [m["address"]],
                "enable": m.get("session") == "user-enabled",
            }
        )
    out: dict[str, Any] = {
        "class": "Pool",
        "loadBalancingMode": pool.get("loadBalancingMode", "round-robin"),
        "members": members,
    }
    if monitor_ref := pool.get("monitor"):
        out["monitors"] = [_monitor_ref_name(monitor_ref)]
    return out


def _member_port(member_name: str) -> int:
    """Pool member `name` is `<address>:<port>`. Extract the integer port."""
    _, _, port_str = member_name.rpartition(":")
    return int(port_str)


def _monitor_ref_name(monitor_ref: str) -> str:
    """Reduce a F5 monitor path reference to a simple tenant-local name.

    `/Common/example_http_monitor` → `example_http_monitor`. Multi-
    monitor `min N of { /Common/a /Common/b }` syntax is deferred per
    ADR 007 §Out of scope; surfaces here as an opaque string the
    operator must hand-fix until that path is supported.
    """
    return monitor_ref.rsplit("/", 1)[-1]


def _virtual(virtual: dict[str, Any], *, partition: str) -> dict[str, Any]:
    """Map iControl REST virtual to AS3 Service_HTTP / Service_HTTPS / etc.

    Service class selection is driven by profiles:
      - clientssl profile present → Service_HTTPS
      - http profile present, no clientssl → Service_HTTP
      - neither → Service_TCP (fallback for plain L4 virtuals)

    UDP virtuals would map to Service_UDP but require ipProtocol=='udp'
    detection — deferred to when the mock fixture exercises that case.
    """
    address, port = parse_destination(virtual["destination"])
    profile_paths = list(virtual.get("profiles", {}).keys())
    has_clientssl = any(
        not p.startswith("/Common/") or _profile_simple_name(p) not in BIGIP_BUILTIN_PROFILE_NAMES
        for p in profile_paths
        if "clientssl" in p
    )
    has_http_profile = any(_profile_simple_name(p) in {"http", "http2"} for p in profile_paths)
    if has_clientssl:
        service_class = "Service_HTTPS"
    elif has_http_profile:
        service_class = "Service_HTTP"
    else:
        service_class = "Service_TCP"
    out: dict[str, Any] = {
        "class": service_class,
        "virtualAddresses": [address],
        "virtualPort": port,
    }
    if pool_ref := virtual.get("pool"):
        out["pool"] = _profile_simple_name(pool_ref)
    if service_class == "Service_HTTPS":
        clientssl_paths = [p for p in profile_paths if "clientssl" in p]
        custom = [
            p for p in clientssl_paths if _profile_simple_name(p) not in BIGIP_BUILTIN_PROFILE_NAMES
        ]
        if custom:
            out["serverTLS"] = _profile_simple_name(custom[0])
    if irules := virtual.get("rules"):
        out["iRules"] = [_profile_simple_name(p) for p in irules]
    if persists := virtual.get("persist"):
        out["persistenceMethods"] = [{"use": _profile_simple_name(p)} for p in persists]
    _ = partition  # signal that partition is part of context, intentionally unused here
    return out


def _profile_simple_name(profile_path: str) -> str:
    """Reduce `/Common/foo` to `foo` for tenant-local references."""
    return profile_path.rsplit("/", 1)[-1]
