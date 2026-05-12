"""Structural-schema gate for terraform-rendered F5 DO and AS3 declarations.

This file does not test the mock server. It tests the *terraform templates*
in `terraform/modules/{do,as3}-declaration/templates/` against the structural
constraints that real F5 BIG-IP DO/AS3 enforce. It lives in the mock-f5 test
suite because that suite already runs in `make test-unit` and provides the
pytest + uv environment.

Why this exists: PR 3 iteration 8 surfaced a malformed DO declaration shape
(schemaVersion duplicated at both outer DO and inner Device class levels)
that real F5 DO 1.47.0 rejected with HTTP 400 / additionalProperties. The
mock had accepted it for the entire PR 1-3 history because the mock's own
test fixture used the same malformed shape — a closed loop of "mock trains
itself on bad input." This file is the gate that breaks that loop: it
validates the rendered terraform output against F5's schema-level rules
directly, independent of the mock. See ADR 005 and PR 8 for context.

The renderer is a minimal `templatefile()` emulator — it handles the
patterns the current templates use and intentionally fails loudly on any
new pattern so a template change that needs new emulator support shows
up here rather than silently in production.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_DO_TEMPLATE_REL = "terraform/modules/do-declaration/templates/do.json.tftpl"
_AS3_TEMPLATE_REL = "terraform/modules/as3-declaration/templates/as3.json.tftpl"
DO_TEMPLATE = REPO_ROOT / _DO_TEMPLATE_REL
AS3_TEMPLATE = REPO_ROOT / _AS3_TEMPLATE_REL


def _render_tftpl(text: str, vars: dict[str, Any]) -> str:
    """Minimal terraform `templatefile()` emulator.

    Supports the patterns used by the templates under test. Intentionally
    NOT a full HCL evaluator — any new template construct needs explicit
    support added here so the test failure surfaces in CI, not on a real VE.

    Supported:
      - `${var}`                                     plain interpolation
      - `${var.field}`                               struct field access
      - `${var[N].field}`                            list-of-struct access
      - `${jsonencode(var)}`                         JSON-encode whole var
      - `${jsonencode([for X in LIST : X.field])}`   JSON-encode projection
      - `${EXPR * N + N}`                            arithmetic for monitor timing
      - `%{ if length(VAR) > 0 }...%{ endif }`       empty-list short-circuit
    """

    # 1. Conditional blocks: keep body iff the named list is non-empty.
    #    Greedy match — the outer block may contain nested %{ if/for } whose
    #    own %{ endif/endfor } markers must not terminate the outer match.
    #    Templates under test contain exactly one outer if-block; if a future
    #    template adds a second, this needs a balanced matcher.
    def _strip_empty_if(m: re.Match[str]) -> str:
        return m.group(2) if vars.get(m.group(1)) else ""

    text = re.sub(
        r"%\{ if length\((\w+)\) > 0 \}(.*)%\{ endif \}",
        _strip_empty_if,
        text,
        flags=re.DOTALL,
    )

    # 2. jsonencode of a list comprehension projection.
    def _encode_projection(m: re.Match[str]) -> str:
        source, field = m.group(2), m.group(3)
        return json.dumps([item[field] for item in vars[source]])

    text = re.sub(
        r"\$\{jsonencode\(\[for (\w+) in (\w+) : \1\.(\w+)\]\)\}",
        _encode_projection,
        text,
    )

    # 3. Plain jsonencode of a whole var.
    text = re.sub(
        r"\$\{jsonencode\((\w+)\)\}",
        lambda m: json.dumps(vars[m.group(1)]),
        text,
    )

    # 4. Arithmetic: ${var * N + N} (monitor_interval timing).
    text = re.sub(
        r"\$\{(\w+)\s*\*\s*(\d+)\s*\+\s*(\d+)\}",
        lambda m: str(vars[m.group(1)] * int(m.group(2)) + int(m.group(3))),
        text,
    )

    # 5. List-of-struct field access: ${var[N].field}.
    text = re.sub(
        r"\$\{(\w+)\[(\d+)\]\.(\w+)\}",
        lambda m: str(vars[m.group(1)][int(m.group(2))][m.group(3)]),
        text,
    )

    # 6. Struct field access: ${var.field}.
    text = re.sub(
        r"\$\{(\w+)\.(\w+)\}",
        lambda m: str(vars[m.group(1)][m.group(2)]),
        text,
    )

    # 7. Plain interpolation: ${var}.
    text = re.sub(
        r"\$\{(\w+)\}",
        lambda m: str(vars[m.group(1)]),
        text,
    )

    return text


def test_do_declaration_is_direct_device_class() -> None:
    """F5 DO 1.47.0's API accepts only `class: "Device"` at the root —
    the `class: "DO"` outer wrapper is not part of F5's published schema
    (confirmed against F5 DO base.schema.json, F5's own examples in the
    f5-declarative-onboarding and f5-bigip-runtime-init repos, and the
    terraform-provider-bigip's own bigip_onboard.tf example). PR 3 iter-7
    through iter-9 chased this misconception in the original PR 1 template.
    Asserting the direct-Device shape so a regression that re-introduces
    the wrapper surfaces here, not on the next cloud round-trip."""
    rendered = _render_tftpl(
        DO_TEMPLATE.read_text(),
        {
            "device_hostname": "bigip-test.example.invalid",
            "dns_servers": ["10.0.0.2"],
            "ntp_servers": ["10.0.0.3"],
            "timezone": "UTC",
            "vlans": [],
        },
    )
    doc = json.loads(rendered)

    assert doc["class"] == "Device", (
        f"DO declaration must use direct Device class at root, "
        f"not a wrapper. Got class={doc.get('class')!r}"
    )
    assert "schemaVersion" in doc, "Device class requires schemaVersion at root"
    assert "declaration" not in doc, (
        "DO declaration must NOT have an outer 'declaration' wrapper — "
        "that shape is rejected by F5 DO 1.47.0's API "
        "(class const must be 'Device', not 'DO')"
    )
    assert doc["Common"]["class"] == "Tenant"


def test_as3_declaration_inner_adc_has_schema_version() -> None:
    """F5 AS3's ADC class *requires* `schemaVersion` (opposite of DO's
    Device class). Asserting it explicitly so a future template edit
    that drops it surfaces here, not in a cloud round-trip."""
    rendered = _render_tftpl(
        AS3_TEMPLATE.read_text(),
        {
            "device_hostname": "bigip-test.example.invalid",
            "tenant_name": "test_tenant",
            "app_name": "test_app",
            "vip_address": "10.98.10.10",
            "pool_members": [
                {"ip": "10.98.20.10", "port": 8080},
                {"ip": "10.98.20.11", "port": 8080},
            ],
            "monitor_interval": 5,
        },
    )
    doc = json.loads(rendered)

    assert doc["class"] == "AS3"
    assert doc["action"] == "deploy"
    assert "declaration" in doc

    inner = doc["declaration"]
    assert inner["class"] == "ADC"
    assert "schemaVersion" in inner, (
        "AS3 ADC declaration MUST carry schemaVersion (required by F5 AS3 schema)"
    )
    assert "test_tenant" in inner
    assert inner["test_tenant"]["class"] == "Tenant"


def test_do_template_renders_valid_json() -> None:
    """Renders cleanly to JSON with realistic inputs (catches template
    syntax errors like missing commas or unmatched quotes that would
    otherwise only surface mid-apply)."""
    rendered = _render_tftpl(
        DO_TEMPLATE.read_text(),
        {
            "device_hostname": "bigip-aws-new.nexusf5.local",
            "dns_servers": ["10.98.0.2", "10.98.0.3"],
            "ntp_servers": ["pool.ntp.org"],
            "timezone": "UTC",
            "vlans": [],
        },
    )
    json.loads(rendered)  # raises if not valid JSON


def test_as3_template_renders_valid_json() -> None:
    """Same JSON-parse gate for AS3 as for DO."""
    rendered = _render_tftpl(
        AS3_TEMPLATE.read_text(),
        {
            "device_hostname": "bigip-aws-new.nexusf5.local",
            "tenant_name": "nexusf5_immutable",
            "app_name": "demo_app",
            "vip_address": "10.98.10.10",
            "pool_members": [{"ip": "10.98.20.10", "port": 80}],
            "monitor_interval": 5,
        },
    )
    json.loads(rendered)
