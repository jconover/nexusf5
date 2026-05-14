"""Vendored list of F5 BIG-IP built-in objects under /Common.

These are objects F5 ships pre-populated on every BIG-IP device. The
brownfield extractor must filter them out when walking /Common, because
emitting them in an AS3 declaration would cause `terraform apply` to
either fail (duplicate object) or overwrite F5's defaults.

# Provenance

| Field | Value |
|---|---|
| Upstream repo | https://github.com/f5devcentral/f5-automation-config-converter |
| Upstream path | `src/lib/bigipDefaults.json` |
| Upstream tag | `v1.24.0` |
| Upstream commit | `e6f9fcec` |
| Access date | 2026-05-13 |
| Entry count | 234 |

Refresh protocol matches the vendored-schemas pattern (mock-f5/schemas/README.md):
explicit version bumps, cite the same fields above, run the test suite to
catch any name divergence.

# Filter semantics

`is_builtin(item)` is true ONLY when both:

  1. `partition == "Common"` — built-ins live in /Common per F5 convention.
  2. `fullPath` exact-matches an entry in BIGIP_BUILTINS.

Both gates are required. A custom monitor at `/CustomTenant/http` is NOT
filtered (custom partition wins), even though `http` is on the list — this
is the operator-named-collision safety property: name collisions are
disambiguated by partition, the filter never over-reaches into a custom
partition's namespace.

A custom monitor literally placed at `/Common/http` would be filtered.
F5 reserves built-in names in /Common (TMSH typically rejects shadowing),
so this case is contrived in practice; the unit test
`test_operator_named_collision_in_custom_partition_is_extracted` covers
the realistic version of the operator-collision scenario.

# Single source of truth

This module is the only place that knows about F5 built-ins. The emitter
imports `filter_builtins`; the tests import `BIGIP_BUILTINS` to verify
emission excludes every entry. Future contributors update both the
constant and the provenance table when refreshing the upstream pin.
"""

from __future__ import annotations

from typing import Any

# Sourced verbatim from
# https://github.com/f5devcentral/f5-automation-config-converter/blob/v1.24.0/src/lib/bigipDefaults.json
# (commit e6f9fcec, accessed 2026-05-13). Keep entries in upstream order so
# diffs against future refreshes are trivial to review — do NOT alphabetize.
BIGIP_BUILTINS: frozenset[str] = frozenset(
    {
        "/Common/0",
        "/Common/__appsvcs_update",
        "/Common/_sys_APM_ExchangeSupport_OA_BasicAuth",
        "/Common/_sys_APM_ExchangeSupport_OA_NtlmAuth",
        "/Common/_sys_APM_ExchangeSupport_helper",
        "/Common/_sys_APM_ExchangeSupport_main",
        "/Common/_sys_APM_MS_Office_OFBA_Support",
        "/Common/_sys_APM_Office365_SAML_BasicAuth",
        "/Common/_sys_APM_activesync",
        "/Common/_sys_auth_krbdelegate",
        "/Common/_sys_auth_ldap",
        "/Common/_sys_auth_radius",
        "/Common/_sys_auth_ssl_cc_ldap",
        "/Common/_sys_auth_ssl_crldp",
        "/Common/_sys_auth_ssl_ocsp",
        "/Common/_sys_auth_tacacs",
        "/Common/_sys_https_redirect",
        "/Common/_sys_radius_proto_all",
        "/Common/_sys_radius_proto_imsi",
        "/Common/_sys_self_allow_tcp_defaults",
        "/Common/_sys_self_allow_udp_defaults",
        "/Common/_sys_self_allow_all",
        "/Common/_sys_self_allow_defaults",
        "/Common/_sys_self_allow_management",
        "/Common/acrobat",
        "/Common/admin",
        "/Common/alg_log_profile",
        "/Common/all-match",
        "/Common/anonymous",
        "/Common/aol",
        "/Common/apm-default-serverssl",
        "/Common/apm-enduser-if-cache",
        "/Common/apm-forwarding-client-tcp",
        "/Common/apm-forwarding-fastL4",
        "/Common/apm-forwarding-server-tcp",
        "/Common/arg_example",
        "/Common/aws-ec2",
        "/Common/best-match",
        "/Common/bigip",
        "/Common/bot-defense",
        "/Common/botnets",
        "/Common/ca-bundle",
        "/Common/ca-bundle.crt",
        "/Common/ce_apm_swg",
        "/Common/cist",
        "/Common/classification_apm_swg",
        "/Common/classification_pem",
        "/Common/clientldap",
        "/Common/clientssl",
        "/Common/clientssl-insecure-compatible",
        "/Common/clientssl-quic",
        "/Common/clientssl-secure",
        "/Common/cloud-service-default-ssl",
        "/Common/cookie",
        "/Common/Crawler",
        "/Common/crypto-client-default-serverssl",
        "/Common/crypto-server-default-clientssl",
        "/Common/Default",
        "/Common/default",
        "/Common/default.crt",
        "/Common/default.key",
        "/Common/default-ipsec-log-publisher",
        "/Common/default-ipsec-policy",
        "/Common/default-ipsec-policy-interface",
        "/Common/default-ipsec-policy-isession",
        "/Common/default-mgmt-acl-log-publisher",
        "/Common/default-traffic-selector-interface",
        "/Common/device_trust_group",
        "/Common/dest_addr",
        "/Common/dhcpv4",
        "/Common/dhcpv4_fwd",
        "/Common/dhcpv6",
        "/Common/dhcpv6_fwd",
        "/Common/diameter",
        "/Common/diametersession",
        "/Common/diameter-endpoint",
        "/Common/dnet",
        "/Common/dns",
        "/Common/do-not-remove-without-replacement",
        "/Common/dos",
        "/Common/dos-udp-portlist",
        "/Common/DOS Tool",
        "/Common/dtca-bundle.crt",
        "/Common/dtca.crt",
        "/Common/dtca.key",
        "/Common/dtdi.crt",
        "/Common/dtdi.key",
        "/Common/dynamic_spm_bwc_policy",
        "/Common/Exploit Tool",
        "/Common/f5-aes",
        "/Common/f5-ca-bundle",
        "/Common/f5-default",
        "/Common/f5-ecc",
        "/Common/f5-hw_keys",
        "/Common/f5-irule",
        "/Common/f5-quic",
        "/Common/f5-secure",
        "/Common/f5-tcp-lan",
        "/Common/f5-tcp-mobile",
        "/Common/f5-tcp-progressive",
        "/Common/f5-tcp-wan",
        "/Common/f5_api_com",
        "/Common/f5aas-default-ssl",
        "/Common/fastL4",
        "/Common/fasthttp",
        "/Common/first-match",
        "/Common/fix",
        "/Common/ftp",
        "/Common/full-acceleration",
        "/Common/gateway_icmp",
        "/Common/gtm",
        "/Common/gtp",
        "/Common/hash",
        "/Common/host",
        "/Common/html",
        "/Common/http",
        "/Common/http-explicit",
        "/Common/http-proxy-connect",
        "/Common/http-transparent",
        "/Common/http-tunnel",
        "/Common/http2",
        "/Common/http_head_f5",
        "/Common/httpcompression",
        "/Common/httprouter",
        "/Common/https",
        "/Common/https_443",
        "/Common/https_head_f5",
        "/Common/icap",
        "/Common/icmp",
        "/Common/images",
        "/Common/inband",
        "/Common/internal",
        "/Common/ipother",
        "/Common/ipsecalg",
        "/Common/ip-intelligence",
        "/Common/isession",
        "/Common/isession-encrypt",
        "/Common/isession-mapi",
        "/Common/isession-softwoc",
        "/Common/krbdelegate",
        "/Common/ldap",
        "/Common/local-db-publisher",
        "/Common/mptcp-mobile-optimized",
        "/Common/msrdp",
        "/Common/Music",
        "/Common/netflow",
        "/Common/ntlm",
        "/Common/oauthdb",
        "/Common/oneconnect",
        "/Common/optimized-acceleration",
        "/Common/optimized-caching",
        "/Common/paap_version_monitor",
        "/Common/pcoip-default-serverssl",
        "/Common/pcp",
        "/Common/pptp",
        "/Common/private_net",
        "/Common/qoe",
        "/Common/radius",
        "/Common/radiusaaa",
        "/Common/radiusLB",
        "/Common/radiusLB-subscriber-aware",
        "/Common/real_server",
        "/Common/request-log",
        "/Common/requestadapt",
        "/Common/responseadapt",
        "/Common/rewrite",
        "/Common/rewrite-portal",
        "/Common/rewrite-uri-translation",
        "/Common/Root",
        "/Common/rtsp",
        "/Common/sample_monitor",
        "/Common/scrubber-profile-default",
        "/Common/sctp",
        "/Common/Search Engine",
        "/Common/security-fastL4",
        "/Common/serverldap",
        "/Common/serverssl",
        "/Common/serverssl-insecure-compatible",
        "/Common/shape-api-ssl",
        "/Common/sip",
        "/Common/sip_info",
        "/Common/sipsession",
        "/Common/sipsession-alg",
        "/Common/smtps",
        "/Common/snmp_dca",
        "/Common/socks",
        "/Common/socks-tunnel",
        "/Common/source_addr",
        "/Common/splitsession-default-clientssl",
        "/Common/splitsession-default-serverssl",
        "/Common/splitsession-default-tcp",
        "/Common/splitsessionclient",
        "/Common/splitsessionserver",
        "/Common/spm",
        "/Common/ssl",
        "/Common/ssl_cc_ldap",
        "/Common/ssl_crldp",
        "/Common/ssl_ocsp",
        "/Common/stats",
        "/Common/stream",
        "/Common/subscriber-mgmt",
        "/Common/sys-db-access-publisher",
        "/Common/sys-sslo-publisher",
        "/Common/sys-sso-access-publisher",
        "/Common/sys_APM_MS_Office_OFBA_DG",
        "/Common/tacacs",
        "/Common/tcp",
        "/Common/tcp-lan-optimized",
        "/Common/tcp-legacy",
        "/Common/tcp-mobile-optimized",
        "/Common/tcp-wan-optimized",
        "/Common/tcp_echo",
        "/Common/tcp_half_open",
        "/Common/tftp",
        "/Common/traffic-group-1",
        "/Common/traffic-group-local-only",
        "/Common/udp",
        "/Common/udp_decrement_ttl",
        "/Common/udp_gtm_dns",
        "/Common/udp_preserve_ttl",
        "/Common/universal",
        "/Common/uuid_entity_id",
        "/Common/vsphere",
        "/Common/wam-tcp-lan-optimized",
        "/Common/wam-tcp-wan-optimized",
        "/Common/wan-optimized-compression",
        "/Common/webacceleration",
        "/Common/websocket",
        "/Common/wom-default-clientssl",
        "/Common/wom-default-serverssl",
        "/Common/wom-tcp-lan-optimized",
        "/Common/wom-tcp-wan-optimized",
        "/Common/xml",
        "/Common/Yandex",
    }
)


def is_builtin(item: dict[str, Any]) -> bool:
    """Return True if an extracted F5 object is a stock built-in.

    Treat as built-in ONLY when both:
      - partition is 'Common' (built-ins live in /Common)
      - fullPath exact-matches an entry in BIGIP_BUILTINS

    A custom monitor at `/CustomTenant/http` is NOT a built-in even
    though `http` is on the list — the partition gate is the
    disambiguator that prevents over-reach into custom partitions.
    """
    if item.get("partition") != "Common":
        return False
    full_path = item.get("fullPath")
    return isinstance(full_path, str) and full_path in BIGIP_BUILTINS


def filter_builtins(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop F5 built-ins from a walker's items list.

    Returns a NEW list in input order; does not mutate the input.
    Operator-named objects pass through unchanged.
    """
    return [item for item in items if not is_builtin(item)]


# Profile-type built-in names AS3 recognizes as references without needing
# the operator to declare them. These are stock F5 profile-class objects
# the AS3 emitter (brownfield.emit.as3) checks when deciding whether a
# `/Common/<name>` profile reference on a virtual is a built-in to
# bypass-but-not-declare or a custom profile to embed.
#
# Provenance: each name is the basename of an entry in BIGIP_BUILTINS
# above; the subset is hand-curated to AS3-recognized PROFILE-class
# names (vs. monitor/persistence/iRule names, which the BIGIP_BUILTINS
# list also contains but which AS3 references with different syntaxes).
# Categorization source: F5 iControl REST API reference, profile-class
# endpoint families:
#   https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_http.html
#   https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_tcp.html
#   https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_client-ssl.html
#   https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_server-ssl.html
#   https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_one-connect.html
#
# Drift guard: the assertion below confirms every entry exists in
# BIGIP_BUILTINS. A refresh of the ACC list that removes one of these
# entries fails import — surfacing the divergence at load time rather
# than at runtime.
BIGIP_BUILTIN_PROFILE_NAMES: frozenset[str] = frozenset(
    {
        "http",
        "http2",
        "tcp",
        "tcp-lan-optimized",
        "tcp-wan-optimized",
        "udp",
        "fastL4",
        "clientssl",
        "serverssl",
        "oneconnect",
    }
)

# Drift guard — each profile name MUST be in BIGIP_BUILTINS. If a future
# ACC refresh drops one of these, this assertion surfaces the drift on
# `from brownfield import builtins`, not later when the emitter under-
# filters at runtime.
_MISSING = {name for name in BIGIP_BUILTIN_PROFILE_NAMES if f"/Common/{name}" not in BIGIP_BUILTINS}
assert not _MISSING, (
    f"BIGIP_BUILTIN_PROFILE_NAMES has entries not in BIGIP_BUILTINS: {_MISSING}. "
    "An ACC refresh likely dropped these — verify against the upstream list and "
    "either remove from the profile-names subset or add to the ACC pin."
)
del _MISSING
