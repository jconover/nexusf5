"""Shape helpers: parsers and identifier normalizers shared across emitters.

Centralizes the small string-manipulation primitives that the AS3, DO,
Terraform, and README emitters all need so the normalizations applied
to extracted data are defined in exactly one place. Used by the
emit modules; not part of the public package surface.
"""

from __future__ import annotations


def parse_destination(destination: str) -> tuple[str, int]:
    """Parse an F5 virtual `destination` string into (address, port).

    F5 wire format is `/<partition>/<address>:<port>`. Examples:
      /Common/10.1.10.10:443 → ("10.1.10.10", 443)
      /Common/0.0.0.0:80     → ("0.0.0.0", 80)

    Per ADR 007 §Out of scope, IPv6 addresses (which use `.` as the
    port delimiter, not `:`) and route-domain specifiers (`%N`) are NOT
    handled in the first cut. Calling parse_destination with such a
    string surfaces a ValueError so the bug is loud, not silent.
    """
    if not destination.startswith("/"):
        raise ValueError(f"destination must start with /partition/: got {destination!r}")
    # Strip leading "/", then the partition segment.
    parts = destination.lstrip("/").split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"destination missing address segment: {destination!r}")
    addr_port = parts[1]
    addr, sep, port_str = addr_port.rpartition(":")
    if not sep:
        raise ValueError(
            f"destination missing :port (IPv6 or route-domain not supported in first cut): "
            f"{destination!r}"
        )
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"destination port not an integer: {destination!r}") from exc
    return addr, port


def hostname_to_tf_identifier(hostname: str) -> str:
    """Normalize an F5 device hostname into a snake_case Terraform
    identifier per ADR 007 Addendum 2026-05-13.

    F5 hostnames per CLAUDE.md follow `bigip-{site}-{number}` — hyphens.
    HCL identifier syntax allows hyphens, but project convention
    (terraform/modules/*) is snake_case. The brownfield emitter
    normalizes only the Terraform resource name; the hostname stays
    as-is for provider config and API calls, and the AS3 tenant stays
    literal-partition-name.

    Examples:
      bigip-lab-01    → bigip_lab_01
      bigip-dc1-042   → bigip_dc1_042
    """
    return hostname.replace("-", "_")


def tf_resource_name(hostname: str, partition: str) -> str:
    """Build the device-scoped Terraform resource name for a brownfield
    extraction.

    Format: `<normalized_hostname>_<partition>`.

    Examples:
      bigip-lab-01 + Common → bigip_lab_01_Common

    Both `bigip_as3` and `bigip_do` resources for the same device+
    partition reuse this name, scoped only by resource type. Multi-
    device disambiguation lives at this identifier per ADR 007
    Addendum 2026-05-13.
    """
    return f"{hostname_to_tf_identifier(hostname)}_{partition}"


def strip_ver_query(self_link: str) -> str:
    """Drop the `?ver=` query suffix that F5 appends to selfLinks.

    Used by the README emitter so the documented "extracted objects"
    list is stable across F5 version pulses — `?ver=17.1.0` becomes
    `?ver=17.1.0.1` on a patch and would otherwise churn the README on
    every patch even when the extracted shape is unchanged.

    The walker preserves the ver suffix on selfLinks as provenance
    (Checkpoint 2 normalization choice); the README emitter strips it
    for the human-readable summary.
    """
    return self_link.split("?", 1)[0]
